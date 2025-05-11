import os
import json
import re
from openai import OpenAI
from dotenv import load_dotenv
from datetime import datetime # Ensure datetime is imported at the top

# Import utilities
from email_utils import send_email, get_gmail_service, TermColors 
import sys # For sys.exit in standalone mode

# Load environment variables
load_dotenv(override=True)

# --- Configuration ---
SCOPES = ['https://www.googleapis.com/auth/gmail.send', 'https://www.googleapis.com/auth/gmail.readonly'] # Readonly might be useful if script evolves

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# File paths - make them SCRIPT_DIR relative
NEEDS_RESPONSE_REPORT_FILE = os.path.join(SCRIPT_DIR, "needs_response_report.md") # Corrected to .md
RESPONSE_HISTORY_FILE = os.path.join(SCRIPT_DIR, "response_history.json")

def extract_emails_from_report(report_path=NEEDS_RESPONSE_REPORT_FILE): # Use updated constant
    """Extract emails from the needs_response_report.txt file"""
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            content = f.read()
        
        email_sections = content.split("-" * 50)
        emails = []
        for section in email_sections:
            if not section.strip():
                continue
            
            subject_match = re.search(r"Subject: (.+?)$", section, re.MULTILINE)
            from_match = re.search(r"From: (.+?)$", section, re.MULTILINE)
            email_address_match = re.search(r"<(.+?)>", section) # This might not always be present or correct
            preview_match = re.search(r"Preview: (.+?)$", section, re.MULTILINE | re.DOTALL)
            already_responded = "ALREADY RESPONDED" in section
            
            if subject_match and from_match:
                # Attempt to extract email from "From:" field if not found directly
                extracted_email = None
                if email_address_match:
                    extracted_email = email_address_match.group(1).strip()
                else: # Try to get it from the From field if it's just an email
                    from_content = from_match.group(1).strip()
                    email_pattern = r'[\w\.-]+@[\w\.-]+'
                    found_emails_in_from = re.findall(email_pattern, from_content)
                    if found_emails_in_from:
                        extracted_email = found_emails_in_from[0]


                email_data = {
                    "subject": subject_match.group(1).strip(),
                    "from": from_match.group(1).strip(),
                    "email_address": extracted_email,
                    "preview": preview_match.group(1).strip() if preview_match else "No preview available",
                    "already_responded": already_responded
                }
                emails.append(email_data)
        return emails
    
    except FileNotFoundError:
        print(f"{TermColors.STATUS_ERROR}Error: File {os.path.basename(report_path)} (expected in project directory) not found.{TermColors.RESET}")
        return []
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error extracting emails from report: {e}{TermColors.RESET}")
        return []

def save_response_history(new_response):
    """Save a record of an email we've responded to"""
    try:
        try:
            with open(RESPONSE_HISTORY_FILE, "r", encoding="utf-8") as f:
                history = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            history = {"responded_emails": []}
        
        history["responded_emails"].append({
            "subject": new_response["subject"],
            "from": new_response["from"],
            "responded_at": new_response["responded_at"] # Ensure this is passed correctly
        })
        
        with open(RESPONSE_HISTORY_FILE, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2)
        return True
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error saving response history: {e}{TermColors.RESET}")
        return False

def generate_response(client, email_data, edit_instructions=None):
    """Generate a response email using OpenAI"""
    if edit_instructions:
        prompt = f"""
        Rewrite the email response based on these instructions:
        Original Email:
        Subject: {email_data['subject']}
        From: {email_data['from']}
        Preview: {email_data['preview'][:500]}
        Instructions for rewriting: {edit_instructions}
        Your response should maintain this format:
        Subject: Re: [Original Subject]
        
        [Email body]
        
        Best regards,
        Kris
        """
    else:
        prompt = f"""
        Create a concise and helpful email response for the following inquiry:
        Subject: {email_data['subject']}
        From: {email_data['from']}
        Preview: {email_data['preview'][:1000]}
        Requirements:
        1. Keep the response friendly but brief and to the point
        2. Address any specific questions or requests in the email
        3. Be professional and helpful
        4. Always end with "Best regards,\nKris"
        5. Include appropriate subject line with "Re: " prefix
        6. Don't be overly verbose - keep it under 150 words
        7. Don't apologize for delay unless clearly necessary
        Your response should be formatted as:
        Subject: Re: [Original Subject]
        
        [Email body]
        
        Best regards,
        Kris
        """
    try:
        response = client.chat.completions.create(
            model="gpt-4.1", 
            messages=[
                {"role": "system", "content": "You are a professional, concise email responder who crafts helpful, direct responses to business inquiries."},
                {"role": "user", "content": prompt}
            ]
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error generating response: {e}{TermColors.RESET}")
        return None

def run_reply_drafting(gmail_service, openai_client): # Renamed and added parameters
    """Process and send responses to important emails"""
    # client = OpenAI() # Use passed-in openai_client
    # gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES) # Use passed-in gmail_service

    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available. Cannot send responses. Exiting.{TermColors.RESET}")
        return
    
    if not openai_client:
        print(f"{TermColors.STATUS_ERROR}OpenAI client not available. Cannot generate responses. Exiting.{TermColors.RESET}")
        return
        
    emails = extract_emails_from_report() # Uses updated constant by default
    
    if not emails:
        print(f"{TermColors.YELLOW}No emails requiring response found in the report (needs_response_report.txt).{TermColors.RESET}")
        return
    
    new_emails = [email for email in emails if not email['already_responded']]
    print(f"Found {len(emails)} emails requiring response ({len(new_emails)} new, {len(emails) - len(new_emails)} already responded to).\n")
    
    for i, email_data in enumerate(emails, 1):
        print("=" * 50)
        print(f"Email {i}/{len(emails)}")
        print(f"{TermColors.CANDIDATE_INFO}Subject: {email_data['subject']}{TermColors.RESET}")
        print(f"{TermColors.CANDIDATE_INFO}From: {email_data['from']}{TermColors.RESET}")
        
        if email_data['already_responded']:
            print(f"{TermColors.GREEN}STATUS: ✅ ALREADY RESPONDED{TermColors.RESET}")
            choice = input("\nThis email has already been responded to. Process anyway? (y/n): ").lower()
            if choice != 'y':
                print("Skipping to next email...\n")
                continue
        
        print("-" * 50)
        draft_response = generate_response(openai_client, email_data) # Use passed-in openai_client
        
        if not draft_response:
            print("Failed to generate a response. Skipping to next email.")
            continue
        
        while True:
            response_lines = draft_response.strip().split('\n')
            subject_line = response_lines[0].replace('Subject:', '').strip()
            body = '\n'.join(response_lines[1:]).strip()
            
            print(f"\n{TermColors.SUMMARY_HEADER}DRAFT RESPONSE:{TermColors.RESET}")
            print("-" * 50)
            print(f"To: {email_data['email_address']}")
            print(f"Subject: {subject_line}")
            print("-" * 50)
            print(body)
            print("-" * 50)
            
            choice = input(f"\n{TermColors.YELLOW}Send this response? (y/n/edit/skip): {TermColors.RESET}").lower()
            
            if choice == 'y':
                if email_data['email_address']:
                    print(f"{TermColors.STATUS_INFO}Sending email to {email_data['email_address']}...{TermColors.RESET}")
                    # Pass the service object to send_email
                    result = send_email(gmail_service, subject_line, body, email_data['email_address'])
                    if result:
                        print(f"{TermColors.STATUS_SUCCESS}Email sent successfully!{TermColors.RESET}")
                        save_response_history({
                            "subject": email_data['subject'],
                            "from": email_data['from'],
                            "responded_at": datetime.now().isoformat() # Use datetime directly
                        })
                    else:
                        print(f"{TermColors.STATUS_ERROR}Failed to send email.{TermColors.RESET}")
                else:
                    print(f"{TermColors.STATUS_ERROR}Error: No email address found for recipient.{TermColors.RESET}")
                break
            elif choice == 'n' or choice == 'skip':
                print("Skipping this email.")
                break
            elif choice == 'edit':
                print("\nDescribe how you want the email rewritten:")
                edit_instructions = input("> ")
                print(f"\n{TermColors.STATUS_INFO}Generating new response based on your instructions...{TermColors.RESET}")
                new_draft = generate_response(openai_client, email_data, edit_instructions) # Use passed-in openai_client
                if new_draft:
                    draft_response = new_draft
                else:
                    print(f"{TermColors.STATUS_ERROR}Failed to generate edited response. Keeping previous draft.{TermColors.RESET}")
            else:
                print("Invalid choice. Please enter 'y', 'n', 'edit', or 'skip'.")
        print() 
    
    print(f"\n{TermColors.BOLD}All emails processed.{TermColors.RESET}")

if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email Reply Drafting Standalone...{TermColors.RESET}")
    # Initialize services for standalone run
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

    run_reply_drafting(standalone_gmail_service, standalone_openai_client)
