import os
import json
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import base64
import re
import sys

# Import utilities
from email_utils import get_gmail_service, TermColors

# Removed Google specific imports as they are in email_utils
# from google_auth_oauthlib.flow import InstalledAppFlow
# from google.auth.transport.requests import Request
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
from googleapiclient.errors import HttpError # Keep for local error handling if any

from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# TermColors class is now imported from email_utils

# --- Configuration ---
# Gmail API Scopes - Readonly is sufficient for planning deletion
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly']
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json") # Ensure this is present

# Report file
DELETION_PLAN_REPORT_FILE = os.path.join(SCRIPT_DIR, "deletion_plan_report.txt")
DELETION_CANDIDATES_JSON_FILE = os.path.join(SCRIPT_DIR, "deletion_candidates.json")


# --- Pydantic Models ---
class EmailDeletionSuggestion(BaseModel):
    email_id: str
    subject: str
    sender: str
    received_date: str
    suggestion: Literal["strong_candidate", "possible_candidate", "keep"]
    reason_category: Literal[
        "age", "sender_rule", "subject_rule",
        "ai_promotional", "ai_social", "ai_outdated_alert", "ai_newsletter",
        "ai_general_clutter", "ai_transactional", "ai_personal", "ai_work_related",
        "ai_other_deletable", "ai_unsure", "manual_keep"
    ]
    reason_detail: str
    ai_confidence: Optional[float] = None
    list_unsubscribe_mailto: Optional[str] = None
    list_unsubscribe_http: Optional[str] = None

class EmailDetails(BaseModel):
    id: str
    thread_id: str
    subject: str
    sender: str
    received_date: datetime
    snippet: str
    body_plain: Optional[str] = None
    list_unsubscribe_mailto: Optional[str] = None
    list_unsubscribe_http: Optional[str] = None

# get_gmail_service function is now imported from email_utils

# --- Email Fetching ---
def fetch_emails_for_deletion_planning(service, days_to_scan=180, max_emails=200):
    fetched_emails: List[EmailDetails] = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_scan)
    query = f'before:{cutoff_date.strftime("%Y/%m/%d")}'
    
    print(f"{TermColors.STATUS_INFO}Fetching emails with query: {query} (up to {max_emails} emails){TermColors.RESET}")

    try:
        response = service.users().messages().list(userId='me', q=query, maxResults=max_emails).execute()
        messages_info = response.get('messages', [])
        
        if not messages_info:
            print(f"{TermColors.YELLOW}No emails found matching the criteria.{TermColors.RESET}")
            return fetched_emails

        print(f"{TermColors.STATUS_INFO}Found {len(messages_info)} email messages. Fetching details...{TermColors.RESET}")
        
        for i, msg_info in enumerate(messages_info):
            if i % 20 == 0 and i > 0:
                print(f"{TermColors.STATUS_INFO}Fetched details for {i}/{len(messages_info)} emails...{TermColors.RESET}")

            msg_id = msg_info['id']
            thread_id = msg_info['threadId']
            msg = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            
            list_unsubscribe_header = next((h['value'] for h in headers if h['name'].lower() == 'list-unsubscribe'), None)
            list_unsubscribe_mailto = None
            list_unsubscribe_http = None

            if list_unsubscribe_header:
                mailto_match = re.search(r'<mailto:([^>]+)>', list_unsubscribe_header)
                http_match = re.search(r'<(https?:[^>]+)>', list_unsubscribe_header)
                if mailto_match: list_unsubscribe_mailto = mailto_match.group(1)
                if http_match: list_unsubscribe_http = http_match.group(1)
            
            internal_date_ms = int(msg.get('internalDate', '0'))
            received_dt = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)
            snippet = msg.get('snippet', '')
            body_plain_content = ""

            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        body_data = part['body'].get('data')
                        if body_data: body_plain_content += base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
                        break 
            elif 'body' in payload and payload['body'].get('data') and payload.get('mimeType') == 'text/plain':
                body_data = payload['body']['data']
                body_plain_content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')

            fetched_emails.append(EmailDetails(
                id=msg_id, thread_id=thread_id, subject=subject, sender=sender,
                received_date=received_dt, snippet=snippet,
                body_plain=body_plain_content.strip() if body_plain_content else snippet,
                list_unsubscribe_mailto=list_unsubscribe_mailto, list_unsubscribe_http=list_unsubscribe_http
            ))
            if len(fetched_emails) >= max_emails: break
        print(f"{TermColors.STATUS_SUCCESS}Successfully fetched details for {len(fetched_emails)} emails.{TermColors.RESET}")

    except HttpError as error: # HttpError is still imported at the top
        print(f'{TermColors.STATUS_ERROR}An error occurred fetching emails: {error}{TermColors.RESET}')
    return fetched_emails

# --- Email Analysis ---
def analyze_email_for_deletion(client: OpenAI, email: EmailDetails) -> EmailDeletionSuggestion:
    if email.received_date < (datetime.now(timezone.utc) - timedelta(days=365*2)): # Older than 2 years
        return EmailDeletionSuggestion(
            email_id=email.id, subject=email.subject, sender=email.sender, received_date=email.received_date.isoformat(),
            suggestion="strong_candidate", reason_category="age", reason_detail="Email older than 2 years.",
            list_unsubscribe_mailto=email.list_unsubscribe_mailto, list_unsubscribe_http=email.list_unsubscribe_http
        )
    prompt_text = f"""
    Analyze the following email to determine if it's a strong candidate for deletion.
    Consider if it's promotional, a social media notification, an outdated alert, a newsletter the user likely no longer reads,
    or general clutter. Prioritize keeping emails that seem transactional (receipts, bookings), personal, or work-related unless very old.

    Email Details:
    Subject: {email.subject}
    From: {email.sender}
    Date: {email.received_date.strftime('%Y-%m-%d')}
    Snippet: {email.snippet}
    Body (first 200 chars): {email.body_plain[:200] if email.body_plain else ""}

    Based on this, provide a JSON response with:
    - "suggestion": "strong_candidate", "possible_candidate", or "keep"
    - "reason_category": "ai_promotional", "ai_social", "ai_outdated_alert", "ai_newsletter", "ai_general_clutter", "ai_transactional", "ai_personal", "ai_work_related", "ai_unsure"
    - "reason_detail": A brief explanation for your suggestion.
    - "ai_confidence": Your confidence in this assessment (0.0 to 1.0).
    """
    try:
        response = client.chat.completions.create(
            model="gpt-3.5-turbo",
            messages=[
                {"role": "system", "content": "You are an email management assistant helping to identify emails for deletion. Be conservative with important-looking emails."},
                {"role": "user", "content": prompt_text}
            ],
            response_format={"type": "json_object"}
        )
        analysis_data = json.loads(response.choices[0].message.content)
        return EmailDeletionSuggestion(
            email_id=email.id, subject=email.subject, sender=email.sender, received_date=email.received_date.isoformat(),
            suggestion=analysis_data.get("suggestion", "keep"),
            reason_category=analysis_data.get("reason_category", "ai_unsure"),
            reason_detail=analysis_data.get("reason_detail", "AI analysis performed."),
            ai_confidence=analysis_data.get("ai_confidence"),
            list_unsubscribe_mailto=email.list_unsubscribe_mailto, list_unsubscribe_http=email.list_unsubscribe_http
        )
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Error analyzing email ID {email.id} with AI: {e}{TermColors.RESET}")
        return EmailDeletionSuggestion(
            email_id=email.id, subject=email.subject, sender=email.sender, received_date=email.received_date.isoformat(),
            suggestion="keep", reason_category="ai_unsure", reason_detail=f"AI analysis failed: {e}",
            list_unsubscribe_mailto=email.list_unsubscribe_mailto, list_unsubscribe_http=email.list_unsubscribe_http
        )

# --- Reporting ---
def generate_deletion_plan_reports(deletion_suggestions: List[EmailDeletionSuggestion]):
    strong_candidates = [s for s in deletion_suggestions if s.suggestion == "strong_candidate"]
    possible_candidates = [s for s in deletion_suggestions if s.suggestion == "possible_candidate"]

    # Terminal Report
    print(f"\n{TermColors.SUMMARY_HEADER}--- Email Deletion Plan: Executive Summary ---{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Total Emails Analyzed:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(deletion_suggestions)}{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Strong Deletion Candidates:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(strong_candidates)}{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Possible Deletion Candidates:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(possible_candidates)}{TermColors.RESET}")
    
    reason_summary = {}
    for s in strong_candidates:
        reason_summary[s.reason_category] = reason_summary.get(s.reason_category, 0) + 1
    
    if reason_summary:
        print(f"\n{TermColors.SUMMARY_KEY}Breakdown of Strong Candidates by Reason:{TermColors.RESET}")
        for reason, count in reason_summary.items():
            print(f"- {TermColors.CYAN}{reason}{TermColors.RESET}: {TermColors.SUMMARY_VALUE}{count}{TermColors.RESET}")

    # Text File Report (remains uncolored for simplicity of the file content)
    with open(DELETION_PLAN_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("--- Email Deletion Plan Report ---\n")
        f.write(f"Generated on: {datetime.now().isoformat()}\n\n")
        f.write("--- Executive Summary ---\n")
        f.write(f"Total Emails Analyzed: {len(deletion_suggestions)}\n")
        f.write(f"Strong Deletion Candidates: {len(strong_candidates)}\n")
        f.write(f"Possible Deletion Candidates: {len(possible_candidates)}\n\n")
        if reason_summary:
            f.write("Breakdown of Strong Candidates by Reason:\n")
            for reason, count in reason_summary.items(): f.write(f"- {reason}: {count}\n")
            f.write("\n")
        f.write("\n--- Strong Deletion Candidates ---\n")
        if strong_candidates:
            for s in strong_candidates:
                f.write(f"Subject: {s.subject}\nFrom: {s.sender}\nDate: {s.received_date}\n")
                f.write(f"Reason Category: {s.reason_category}\nDetail: {s.reason_detail}\n")
                if s.ai_confidence is not None: f.write(f"AI Confidence: {s.ai_confidence:.2f}\n")
                if s.list_unsubscribe_mailto: f.write(f"Unsubscribe Mailto: {s.list_unsubscribe_mailto}\n")
                if s.list_unsubscribe_http: f.write(f"Unsubscribe HTTP: {s.list_unsubscribe_http}\n")
                f.write(f"Email ID: {s.email_id}\n" + "-" * 30 + "\n")
        else: f.write("No strong candidates identified.\n")
        f.write("\n--- Possible Deletion Candidates ---\n")
        if possible_candidates:
            for s in possible_candidates:
                f.write(f"Subject: {s.subject}\nFrom: {s.sender}\nDate: {s.received_date}\n")
                f.write(f"Reason Category: {s.reason_category}\nDetail: {s.reason_detail}\n")
                if s.ai_confidence is not None: f.write(f"AI Confidence: {s.ai_confidence:.2f}\n")
                if s.list_unsubscribe_mailto: f.write(f"Unsubscribe Mailto: {s.list_unsubscribe_mailto}\n")
                if s.list_unsubscribe_http: f.write(f"Unsubscribe HTTP: {s.list_unsubscribe_http}\n")
                f.write(f"Email ID: {s.email_id}\n" + "-" * 30 + "\n")
        else: f.write("No possible candidates identified.\n")
            
    print(f"\n{TermColors.STATUS_SUCCESS}Detailed deletion plan report saved to: {DELETION_PLAN_REPORT_FILE}{TermColors.RESET}")
    candidates_for_json = {"strong_candidates": [s.model_dump() for s in strong_candidates], "possible_candidates": [s.model_dump() for s in possible_candidates]}
    with open(DELETION_CANDIDATES_JSON_FILE, "w", encoding="utf-8") as f_json:
        json.dump(candidates_for_json, f_json, indent=2)
    print(f"{TermColors.STATUS_SUCCESS}Deletion candidates saved to JSON: {DELETION_CANDIDATES_JSON_FILE}{TermColors.RESET}")

# --- Main Orchestration ---
def run_cleanup_planning(gmail_service, openai_client): # Renamed and added parameters
    print(f"{TermColors.BOLD}Starting Email Deletion Planner...{TermColors.RESET}")
    
    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available for cleanup planning. Exiting.{TermColors.RESET}")
        return
    
    if not openai_client:
        print(f"{TermColors.STATUS_ERROR}OpenAI client not available for cleanup planning. Exiting.{TermColors.RESET}")
        return

    # openai_client = OpenAI() # Use passed-in client
    days_to_scan_for_old_emails = 30 # Default for CLI, can be made configurable
    max_emails_to_process = 50  # Default for CLI, can be made configurable
    
    # User input for days_to_scan and max_emails could be added here if desired for CLI flexibility
    # For now, using fixed values for simplicity in refactoring.
    # Example prompt for days:
    try:
        days_input = input(f"How many days of older emails to scan (default {days_to_scan_for_old_emails})? Press Enter for default: ")
        if days_input.strip():
            days_to_scan_for_old_emails = int(days_input)
        
        max_input = input(f"Maximum number of emails to process (default {max_emails_to_process})? Press Enter for default: ")
        if max_input.strip():
            max_emails_to_process = int(max_input)

    except ValueError:
        print(f"{TermColors.YELLOW}Invalid input. Using default values.{TermColors.RESET}")


    emails_to_analyze = fetch_emails_for_deletion_planning(
        gmail_service, days_to_scan=days_to_scan_for_old_emails, max_emails=max_emails_to_process
    )

    if not emails_to_analyze:
        print(f"{TermColors.YELLOW}No emails fetched for analysis. Exiting.{TermColors.RESET}")
        return

    all_suggestions: List[EmailDeletionSuggestion] = []
    print(f"\n{TermColors.STATUS_INFO}Analyzing {len(emails_to_analyze)} emails for deletion potential...{TermColors.RESET}")
    for i, email in enumerate(emails_to_analyze):
        if i % 10 == 0 and i > 0:
            print(f"{TermColors.STATUS_INFO}Analyzed {i}/{len(emails_to_analyze)} emails...{TermColors.RESET}")
        suggestion = analyze_email_for_deletion(openai_client, email)
        all_suggestions.append(suggestion)
    
    print(f"{TermColors.STATUS_SUCCESS}Analysis complete.{TermColors.RESET}")
    generate_deletion_plan_reports(all_suggestions)

    print(f"\n{TermColors.BOLD}Email Deletion Planner finished.{TermColors.RESET}")

if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email Deletion Planner Standalone...{TermColors.RESET}")
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

    run_cleanup_planning(standalone_gmail_service, standalone_openai_client)
