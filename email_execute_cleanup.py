import os
import json
from datetime import datetime, timezone
import base64
import re
import requests # For visiting HTTP unsubscribe links

# Import utilities
from email_utils import get_gmail_service, TermColors, send_email # send_email is not directly used but good to have if needed
import sys # For sys.exit in standalone mode

# Removed Google specific imports as they are in email_utils
# from google_auth_oauthlib.flow import InstalledAppFlow
# from google.auth.transport.requests import Request as GoogleAuthRequest 
# from google.oauth2.credentials import Credentials
# from googleapiclient.discovery import build
from googleapiclient.errors import HttpError # Keep for local error handling
from email.mime.text import MIMEText # Keep for send_unsubscribe_email_action

from dotenv import load_dotenv

# Load environment variables
load_dotenv(override=True)

# TermColors class is now imported from email_utils

# --- Configuration ---
SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly', 
    'https://www.googleapis.com/auth/gmail.send',     
    'https://www.googleapis.com/auth/gmail.modify'    
]
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json") 
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

DELETION_CANDIDATES_JSON_FILE = os.path.join(SCRIPT_DIR, "deletion_candidates.json")
ACTION_LOG_FILE = os.path.join(SCRIPT_DIR, "cline/action_executor_log.txt")

# get_gmail_service function is now imported from email_utils

# --- Action Functions ---
def log_action(action_details):
    os.makedirs(os.path.dirname(ACTION_LOG_FILE), exist_ok=True)
    with open(ACTION_LOG_FILE, "a", encoding="utf-8") as f:
        # Strip colors for log file
        cleaned_details = action_details.replace(TermColors.RESET, '').replace(TermColors.GREEN, '').replace(TermColors.RED, '').replace(TermColors.YELLOW, '').replace(TermColors.BLUE, '').replace(TermColors.CYAN, '').replace(TermColors.BOLD, '')
        f.write(f"[{datetime.now().isoformat()}] {cleaned_details}\n") 
    
    # Print to console (already includes colors if TermColors were used in action_details)
    print(action_details)


def send_unsubscribe_email_action(service, to_address, original_subject):
    try:
        email_body = (
            f"This is an automated unsubscribe request regarding emails with subjects similar to: \"{original_subject}\".\n\n"
            "Please remove this email address from your mailing list.\n\n"
            "If this is an error, please ignore this message.\n"
            "(This email was sent by an automated script based on user direction.)"
        )
        message = MIMEText(email_body)
        message['to'] = to_address
        message['subject'] = f"Automated Unsubscribe Request" 
        
        create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        sent_message = service.users().messages().send(userId="me", body=create_message).execute()
        log_action(f"{TermColors.GREEN}SUCCESS: Sent unsubscribe email to {to_address}. Message ID: {sent_message['id']}{TermColors.RESET}")
        return True
    except HttpError as error:
        log_action(f"{TermColors.RED}ERROR sending unsubscribe email to {to_address}: {error}{TermColors.RESET}")
        return False
    except Exception as e:
        log_action(f"{TermColors.RED}UNEXPECTED ERROR sending unsubscribe email to {to_address}: {e}{TermColors.RESET}")
        return False

def visit_unsubscribe_link_action(url):
    try:
        headers = { 
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
        response = requests.get(url, headers=headers, timeout=10, allow_redirects=True)
        response.raise_for_status() 
        
        if response.status_code == 200:
            log_action(f"{TermColors.GREEN}SUCCESS: Visited unsubscribe link {url}. Status: {response.status_code}.{TermColors.RESET}")
            content_sample = response.text[:1024].lower()
            success_keywords = ["unsubscribed", "removed", "success", "no longer receive", "manage your preferences"]
            if any(keyword in content_sample for keyword in success_keywords):
                log_action(f"{TermColors.GREEN}INFO: Unsubscribe page for {url} seems to indicate success.{TermColors.RESET}")
            else:
                log_action(f"{TermColors.YELLOW}WARNING: Visited {url}, but success message not detected. Manual check might be needed.{TermColors.RESET}")
            return True
        else:
            log_action(f"{TermColors.YELLOW}INFO: Visited unsubscribe link {url}. Status: {response.status_code}. Might not be a direct unsubscribe.{TermColors.RESET}")
            return False
            
    except requests.exceptions.RequestException as e:
        log_action(f"{TermColors.RED}ERROR visiting unsubscribe link {url}: {e}{TermColors.RESET}")
        return False
    except Exception as e:
        log_action(f"{TermColors.RED}UNEXPECTED ERROR visiting unsubscribe link {url}: {e}{TermColors.RESET}")
        return False

def delete_email_message_action(service, message_id):
    try:
        service.users().messages().trash(userId='me', id=message_id).execute()
        log_action(f"{TermColors.GREEN}SUCCESS: Moved email ID {message_id} to trash.{TermColors.RESET}")
        return True
    except HttpError as error:
        log_action(f"{TermColors.RED}ERROR trashing email ID {message_id}: {error}{TermColors.RESET}")
        return False
    except Exception as e:
        log_action(f"{TermColors.RED}UNEXPECTED ERROR trashing email ID {message_id}: {e}{TermColors.RESET}")
        return False

# --- Main Orchestration ---
def run_cleanup_execution(gmail_service): # Renamed and added parameter
    print(f"{TermColors.BOLD}Starting Email Action Executor...{TermColors.RESET}")
    log_action("Executor script started.")

    if not os.path.exists(DELETION_CANDIDATES_JSON_FILE):
        print(f"{TermColors.RED}ERROR: Deletion plan file not found: {DELETION_CANDIDATES_JSON_FILE}{TermColors.RESET}")
        print(f"Please run the planner script ({TermColors.CYAN}email_plan_cleanup.py{TermColors.RESET}) first.")
        log_action(f"CRITICAL: {DELETION_CANDIDATES_JSON_FILE} not found. Exiting.")
        return

    with open(DELETION_CANDIDATES_JSON_FILE, "r", encoding="utf-8") as f:
        plan = json.load(f)

    strong_candidates = plan.get("strong_candidates", [])
    possible_candidates = plan.get("possible_candidates", [])
    all_candidates = strong_candidates + possible_candidates 

    if not all_candidates:
        print("No deletion candidates found in the plan file.")
        log_action("No candidates in plan file. Exiting.")
        return

    print(f"Loaded {len(strong_candidates)} strong and {len(possible_candidates)} possible candidates.")
    
    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available for cleanup execution. Exiting.{TermColors.RESET}")
        log_action("CRITICAL: Gmail service not provided to run_cleanup_execution. Exiting.")
        return

    processed_count = 0
    for i, candidate in enumerate(all_candidates):
        print(f"\n--- Processing Candidate {i+1}/{len(all_candidates)} ---")
        print(f"{TermColors.CANDIDATE_INFO}Subject: {candidate['subject']}{TermColors.RESET}")
        print(f"{TermColors.CANDIDATE_INFO}From: {candidate['sender']}{TermColors.RESET}")
        print(f"Date: {candidate['received_date']}")
        print(f"Suggestion: {candidate['suggestion']} (Reason: {candidate['reason_category']} - {candidate['reason_detail']})")
        
        email_id = candidate['email_id']
        actions_taken_for_this_email = False

        if candidate.get("list_unsubscribe_mailto"):
            mailto_url = candidate["list_unsubscribe_mailto"]
            prompt_text = f"{TermColors.PROMPT_UNSUB_MAIL}  Action: Send unsubscribe email to {mailto_url}? (y/n/s=skip email): {TermColors.RESET}"
            while True:
                choice = input(prompt_text).lower()
                if choice == 'y':
                    send_unsubscribe_email_action(gmail_service, mailto_url, candidate['subject'])
                    actions_taken_for_this_email = True
                    break
                elif choice == 'n': break
                elif choice == 's': 
                    log_action(f"User skipped all actions for email ID {email_id}.")
                    break 
                else: print("  Invalid input. Please enter y, n, or s.")
            if choice == 's': continue

        if candidate.get("list_unsubscribe_http"):
            http_url = candidate["list_unsubscribe_http"]
            prompt_text = f"{TermColors.PROMPT_UNSUB_HTTP}  Action: Attempt to visit unsubscribe link {http_url}? (y/n/s=skip email): {TermColors.RESET}"
            while True:
                choice = input(prompt_text).lower()
                if choice == 'y':
                    visit_unsubscribe_link_action(http_url)
                    actions_taken_for_this_email = True
                    break
                elif choice == 'n': break
                elif choice == 's': 
                    log_action(f"User skipped all actions for email ID {email_id}.")
                    break
                else: print("  Invalid input. Please enter y, n, or s.")
            if choice == 's': continue
            
        prompt_text = f"{TermColors.PROMPT_DELETE}  Action: Delete this email (move to trash)? (y/n/s=skip email): {TermColors.RESET}"
        while True:
            choice = input(prompt_text).lower()
            if choice == 'y':
                delete_email_message_action(gmail_service, email_id)
                actions_taken_for_this_email = True
                break
            elif choice == 'n':
                if not actions_taken_for_this_email:
                     log_action(f"User chose not to delete or take other actions for email ID {email_id}.")
                break
            elif choice == 's': 
                log_action(f"User skipped all actions for email ID {email_id}.")
                break
            else: print("  Invalid input. Please enter y, n, or s.")
        if choice == 's': continue

        processed_count +=1

    log_action(f"Executor script finished. Processed {processed_count} candidates.")
    print(f"\n{TermColors.BOLD}Email Action Executor finished.{TermColors.RESET}")

if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email Action Executor Standalone...{TermColors.RESET}")
    standalone_gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES)
    if not standalone_gmail_service:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize Gmail service for standalone run. Exiting.{TermColors.RESET}")
        # log_action is not available here unless we also pass it or make it global,
        # but the print to console is sufficient for standalone failure.
        sys.exit(1)
    
    run_cleanup_execution(standalone_gmail_service)
