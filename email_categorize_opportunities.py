import os
from dotenv import load_dotenv
import json
from datetime import datetime, timedelta
from openai import OpenAI
from pydantic import BaseModel
from typing import Optional, Literal
import base64
# from email.mime.text import MIMEText # No longer needed here as send_email is in utils
import re 

# Import utilities
from email_utils import get_gmail_service, TermColors # send_email is not directly used by this script's main flow

from googleapiclient.errors import HttpError # Keep for exception handling

# Load environment variables
load_dotenv(override=True)

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.send'] # Readonly for fetching, send if it were to use the send_email util directly

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# File paths - make them SCRIPT_DIR relative
EMAILS_FILE = os.path.join(SCRIPT_DIR, "emails.txt")
CATEGORIZED_EMAILS_JSON = os.path.join(SCRIPT_DIR, "categorized_emails.json")
OPPORTUNITY_REPORT = os.path.join(SCRIPT_DIR, "opportunity_report.txt")


class EmailAnalysis(BaseModel):
    category: Literal["sponsorship", "business_inquiry", "other"]
    confidence: float
    reason: str
    company_name: Optional[str] = None
    topic: Optional[str] = None

# get_gmail_service and send_email functions are now in email_utils.py
import sys # For sys.exit in standalone mode

def get_emails(service, hours=72): # Added service parameter
    """
    Fetches emails from Gmail from the last {hours} hours and saves to EMAILS_FILE.
    """
    # service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES) # Service is now passed in
    if not service:
        print(f"{TermColors.STATUS_ERROR}Failed to get Gmail service in get_emails (service not provided).{TermColors.RESET}")
        return []

    emails_data = []
    query_date = (datetime.now() - timedelta(hours=hours)).strftime('%Y/%m/%d')
    query = f'after:{query_date} category:primary' 

    try:
        response = service.users().messages().list(userId='me', q=query, maxResults=50).execute() 
        messages = response.get('messages', [])
        
        with open(EMAILS_FILE, "w", encoding="utf-8") as f_out: 
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
                
        print(f"{TermColors.STATUS_INFO}Fetched {len(emails_data)} emails from the last {hours} hours into {EMAILS_FILE}.{TermColors.RESET}")
        if not emails_data:
            with open(EMAILS_FILE, 'w', encoding='utf-8') as f_empty: f_empty.write("")
            print(f"{TermColors.YELLOW}{EMAILS_FILE} is empty as no new emails were found.{TermColors.RESET}")

    except HttpError as error:
        print(f"{TermColors.STATUS_ERROR}An error occurred fetching emails: {error}{TermColors.RESET}")
        with open(EMAILS_FILE, 'w', encoding='utf-8') as f_err: f_err.write("")
        print(f"{TermColors.YELLOW}{EMAILS_FILE} is empty due to an error.{TermColors.RESET}")
    return emails_data

def read_emails():
    """Read emails from emails.txt and return as a list of dictionaries"""
    try:
        with open(EMAILS_FILE, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except FileNotFoundError:
        print(f"{TermColors.YELLOW}No {EMAILS_FILE} file found. Creating empty file.{TermColors.RESET}")
        with open(EMAILS_FILE, "w", encoding="utf-8") as f_create:
            f_create.write("")
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

def analyze_email(client, email):
    """Analyze a single email using OpenAI API with Structured Outputs"""
    body = email['body'].strip()
    prompt = f"""
    You are an email categorizer for a professional. Your task is to categorize incoming emails
    and identify important information.
    Email to analyze:
    Subject: {email['subject']}
    From: {email['from']}
    Body:
    {body[:4000]}
    Categorize this email into one of the following:
    1. "sponsorship" - Companies wanting to sponsor content or services
    2. "business_inquiry" - Business-related emails, partnership offers, marketing opportunities
    3. "other" - Everything else
    If it's a sponsorship or business inquiry, extract the company name and the main topic/product.
    Respond with a JSON object that MUST include:
    {{
        "category": "sponsorship" | "business_inquiry" | "other",
        "confidence": <number between 0 and 1>,
        "reason": <explanation string>,
        "company_name": <extracted company name or null>,
        "topic": <main topic/product or null>
    }}"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[
                {"role": "system", "content": "You are a precise email categorizer. Your goal is to accurately categorize emails and extract relevant business information."},
                {"role": "user", "content": prompt}
            ],
            response_format={"type": "json_object"}
        )
        content = response.choices[0].message.content
        if content:
            analysis = json.loads(content)
            print(f"\n{TermColors.STATUS_INFO}Analyzing: {email['subject']}{TermColors.RESET}")
            print(f"Analysis result: {json.dumps(analysis, indent=2)}")
            return EmailAnalysis(**analysis)
        else:
            print(f"{TermColors.YELLOW}Empty response for email: {email['subject']}{TermColors.RESET}")
            return None
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error analyzing email: {e}{TermColors.RESET}")
        print(f"Failed email subject: {email['subject']}")
        return None

def run_opportunity_categorization_step1(gmail_service, openai_client): # Renamed and added parameters
    """Fetches and performs initial categorization of emails."""
    print(f"{TermColors.STATUS_INFO}Fetching new emails for opportunity categorization...{TermColors.RESET}")
    get_emails(service=gmail_service, hours=72) # Pass gmail_service
    
    # client = OpenAI() # Use passed-in openai_client
    emails = read_emails()
    
    sponsorship_emails, business_emails, other_emails = [], [], []
    
    for email in emails:
        analysis = analyze_email(openai_client, email) # Pass openai_client
        if analysis:
            email_data = {
                "subject": email["subject"], "from": email["from"],
                "received": email.get("received", datetime.now().isoformat()),
                "body": email["body"], "analysis": analysis.model_dump()
            }
            if analysis.category == "sponsorship": sponsorship_emails.append(email_data)
            elif analysis.category == "business_inquiry": business_emails.append(email_data)
            else: other_emails.append(email_data)
    
    output_data = {
        "last_updated": datetime.now().isoformat(),
        "sponsorship_emails": sponsorship_emails,
        "business_emails": business_emails,
        "other_emails": other_emails
    }
    with open(CATEGORIZED_EMAILS_JSON, "w", encoding="utf-8") as f: json.dump(output_data, f, indent=2)
    
    print(f"\n{TermColors.SUMMARY_KEY}Processed {len(emails)} emails{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Sponsorship requests:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(sponsorship_emails)}{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Business inquiries:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(business_emails)}{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Other emails:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(other_emails)}{TermColors.RESET}")
    print(f"\n{TermColors.STATUS_INFO}Detailed results saved to: {CATEGORIZED_EMAILS_JSON}{TermColors.RESET}")
    
    print(f"\n{TermColors.SUMMARY_HEADER}High Confidence Business/Sponsorship Emails (>0.8):{TermColors.RESET}")
    for email in sponsorship_emails + business_emails:
        if email["analysis"]["confidence"] > 0.8:
            print(f"\n{TermColors.CANDIDATE_INFO}Category: {email['analysis']['category']}{TermColors.RESET}")
            print(f"From: {email['from']}")
            print(f"Subject: {email['subject']}")
            if email["analysis"]["company_name"]: print(f"Company: {email['analysis']['company_name']}")
            if email["analysis"]["topic"]: print(f"Topic: {email['analysis']['topic']}")
            print(f"Reason: {email['analysis']['reason']}\n" + "-" * 50)
    return True # Indicate success or that the process ran

def run_opportunity_categorization_step2(openai_client, categorized_emails_path=CATEGORIZED_EMAILS_JSON): # Added openai_client
    """Generate a structured report highlighting valuable business opportunities"""
    try:
        with open(categorized_emails_path, "r", encoding="utf-8") as f: data = json.load(f)
        business_emails = data.get("business_emails", [])
        sponsorship_emails = data.get("sponsorship_emails", [])
        all_relevant_emails = business_emails + sponsorship_emails
        
        if not all_relevant_emails:
            print(f"{TermColors.YELLOW}No business or sponsorship emails found to analyze for the report.{TermColors.RESET}")
            return
            
        # client = OpenAI() # Use passed-in openai_client
        print(f"\n{TermColors.STATUS_INFO}Analyzing business and sponsorship emails for quality opportunities report...{TermColors.RESET}")
        
        prompt = f"""
        You are an executive assistant tasked with filtering through business and sponsorship emails to identify the highest quality opportunities.
        Please analyze these {len(all_relevant_emails)} business and sponsorship emails and create a structured report that:
        1. Categorizes them as "High Value" or "Mass Marketing/Generic"
        2. Ranks the high-value opportunities in order of priority
        3. Provides brief reasoning for your assessments
        Here are the emails to analyze:
        {json.dumps([{
            "category": email["analysis"]["category"], "from": email["from"], "subject": email["subject"],
            "company": email["analysis"]["company_name"], "topic": email["analysis"]["topic"],
            "confidence": email["analysis"]["confidence"],
            "snippet": email["body"][:500] + "..." if len(email["body"]) > 500 else email["body"]
        } for email in all_relevant_emails], indent=2)}
        Consider the following criteria to evaluate opportunities:
        1. Personalization (specifically addressed to the user, mentions specific work)
        2. Authenticity (not mass-marketing, personal tone, unique request)
        3. Relevance (aligns with user's work, interesting topic, reasonable offer)
        4. Reputation (known company, established person, verifiable identity)
        5. Specificity (clear request/opportunity with details, not vague)
        Format your report with clear sections and prioritize opportunities that seem unique, personalized, and valuable.
        """
        response = client.chat.completions.create(
            model="gpt-4",
            messages=[
                {"role": "system", "content": "You are an executive assistant who helps identify high-quality opportunities from business emails. You excel at distinguishing personalized offers from mass marketing campaigns."},
                {"role": "user", "content": prompt}
            ]
        )
        report_content = response.choices[0].message.content
        
        print("\n" + "="*50 + f"\n{TermColors.SUMMARY_HEADER}BUSINESS AND SPONSORSHIP OPPORTUNITY REPORT{TermColors.RESET}\n" + "="*50 + "\n")
        print(report_content)
        
        with open(OPPORTUNITY_REPORT, "w", encoding="utf-8") as f:
            f.write("BUSINESS AND SPONSORSHIP OPPORTUNITY REPORT\n" + "="*50 + "\n\n" + report_content)
        print(f"\n{TermColors.STATUS_SUCCESS}Report saved to {OPPORTUNITY_REPORT}{TermColors.RESET}")
            
    except FileNotFoundError:
        print(f"{TermColors.STATUS_ERROR}Error: File {categorized_emails_path} not found. Please run sort_emails() first.{TermColors.RESET}")
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error generating opportunity report: {e}{TermColors.RESET}")

def run_opportunity_categorization(gmail_service, openai_client):
    """Main orchestrator for opportunity categorization."""
    print(f"{TermColors.BOLD}Starting Email Opportunity Categorization...{TermColors.RESET}")
    step1_success = run_opportunity_categorization_step1(gmail_service, openai_client)
    if step1_success:
        run_opportunity_categorization_step2(openai_client)
    else:
        print(f"{TermColors.YELLOW}Step 1 of opportunity categorization did not complete successfully. Skipping report generation.{TermColors.RESET}")
    print(f"{TermColors.BOLD}Email Opportunity Categorization finished.{TermColors.RESET}")


if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email Opportunity Categorization Standalone...{TermColors.RESET}")
    standalone_gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES)
    if not standalone_gmail_service:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize Gmail service for standalone run. Exiting.{TermColors.RESET}")
        sys.exit(1)
    
    try:
        standalone_openai_client = OpenAI()
        print(f"{TermColors.STATUS_SUCCESS}OpenAI client initialized for standalone run.{TermColors.RESET}")
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize OpenAI client for standalone run: {e}{TermColors.RESET}")
        sys.exit(1)

    run_opportunity_categorization(standalone_gmail_service, standalone_openai_client)
