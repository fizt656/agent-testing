import os
import json
from datetime import datetime, timedelta, timezone
from openai import OpenAI
from pydantic import BaseModel, Field
from typing import List, Optional, Literal
import base64
import re

# Import utilities
from email_utils import get_gmail_service, TermColors
import sys # For sys.exit in standalone mode

from googleapiclient.errors import HttpError

# Load environment variables
from dotenv import load_dotenv
load_dotenv(override=True)

# --- Configuration ---
# Gmail API Scopes needed by THIS script
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify'] 

# Determine the absolute path to THIS script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# Define the categories for AI classification and corresponding Gmail labels
CATEGORIES = [
    "Personal",
    "Work",
    "Transactional",
    "Notifications",
    "Newsletters/Promotions",
    "Forums/Groups",
    "Spam/Junk", # We won't apply a label for this, but AI can classify
    "Other" # We won't apply a label for this
]

# Define which categories should have a corresponding Gmail label created and applied
LABELS_TO_APPLY = [
    "Personal",
    "Work",
    "Transactional",
    "Notifications",
    "Newsletters/Promotions",
    "Forums/Groups"
    # Spam/Junk and Other will not have labels applied by this script
]

# Timeframe for fetching emails (e.g., last 24 hours)
FETCH_TIMEFRAME_HOURS = 24
# Maximum emails to process per run
MAX_EMAILS_TO_PROCESS = 100 # Increased default slightly

# Report file
CATEGORIZATION_REPORT_FILE = os.path.join(SCRIPT_DIR, "categorization_report.txt")
CATEGORIZED_EMAILS_JSON_FILE = os.path.join(SCRIPT_DIR, "categorized_emails_general.json")


# --- Pydantic Models ---
class EmailCategorization(BaseModel):
    email_id: str
    thread_id: str
    subject: str
    sender: str
    received_date: str
    category: Literal[tuple(CATEGORIES)] # Use the defined categories
    reason: str
    confidence: Optional[float] = None # AI might provide confidence

class EmailDetails(BaseModel):
    id: str
    thread_id: str
    subject: str
    sender: str
    received_date: datetime
    snippet: str
    body_plain: Optional[str] = None


# --- Main Logic ---
def run_general_categorization(gmail_service, openai_client): # Renamed and added parameters
    print(f"{TermColors.BOLD}Starting Email General Categorizer...{TermColors.RESET}")

    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available for general categorizer. Exiting.{TermColors.RESET}")
        return
    
    if not openai_client:
        print(f"{TermColors.STATUS_ERROR}OpenAI client not available for general categorizer. Exiting.{TermColors.RESET}")
        return

    # openai_client = OpenAI() # Use passed-in client

    # 1. Get or create necessary labels
    label_ids = {}
    print(f"{TermColors.STATUS_INFO}Checking for necessary labels...{TermColors.RESET}")
    try:
        results = gmail_service.users().labels().list(userId='me').execute()
        existing_labels = {label['name']: label['id'] for label in results.get('labels', [])}

        for label_name in LABELS_TO_APPLY:
            if label_name in existing_labels:
                label_ids[label_name] = existing_labels[label_name]
                print(f"{TermColors.STATUS_SUCCESS}Found existing label '{label_name}' with ID: {label_ids[label_name]}{TermColors.RESET}")
            else:
                print(f"{TermColors.STATUS_INFO}Label '{label_name}' not found. Creating it...{TermColors.RESET}")
                created_label = gmail_service.users().labels().create(userId='me', body={'name': label_name}).execute()
                label_ids[label_name] = created_label['id']
                print(f"{TermColors.STATUS_SUCCESS}Created label '{label_name}' with ID: {label_ids[label_name]}{TermColors.RESET}")

    except HttpError as error:
        print(f'{TermColors.STATUS_ERROR}An error occurred while getting or creating labels: {error}{TermColors.RESET}')
        return
    
    if len(label_ids) != len(LABELS_TO_APPLY):
         print(f"{TermColors.STATUS_ERROR}Could not find or create all required labels. Cannot proceed with labeling. Exiting.{TermColors.RESET}")
         # We could still proceed with just categorization report if desired, but for now, exit.
         return


    # 2. Fetch recent emails
    fetched_emails: List[EmailDetails] = []
    cutoff_date = datetime.now(timezone.utc) - timedelta(hours=FETCH_TIMEFRAME_HOURS)
    # Fetch emails received after the cutoff date, excluding Spam and Trash
    query = f'after:{cutoff_date.strftime("%Y/%m/%d %H:%M")} -in:spam -in:trash' # Include time for more precision

    print(f"\n{TermColors.STATUS_INFO}Fetching emails with query: '{query}' (up to {MAX_EMAILS_TO_PROCESS} emails){TermColors.RESET}")

    try:
        response = gmail_service.users().messages().list(
            userId='me',
            q=query,
            maxResults=MAX_EMAILS_TO_PROCESS
        ).execute()
        
        messages_info = response.get('messages', [])
        
        if not messages_info:
            print(f"{TermColors.YELLOW}No emails found matching the criteria.{TermColors.RESET}")
            # Still generate empty reports
            generate_categorization_reports([], CATEGORIES, label_ids)
            return

        print(f"{TermColors.STATUS_INFO}Found {len(messages_info)} email messages. Fetching details...{TermColors.RESET}")
        
        for i, msg_info in enumerate(messages_info):
            if i % 20 == 0 and i > 0:
                print(f"{TermColors.STATUS_INFO}Fetched details for {i}/{len(messages_info)} emails...{TermColors.RESET}")

            msg_id = msg_info['id']
            thread_id = msg_info['threadId']
            msg = gmail_service.users().messages().get(userId='me', id=msg_id, format='full').execute()
            
            payload = msg.get('payload', {})
            headers = payload.get('headers', [])
            
            subject = next((h['value'] for h in headers if h['name'].lower() == 'subject'), 'No Subject')
            sender = next((h['value'] for h in headers if h['name'].lower() == 'from'), 'Unknown Sender')
            
            internal_date_ms = int(msg.get('internalDate', '0'))
            received_dt = datetime.fromtimestamp(internal_date_ms / 1000, tz=timezone.utc)
            
            snippet = msg.get('snippet', '')
            body_plain_content = ""

            if 'parts' in payload:
                for part in payload['parts']:
                    if part['mimeType'] == 'text/plain':
                        body_data = part['body'].get('data')
                        if body_data:
                            body_plain_content += base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')
                        break 
            elif 'body' in payload and payload['body'].get('data') and payload.get('mimeType') == 'text/plain':
                body_data = payload['body']['data']
                body_plain_content = base64.urlsafe_b64decode(body_data).decode('utf-8', errors='replace')

            fetched_emails.append(EmailDetails(
                id=msg_id, thread_id=thread_id, subject=subject, sender=sender,
                received_date=received_dt, snippet=snippet,
                body_plain=body_plain_content.strip() if body_plain_content else snippet
            ))
        print(f"{TermColors.STATUS_SUCCESS}Successfully fetched details for {len(fetched_emails)} emails.{TermColors.RESET}")

    except HttpError as error:
        print(f'{TermColors.STATUS_ERROR}An error occurred fetching emails: {error}{TermColors.RESET}')
        # Still generate empty reports on error
        generate_categorization_reports([], CATEGORIES, label_ids)
        return
    
    if not fetched_emails:
        print(f"{TermColors.YELLOW}No emails fetched for analysis. Exiting.{TermColors.RESET}")
        generate_categorization_reports([], CATEGORIES, label_ids)
        return


    # 3. AI Categorization and Labeling
    categorized_emails: List[EmailCategorization] = []
    emails_to_label = {} # {label_id: [email_id, ...]}

    print(f"\n{TermColors.STATUS_INFO}Analyzing {len(fetched_emails)} emails for categorization and applying labels...{TermColors.RESET}")

    for i, email in enumerate(fetched_emails):
        if i % 10 == 0 and i > 0:
            print(f"{TermColors.STATUS_INFO}Analyzed {i}/{len(fetched_emails)} emails...{TermColors.RESET}")

        # Send to AI for categorization
        prompt_text = f"""
        Categorize the following email into one of these specific categories: {', '.join(CATEGORIES)}.
        Email Details:
        Subject: {email.subject}
        From: {email.sender}
        Date: {email.received_date.strftime('%Y-%m-%d')}
        Snippet: {email.snippet}
        Body (first 200 chars): {email.body_plain[:200] if email.body_plain else ""}

        Provide a JSON response with:
        - "category": One of the specified categories.
        - "reason": Brief explanation for the category.
        - "confidence": Your confidence (0.0 to 1.0).
        """
        try:
            response = openai_client.chat.completions.create(
                model="gpt-3.5-turbo", # Cheaper model for bulk analysis
                messages=[
                    {"role": "system", "content": f"You are an email categorizer. Classify emails into one of these categories: {', '.join(CATEGORIES)}."},
                    {"role": "user", "content": prompt_text}
                ],
                response_format={"type": "json_object"}
            )
            analysis_data = json.loads(response.choices[0].message.content)
            
            # Validate category against our list
            predicted_category = analysis_data.get("category", "Other")
            if predicted_category not in CATEGORIES:
                 print(f"{TermColors.YELLOW}Warning: AI returned unexpected category '{predicted_category}' for email '{email.subject}'. Defaulting to 'Other'.{TermColors.RESET}")
                 predicted_category = "Other"

            categorization = EmailCategorization(
                email_id=email.id, thread_id=email.thread_id, subject=email.subject, sender=email.sender,
                received_date=email.received_date.isoformat(),
                category=predicted_category,
                reason=analysis_data.get("reason", "AI categorization"),
                confidence=analysis_data.get("confidence")
            )
            categorized_emails.append(categorization)

            # Prepare for labeling if the category is in our LABELS_TO_APPLY list
            if predicted_category in LABELS_TO_APPLY:
                label_id = label_ids.get(predicted_category)
                if label_id:
                    if label_id not in emails_to_label:
                        emails_to_label[label_id] = []
                    emails_to_label[label_id].append(email.id)
                    # print(f"Prepared to label email {email.id} with '{predicted_category}' ({label_id})") # Debugging print

        except Exception as e:
            print(f"{TermColors.STATUS_ERROR}Error analyzing email ID {email.id} with AI: {e}{TermColors.RESET}")
            # Add to categorized_emails with 'Other' category on error
            categorized_emails.append(EmailCategorization(
                 email_id=email.id, thread_id=email.thread_id, subject=email.subject, sender=email.sender,
                 received_date=email.received_date.isoformat(),
                 category="Other", reason=f"AI analysis failed: {e}"
            ))

    print(f"{TermColors.STATUS_SUCCESS}AI categorization complete.{TermColors.RESET}")

    # 4. Apply labels in batches
    print(f"\n{TermColors.STATUS_INFO}Applying labels to emails...{TermColors.RESET}")
    total_labeled_count = 0

    for label_name, email_ids in emails_to_label.items():
        label_id = label_ids.get(label_name) # Get the actual ID
        if not label_id:
             print(f"{TermColors.STATUS_ERROR}Error: Could not find ID for label '{label_name}'. Skipping labeling for these emails.{TermColors.RESET}")
             continue

        print(f"{TermColors.STATUS_INFO}Applying label '{label_name}' to {len(email_ids)} emails...{TermColors.RESET}")
        
        # Batch modify to add the label
        batch_size = 100 # Gmail API batchModify limit
        for i in range(0, len(email_ids), batch_size):
            batch_ids = email_ids[i:i + batch_size]
            try:
                gmail_service.users().messages().batchModify(
                    userId='me',
                    body={
                        'ids': batch_ids,
                        'addLabelIds': [label_id]
                    }
                ).execute()
                total_labeled_count += len(batch_ids)
                print(f"{TermColors.STATUS_INFO}Labeled batch {i//batch_size + 1} for '{label_name}': {total_labeled_count} total emails labeled so far...{TermColors.RESET}")

            except HttpError as error:
                print(f'{TermColors.STATUS_ERROR}An error occurred while applying label {label_name} to batch starting with ID {batch_ids[0]}: {error}{TermColors.RESET}')
                # Decide how to handle errors - skip batch, retry, etc.

    print(f"{TermColors.STATUS_SUCCESS}Finished applying labels. Total emails labeled: {total_labeled_count}.{TermColors.RESET}")


    # 5. Generate reports
    generate_categorization_reports(categorized_emails, CATEGORIES, label_ids)

    print(f"\n{TermColors.BOLD}Email General Categorizer finished.{TermColors.RESET}")


# --- Reporting ---
def generate_categorization_reports(categorized_emails: List[EmailCategorization], categories: List[str], label_ids: dict):
    """Generates terminal and file reports for the categorization."""
    
    # Group emails by category
    categorized_groups = {category: [] for category in categories}
    for email in categorized_emails:
        if email.category in categorized_groups:
            categorized_groups[email.category].append(email)
        else: # Should not happen if AI output is validated, but as a fallback
             categorized_groups["Other"].append(email) # Add to other if category is unexpected


    # Terminal Report
    print(f"\n{TermColors.SUMMARY_HEADER}--- Email Categorization Report: Executive Summary ---{TermColors.RESET}")
    print(f"{TermColors.SUMMARY_KEY}Total Emails Analyzed:{TermColors.RESET} {TermColors.SUMMARY_VALUE}{len(categorized_emails)}{TermColors.RESET}")
    
    print(f"\n{TermColors.SUMMARY_KEY}Breakdown by Category:{TermColors.RESET}")
    for category in categories:
        count = len(categorized_groups[category])
        print(f"- {TermColors.CYAN}{category}{TermColors.RESET}: {TermColors.SUMMARY_VALUE}{count}{TermColors.RESET}")

    # Text File Report
    with open(CATEGORIZATION_REPORT_FILE, "w", encoding="utf-8") as f:
        f.write("--- Email Categorization Report ---\n")
        f.write(f"Generated on: {datetime.now().isoformat()}\n\n")
        f.write("--- Executive Summary ---\n")
        f.write(f"Total Emails Analyzed: {len(categorized_emails)}\n\n")
        f.write("Breakdown by Category:\n")
        for category in categories:
            count = len(categorized_groups[category])
            f.write(f"- {category}: {count}\n")
        f.write("\n")

        f.write("\n--- Detailed Categorization ---\n")
        for category in categories:
            emails_in_category = categorized_groups[category]
            if emails_in_category:
                f.write(f"\n--- Category: {category} ({len(emails_in_category)} emails) ---\n")
                for email in emails_in_category:
                    f.write(f"Subject: {email.subject}\nFrom: {email.sender}\nDate: {email.received_date}\n")
                    f.write(f"Reason: {email.reason}\n")
                    if email.confidence is not None: f.write(f"Confidence: {email.confidence:.2f}\n")
                    f.write(f"Email ID: {email.email_id}\n")
                    f.write("-" * 30 + "\n")
            else:
                 f.write(f"\n--- Category: {category} (0 emails) ---\n")
                 f.write("No emails in this category.\n")
                 f.write("-" * 30 + "\n")

    print(f"\n{TermColors.STATUS_SUCCESS}Categorization report saved to: {CATEGORIZATION_REPORT_FILE}{TermColors.RESET}")

    # Save categorized emails to JSON
    categorized_emails_for_json = [email.model_dump() for email in categorized_emails]
    with open(CATEGORIZED_EMAILS_JSON_FILE, "w", encoding="utf-8") as f_json:
        json.dump(categorized_emails_for_json, f_json, indent=2)
    print(f"{TermColors.STATUS_SUCCESS}Categorized emails saved to JSON: {CATEGORIZED_EMAILS_JSON_FILE}{TermColors.RESET}")


if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email General Categorizer Standalone...{TermColors.RESET}")
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
        
    run_general_categorization(standalone_gmail_service, standalone_openai_client)
