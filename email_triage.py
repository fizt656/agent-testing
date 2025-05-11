import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
from openai import OpenAI
from pydantic import BaseModel
from typing import List, Optional, Literal
import re
import base64
from email.mime.text import MIMEText 
import sys 

# Import utilities
from email_utils import get_gmail_service, TermColors 

from googleapiclient.errors import HttpError # Keep HttpError for exception handling

# Load environment variables
load_dotenv(override=True)

# --- Configuration ---
# Gmail API Scopes needed by THIS script
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send'] 

# Determine the absolute path to THIS script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

class EmailImportance(BaseModel):
    importance: Literal["high", "medium", "low"]
    reason: str
    needs_response: bool
    time_sensitive: bool
    topics: List[str]

# File paths
RECENT_EMAILS_FILE = "recent_emails.txt" # Should be SCRIPT_DIR relative
RESPONSE_HISTORY_FILE = os.path.join(SCRIPT_DIR, "response_history.json")
NEEDS_RESPONSE_JSON = os.path.join(SCRIPT_DIR, "needs_response_emails.json")
NEEDS_RESPONSE_REPORT = os.path.join(SCRIPT_DIR, "needs_response_report.md") # Changed to .md


def load_response_history():
    """Load history of emails we've already responded to"""
    try:
        with open(RESPONSE_HISTORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except (FileNotFoundError, json.JSONDecodeError):
        return {"responded_emails": []}

def save_response_history(history, new_response=None):
    """Save history of emails we've already responded to"""
    if new_response:
        history["responded_emails"].append({
            "subject": new_response["subject"],
            "from": new_response["from"],
            "responded_at": datetime.now().isoformat()
        })
    
    with open(RESPONSE_HISTORY_FILE, "w", encoding="utf-8") as f:
        json.dump(history, f, indent=2)

def is_previously_responded(email, sent_emails):
    """Check if we've already responded to this email"""
    from_match = re.search(r'<(.+?)>', email.get('from', ''))
    sender_email = from_match.group(1).lower() if from_match else None
    
    if not sender_email:
        return False
    
    subject = email.get('subject', '').lower()
    clean_subject = re.sub(r'^(?:re|fwd):\s*', '', subject, flags=re.IGNORECASE)
    
    for sent_email in sent_emails:
        if sender_email in sent_email.get('recipients', []):
            sent_subject = sent_email.get('subject', '').lower()
            clean_sent_subject = re.sub(r'^(?:re|fwd):\s*', '', sent_subject, flags=re.IGNORECASE)
            if clean_subject == clean_sent_subject or clean_subject in clean_sent_subject or clean_sent_subject in clean_subject:
                return True
    return False

def get_emails(service, query, hours=24): # Added query parameter
    """
    Fetches emails from Gmail from the last {hours} hours using the provided query and saves to RECENT_EMAILS_FILE.
    """
    if not service:
        print(f"{TermColors.STATUS_ERROR}Failed to get Gmail service in get_emails (service not provided).{TermColors.RESET}")
        return []

    emails_data = []
    query_date = (datetime.now() - timedelta(hours=hours)).strftime('%Y/%m/%d')
    # query = f'after:{query_date} is:unread category:primary' # Query is now passed in

    # Construct the final query string including the date filter
    final_query = f'after:{query_date} {query}'

    try:
        response = service.users().messages().list(userId='me', q=final_query, maxResults=50).execute() # Use final_query
        messages = response.get('messages', [])
        
        # Ensure RECENT_EMAILS_FILE is SCRIPT_DIR relative
        recent_emails_file_path = os.path.join(SCRIPT_DIR, RECENT_EMAILS_FILE)

        with open(recent_emails_file_path, "w", encoding="utf-8") as f_out:
            for message_info in messages:
                msg_id = message_info['id']
                msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
                
                payload = msg.get('payload', {})
                headers = payload.get('headers', [])
                
                subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
                from_sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
                received_date_unix = int(msg.get('internalDate', '0')) / 1000
                received_date = datetime.fromtimestamp(received_date_unix).isoformat()

                body_content = ""
                if 'parts' in payload:
                    for part in payload['parts']:
                        if part['mimeType'] == 'text/plain':
                            body_data = part['body'].get('data')
                            if body_data:
                                body_content += base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
                            break 
                    if not body_content: 
                         for part in payload['parts']:
                            if part['mimeType'] == 'text/html':
                                body_data = part['body'].get('data')
                                if body_data:
                                    html_content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
                                    body_content += re.sub('<[^<]+?>', '', html_content) 
                                break
                elif 'body' in payload and payload['body'].get('data'):
                    body_data = payload['body']['data']
                    body_content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
                    if payload.get('mimeType') == 'text/html':
                        body_content = re.sub('<[^<]+?>', '', body_content)

                email_detail = {
                    'subject': subject, 'from': from_sender,
                    'receivedDateTime': received_date, 'body': body_content.strip()
                }
                emails_data.append(email_detail)

                f_out.write(f"Subject: {subject}\nFrom: {from_sender}\nReceived: {received_date}\nBody: {body_content.strip()}\n" + "-" * 50 + "\n")

        print(f"{TermColors.STATUS_INFO}Fetched {len(emails_data)} emails from the last {hours} hours.{TermColors.RESET}")
        if not emails_data:
            # Ensure file is empty if no emails
            with open(recent_emails_file_path, 'w', encoding='utf-8') as f_out_empty:
                 f_out_empty.write("")
            print(f"{TermColors.YELLOW}{recent_emails_file_path} is empty as no new emails were found.{TermColors.RESET}")

    except HttpError as error:
        print(f"{TermColors.STATUS_ERROR}An error occurred fetching emails: {error}{TermColors.RESET}")
        with open(os.path.join(SCRIPT_DIR, RECENT_EMAILS_FILE), 'w', encoding='utf-8') as f_out_err: # ensure empty on error
             f_out_err.write("")
        print(f"{TermColors.YELLOW}{os.path.join(SCRIPT_DIR, RECENT_EMAILS_FILE)} is empty due to an error.{TermColors.RESET}")
    
    return emails_data

def get_sent_emails(service, days=7): # Added service parameter
    """ Fetches sent emails from Gmail from the past {days} days. """
    # service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES) # Service is now passed in
    if not service:
        print(f"{TermColors.STATUS_ERROR}Failed to get Gmail service in get_sent_emails (service not provided).{TermColors.RESET}")
        return []

    sent_emails_data = []
    query_date = (datetime.now() - timedelta(days=days)).strftime('%Y/%m/%d')
    query = f'after:{query_date} in:sent'

    try:
        response = service.users().messages().list(userId='me', q=query, maxResults=100).execute()
        messages = response.get('messages', [])
        
        for message_info in messages:
            msg_id = message_info['id']
            msg = service.users().messages().get(userId='me', id=msg_id, format='metadata', metadataHeaders=['Subject', 'To', 'Date']).execute()
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            recipients_str = next((h['value'] for h in headers if h['name'].lower() == 'to'), '')
            recipients = [email.strip() for email in re.findall(r'[\w\.-]+@[\w\.-]+', recipients_str)]
            sent_date_unix = int(msg.get('internalDate', '0')) / 1000
            sent_date = datetime.fromtimestamp(sent_date_unix).isoformat()
            sent_emails_data.append({'subject': subject, 'recipients': recipients, 'sent_time': sent_date})
        
        print(f"{TermColors.STATUS_INFO}Fetched {len(sent_emails_data)} sent emails from the last {days} days.{TermColors.RESET}")
    except HttpError as error:
        print(f"{TermColors.STATUS_ERROR}An error occurred fetching sent emails: {error}{TermColors.RESET}")
    return sent_emails_data

def read_emails():
    """Read emails from recent_emails.txt and return as a list of dictionaries"""
    recent_emails_file_path = os.path.join(SCRIPT_DIR, RECENT_EMAILS_FILE)
    try:
        with open(recent_emails_file_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"{TermColors.YELLOW}No {recent_emails_file_path} file found. Creating empty file.{TermColors.RESET}")
        with open(recent_emails_file_path, "w", encoding="utf-8") as f:
            f.write("")
        return []
    
    emails = []
    current_email = {}
    current_body_lines = []
    
    for line in lines:
        line = line.rstrip()
        if line.startswith("Subject: "):
            if current_email:
                current_email["body"] = "\n".join(l for l in current_body_lines if l.strip())
                emails.append(current_email)
                current_body_lines = []
            current_email = {"subject": line[9:], "from": "unknown"}
        elif line.startswith("From: "): current_email["from"] = line[6:]
        elif line.startswith("Received: "): current_email["received"] = line[10:]
        elif line.startswith("Body: "): current_body_lines = [line[6:]]
        elif line.startswith("-" * 50): continue
        else:
            if current_body_lines is not None: current_body_lines.append(line)
            
    if current_email:
        current_email["body"] = "\n".join(l for l in current_body_lines if l.strip())
        emails.append(current_email)
    return emails

def analyze_email_importance(client, email):
    """Analyze a single email's importance using OpenAI API"""
    body = email['body'].strip()
    prompt = f"""
    You are an email importance analyzer for a busy professional.
    Your task is to determine which emails CRITICALLY NEED a response and which can be ignored.
    BE EXTREMELY SELECTIVE - only flag emails as needing a response if they are:
    1. From real people (not automated systems)
    2. Personalized (not mass marketing)
    3. Require specific action or input from the recipient
    4. Have clear business value, substantial opportunity, or time-sensitive importance
    Automated notifications, newsletters, marketing emails should ALWAYS be marked as not needing response.
    Email to analyze:
    Subject: {email['subject']}
    From: {email['from']}
    Received: {email.get('received', 'unknown')}
    Body:
    {body[:4000]}
    Classify importance:
    - "high" importance: Personalized communications with clear value, time-sensitive matters that MUST be addressed
    - "medium" importance: Potentially useful but less critical communications
    - "low" importance: Mass marketing, newsletters, automated notifications, spam, etc.
    BE STRICT about "needs_response" - only mark TRUE if it absolutely requires personal attention and response.
    Respond with a JSON object that MUST include:
    {{
        "importance": "high" | "medium" | "low",
        "reason": <brief explanation for the importance rating>,
        "needs_response": <boolean - true ONLY if email absolutely requires a response>,
        "time_sensitive": <boolean - true if matter is time-sensitive>,
        "topics": [<list of 1-3 key topics in the email>]
    }}"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are an executive assistant who helps busy professionals prioritize their emails. You are EXTREMELY selective about what emails truly need a response. Your goal is to minimize noise and only surface emails that absolutely must be dealt with."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if content:
            analysis = json.loads(content)
            print(f"\n{TermColors.STATUS_INFO}Analyzing: {email['subject']}{TermColors.RESET}")
            print(f"Analysis result: {json.dumps(analysis, indent=2)}")
            return EmailImportance(**analysis)
        else:
            print(f"{TermColors.YELLOW}Empty response for email: {email['subject']}{TermColors.RESET}")
            return None
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error analyzing email: {e}{TermColors.RESET}")
        print(f"Failed email subject: {email['subject']}")
        return None

def run_triage(gmail_service, openai_client): # Renamed and added parameters
    """Main function to identify important emails, callable from other scripts."""
    scan_hours = 24 # Default
    unit_prompt_text = "Look back for new emails in (d)ays or (h)ours? [h, default 24h]: "
    while True:
        unit_choice = input(unit_prompt_text).lower().strip()
        if not unit_choice: 
            unit_choice = 'h'
            print(f"Defaulting to {scan_hours} hours.")
            break
        if unit_choice in ['d', 'h']:
            break
        print("Invalid input. Please enter 'd' for days or 'h' for hours (or leave blank for default 24 hours).")

    # Get timeframe value
    scan_value = scan_hours # Start with default
    if unit_choice != 'h' or input(f"How many hours back should I look? [{scan_hours}]: ").strip(): # If not default hours, or if user provides input
        prompt_value_text = f"How many {'days' if unit_choice == 'd' else 'hours'} back should I look? "
        while True:
            try:
                value_str = input(prompt_value_text)
                if not value_str and unit_choice == 'h': # User hit enter for default hours
                    break # Keep default scan_hours
                value = int(value_str)
                if value > 0:
                    scan_value = value
                    if unit_choice == 'd':
                        scan_value = value * 24
                    break
                else:
                    print("Please enter a positive number.")
            except ValueError:
                print("Invalid number. Please enter a whole number.")
    scan_hours = scan_value # Update scan_hours with the chosen value

    # Ask about including read emails
    include_read = False
    read_prompt = "Include read emails in the triage? (y/n) [n]: "
    read_choice = input(read_prompt).lower().strip()
    if read_choice == 'y':
        include_read = True

    # Construct the query based on user input
    email_query_parts = ['in:INBOX', '-in:spam', '-in:trash'] # Changed to in:INBOX and added exclusions
    if not include_read:
        email_query_parts.append('is:unread') # Add is:unread only if needed
    email_query = ' '.join(email_query_parts)

    print(f"{TermColors.STATUS_INFO}Fetching emails from the last {scan_hours} hours with query '{email_query}'...{TermColors.RESET}")
    # Use passed-in gmail_service and the constructed query
    get_emails(service=gmail_service, query=email_query, hours=scan_hours)
    
    # client = OpenAI() # Use passed-in openai_client
    # Adjust sent email lookback based on incoming scan hours
    sent_email_lookback_days = max(1, scan_hours // 24) # Ensure at least 1 day

    print(f"{TermColors.STATUS_INFO}Checking sent folder for previous responses (last {sent_email_lookback_days} days)...{TermColors.RESET}")
    # Use passed-in gmail_service and the adjusted lookback days
    sent_emails = get_sent_emails(service=gmail_service, days=sent_email_lookback_days)
    
    # client = OpenAI() # Use passed-in openai_client
    emails = read_emails()
    
    # Collect ALL analyzed emails, not just those needing response
    all_analyzed_emails = []
    
    for email in emails:
        already_responded = is_previously_responded(email, sent_emails)
        analysis = analyze_email_importance(openai_client, email) # Use passed-in openai_client
        
        if analysis: # Only include if AI analysis was successful
             email_data = {
                "subject": email["subject"], "from": email["from"],
                "received": email.get("received", datetime.now().isoformat()),
                "body": email["body"][:1000] + ("..." if len(email["body"]) > 1000 else ""),
                "analysis": analysis.model_dump(),
                "already_responded": already_responded
            }
             all_analyzed_emails.append(email_data)
    
    # Save ALL analyzed emails to JSON (optional, but useful for debugging/future features)
    output_data = {"last_updated": datetime.now().isoformat(), "analyzed_emails": all_analyzed_emails}
    # We'll keep NEEDS_RESPONSE_JSON for compatibility with email_draft_reply.py for now,
    # but it will only contain emails flagged as needing response.
    # Let's create a new JSON for ALL analyzed emails.
    ALL_ANALYZED_JSON = os.path.join(SCRIPT_DIR, "all_analyzed_emails.json")
    with open(ALL_ANALYZED_JSON, "w", encoding="utf-8") as f: json.dump(output_data, f, indent=2)
    print(f"\n{TermColors.STATUS_INFO}All analyzed emails saved to: {os.path.basename(ALL_ANALYZED_JSON)} (in the project directory){TermColors.RESET}")


    # Filter for emails needing response for the original JSON and report summary
    needs_response_emails = [
        email for email in all_analyzed_emails 
        if email["analysis"]["needs_response"] and not email["already_responded"] # Only new emails needing response
    ]
    
    # Update NEEDS_RESPONSE_JSON for compatibility with email_draft_reply.py
    needs_response_output_data = {"last_updated": datetime.now().isoformat(), "needs_response_emails": needs_response_emails}
    with open(NEEDS_RESPONSE_JSON, "w", encoding="utf-8") as f: json.dump(needs_response_output_data, f, indent=2)
    print(f"{TermColors.STATUS_INFO}Emails requiring response (for drafting) saved to: {os.path.basename(NEEDS_RESPONSE_JSON)} (in the project directory){TermColors.RESET}")


    print(f"\n{TermColors.SUMMARY_KEY}Processed {len(emails)} emails from the last {scan_hours} hours.{TermColors.RESET}") # Use scan_hours
    print(f"{TermColors.SUMMARY_KEY}Emails requiring response (new):{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(needs_response_emails)}{TermColors.RESET}")
    already_responded_count = sum(1 for email in all_analyzed_emails if email["already_responded"]) # Count from all analyzed
    print(f"{TermColors.SUMMARY_KEY}Previously responded to:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{already_responded_count}{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Total emails analyzed:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(all_analyzed_emails)}{TermColors.RESET}") # Report total analyzed
    
    print(f"\n{TermColors.STATUS_INFO}Detailed results saved to: {os.path.basename(NEEDS_RESPONSE_JSON)} and {os.path.basename(ALL_ANALYZED_JSON)} (in the project directory){TermColors.RESET}")
    
    # Generate Markdown Report for ALL analyzed emails
    with open(NEEDS_RESPONSE_REPORT, "w", encoding="utf-8") as f:
        f.write("# Email Triage Report\n\n") # More general title
        f.write(f"Generated on: {datetime.now().isoformat()}\n\n")
        f.write(f"**Total Emails Analyzed:** {len(all_analyzed_emails)}\n\n")
        f.write(f"**Emails Requiring New Response:** {len(needs_response_emails)}\n\n")
        f.write(f"**Previously Responded To:** {already_responded_count}\n\n")
        f.write("---\n\n")
        
        if all_analyzed_emails:
            # Sort all analyzed emails for the report
            sorted_emails = sorted(
                all_analyzed_emails, 
                key=lambda x: (not x['analysis']['time_sensitive'], x["already_responded"], 
                               0 if x['analysis']['importance'] == 'high' else 1 if x['analysis']['importance'] == 'medium' else 2)
            )
            
            f.write("## Analyzed Emails\n\n")

            for email in sorted_emails:
                f.write(f"### {email['subject']}\n\n")
                f.write(f"**From:** {email['from']}\n\n")
                f.write(f"**Received:** {email['received']}\n\n")
                
                # Determine and write status
                status_text = "⚪️ No Response Needed" # Default
                if email["already_responded"]:
                    status_text = "✅ ALREADY RESPONDED"
                elif email["analysis"]["time_sensitive"]:
                    status_text = "🚨 URGENT"
                elif email["analysis"]["needs_response"]:
                    status_text = "🟠 Needs Response"
                
                f.write(f"**STATUS:** {status_text}\n\n")

                f.write(f"**Importance:** {email['analysis']['importance'].upper()}\n\n")
                f.write(f"**Time Sensitive:** {'YES' if email['analysis']['time_sensitive'] else 'No'}\n\n")
                f.write(f"**Topics:** {', '.join(email['analysis']['topics'])}\n\n")
                f.write(f"**Reason:** {email['analysis']['reason']}\n\n")
                f.write(f"**Preview:**\n")
                f.write(f"> {email['body'][:300]}...\n\n")
                f.write("---\n\n") # Markdown horizontal rule
        else:
            f.write("No emails were analyzed.\n\n")
    
    # Terminal output remains the same for immediate feedback
    if all_analyzed_emails: # Print summary to terminal from all analyzed
        print(f"\n{TermColors.SUMMARY_HEADER}ANALYZED EMAILS SUMMARY:{TermColors.RESET}\n" + "="*50)
        
        # Group by status for terminal summary
        status_counts = {"🚨 URGENT": 0, "✅ ALREADY RESPONDED": 0, "🟠 Needs Response": 0, "⚪️ No Response Needed": 0}
        for email in all_analyzed_emails:
             if email["already_responded"]: # Prioritize already responded
                 status_counts["✅ ALREADY RESPONDED"] += 1
             elif email["analysis"]["time_sensitive"]:
                 status_counts["🚨 URGENT"] += 1
             elif email["analysis"]["needs_response"]:
                 status_counts["🟠 Needs Response"] += 1
             else:
                 status_counts["⚪️ No Response Needed"] += 1

        print(f"{TermColors.SUMMARY_KEY}Total Emails Analyzed:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(all_analyzed_emails)}{TermColors.RESET}")
        print(f"{TermColors.RED}🚨 URGENT:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{status_counts['🚨 URGENT']}{TermColors.RESET}")
        print(f"{TermColors.GREEN}✅ ALREADY RESPONDED:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{status_counts['✅ ALREADY RESPONDED']}{TermColors.RESET}")
        print(f"{TermColors.YELLOW}🟠 Needs Response:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{status_counts['🟠 Needs Response']}{TermColors.RESET}")
        print(f"{TermColors.CYAN}⚪️ No Response Needed:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{status_counts['⚪️ No Response Needed']}{TermColors.RESET}") # Using CYAN for white circle visibility
        
        print("\n" + "="*50) # Separator for terminal detail list

        # Print terminal detail list (similar to before, but from all_analyzed_emails)
        sorted_emails_terminal = sorted(
            all_analyzed_emails, 
            key=lambda x: (not x['analysis']['time_sensitive'], x["already_responded"], 
                           0 if x['analysis']['importance'] == 'high' else 1 if x['analysis']['importance'] == 'medium' else 2)
        )
        for email in sorted_emails_terminal:
            print(f"\n{TermColors.CANDIDATE_INFO}Subject: {email['subject']}{TermColors.RESET}")
            print(f"{TermColors.CANDIDATE_INFO}From: {email['from']}{TermColors.RESET}")
            
            # Determine and print status for terminal
            status_text_terminal = f"{TermColors.CYAN}⚪️ No Response Needed{TermColors.RESET}" # Default
            if email["already_responded"]: # Prioritize already responded
                status_text_terminal = f"{TermColors.GREEN}✅ ALREADY RESPONDED{TermColors.RESET}"
            elif email["analysis"]["time_sensitive"]:
                status_text_terminal = f"{TermColors.RED}🚨 URGENT{TermColors.RESET}"
            elif email["analysis"]["needs_response"]:
                status_text_terminal = f"{TermColors.YELLOW}🟠 Needs Response{TermColors.RESET}"
            
            print(f"STATUS: {status_text_terminal}")

            print(f"Importance: {email['analysis']['importance'].upper()}")
            print(f"Time Sensitive: {'YES' if email['analysis']['time_sensitive'] else 'No'}")
            print(f"Topics: {', '.join(email['analysis']['topics'])}")
            print(f"Reason: {email['analysis']['reason']}\n" + "-" * 50)
    else: print(f"\n{TermColors.YELLOW}No emails were analyzed.{TermColors.RESET}")
    
    print(f"\n{TermColors.STATUS_INFO}Full report available in {os.path.basename(NEEDS_RESPONSE_REPORT)} (in the project directory){TermColors.RESET}")

if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email Triage Standalone...{TermColors.RESET}")
    # Initialize services for standalone run
    standalone_gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES)
    if not standalone_gmail_service:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize Gmail service for standalone run. Exiting.{TermColors.RESET}")
        sys.exit(1)
    
    try:
        standalone_openai_client = OpenAI()
        # You might want to add a simple test call here if needed, e.g., client.models.list()
        print(f"{TermColors.STATUS_SUCCESS}OpenAI client initialized for standalone run.{TermColors.RESET}")
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize OpenAI client for standalone run: {e}{TermColors.RESET}")
        sys.exit(1)

    run_triage(standalone_gmail_service, standalone_openai_client)
