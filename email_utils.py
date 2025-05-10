import os
import json
import base64
from email.mime.text import MIMEText

from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request as GoogleAuthRequest # Renamed to avoid conflict
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

# ANSI escape codes for colors
class TermColors:
    RESET = '\033[0m'
    BOLD = '\033[1m'
    RED = '\033[91m'
    GREEN = '\033[92m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    MAGENTA = '\033[95m'
    CYAN = '\033[96m'
    # For planner/executor status
    STATUS_INFO = CYAN
    STATUS_SUCCESS = GREEN
    STATUS_ERROR = RED
    # For report summary
    SUMMARY_HEADER = BOLD + BLUE
    SUMMARY_KEY = BOLD
    SUMMARY_VALUE = GREEN
    # For executor prompts
    PROMPT_UNSUB_MAIL = YELLOW
    PROMPT_UNSUB_HTTP = CYAN
    PROMPT_DELETE = RED
    CANDIDATE_INFO = BLUE

# --- Gmail Service Utility ---

# Define comprehensive scopes needed by any script using these utils
# Individual scripts might not use all, but token will hold all granted.
SCOPES_UTIL = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify'
]

# Determine the absolute path to the directory containing this utils script
# Token and credentials files will be expected in the same directory as the scripts that use these utils,
# so those scripts will define their own SCRIPT_DIR, TOKEN_FILE, CREDENTIALS_FILE.
# get_gmail_service will need to accept these paths.

def get_gmail_service(token_file_path: str, credentials_file_path: str, scopes: list):
    """
    Authenticates with Gmail API and returns a service object.
    Args:
        token_file_path: Path to the token.json file.
        credentials_file_path: Path to the credentials.json file.
        scopes: List of scopes to request.
    """
    creds = None
    if os.path.exists(token_file_path):
        try:
            # Step 1: Load token to inspect its current scopes
            temp_creds = Credentials.from_authorized_user_file(token_file_path) 
            
            # Step 2: Compare with scopes required by the current script/operation
            required_scopes_set = set(scopes) # 'scopes' is the parameter to get_gmail_service
            token_scopes_set = set(temp_creds.scopes)

            if required_scopes_set.issubset(token_scopes_set):
                # All required scopes are present, load creds properly with these scopes
                creds = Credentials.from_authorized_user_file(token_file_path, scopes)
                # print(f"{TermColors.GREEN}Token loaded successfully with all required scopes from {token_file_path}.{TermColors.RESET}") # Optional: too verbose if always printed
            else:
                # Step 3: Handle Missing Scopes
                missing = list(required_scopes_set - token_scopes_set)
                print(f"{TermColors.YELLOW}Warning: Token file {token_file_path} is missing required permissions.{TermColors.RESET}")
                print(f"  Required for current operation: {list(required_scopes_set)}")
                print(f"  Token currently has: {list(token_scopes_set)}")
                print(f"  Missing: {missing}")
                print(f"{TermColors.YELLOW}Forcing re-authentication to obtain all necessary permissions.{TermColors.RESET}")
                creds = None # Force re-authentication
                os.remove(token_file_path)
                print(f"{TermColors.YELLOW}Removed token file with insufficient scopes: {token_file_path}{TermColors.RESET}")

        except ValueError as e: # Step 4: Fallback for other token issues like malformed JSON
            print(f"{TermColors.YELLOW}Warning: Could not load token from {token_file_path} (ValueError: {e}). Will attempt re-authentication.{TermColors.RESET}")
            creds = None 
            if os.path.exists(token_file_path):
                try:
                    os.remove(token_file_path)
                    print(f"{TermColors.YELLOW}Removed potentially problematic token file: {token_file_path}{TermColors.RESET}")
                except OSError as oe:
                    print(f"{TermColors.RED}Error removing token file {token_file_path}: {oe}{TermColors.RESET}")
        except Exception as e: # Catch any other unexpected errors during token load
            print(f"{TermColors.RED}Unexpected error loading token from {token_file_path}: {e}. Will attempt re-authentication.{TermColors.RESET}")
            creds = None
            if os.path.exists(token_file_path):
                try:
                    os.remove(token_file_path)
                    print(f"{TermColors.YELLOW}Removed token file due to unexpected error: {token_file_path}{TermColors.RESET}")
                except OSError as oe:
                    print(f"{TermColors.RED}Error removing token file {token_file_path}: {oe}{TermColors.RESET}")

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            try:
                creds.refresh(GoogleAuthRequest())
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}Error refreshing token: {e}. Deleting token and re-authenticating.{TermColors.RESET}")
                if os.path.exists(token_file_path): # Ensure removal if refresh fails
                    try:
                        os.remove(token_file_path)
                        print(f"{TermColors.YELLOW}Removed token file after failed refresh: {token_file_path}{TermColors.RESET}")
                    except OSError as oe:
                         print(f"{TermColors.RED}Error removing token file {token_file_path}: {oe}{TermColors.RESET}")
                creds = None 
        
        if not creds: # This block runs if creds is None (initial state, or after failed load/refresh)
            if not os.path.exists(credentials_file_path):
                print(f"{TermColors.STATUS_ERROR}CRITICAL ERROR: {credentials_file_path} not found. Please download it from Google Cloud Console.{TermColors.RESET}")
                return None
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file_path, scopes)
            creds = flow.run_local_server(port=0)
        with open(token_file_path, 'w') as token:
            token.write(creds.to_json())
    try:
        service = build('gmail', 'v1', credentials=creds)
        return service
    except HttpError as error:
        print(f'{TermColors.STATUS_ERROR}An error occurred building the Gmail service: {error}{TermColors.RESET}')
        return None
    except Exception as e:
        print(f'{TermColors.STATUS_ERROR}An unexpected error occurred getting Gmail service: {e}{TermColors.RESET}')
        return None


def send_email(service, subject: str, body: str, recipient_email: str) -> bool:
    """
    Sends an email using the provided Gmail service.
    Args:
        service: Authorized Gmail API service instance.
        subject: Email subject.
        body: Email body content.
        recipient_email: Recipient's email address.
    Returns:
        bool: True if email was sent successfully, False otherwise.
    """
    if not service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available, cannot send email.{TermColors.RESET}")
        return False
    try:
        message = MIMEText(body)
        message['to'] = recipient_email
        message['subject'] = subject
        create_message = {'raw': base64.urlsafe_b64encode(message.as_bytes()).decode()}
        
        sent_message = service.users().messages().send(userId="me", body=create_message).execute()
        print(f"{TermColors.STATUS_SUCCESS}Sent email to {recipient_email}. Subject: '{subject}'. Message ID: {sent_message['id']}{TermColors.RESET}")
        return True
    except HttpError as error:
        print(f"{TermColors.STATUS_ERROR}An error occurred sending email to {recipient_email}: {error}{TermColors.RESET}")
        return False
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}An unexpected error occurred sending email: {e}{TermColors.RESET}")
        return False
