import os
import json
from datetime import datetime, timezone

# Import utilities
from email_utils import get_gmail_service, TermColors
import sys # For sys.exit in standalone mode

from googleapiclient.errors import HttpError

# --- Configuration ---
# Gmail API Scopes needed by THIS script
SCOPES = ['https://www.googleapis.com/auth/gmail.readonly', 'https://www.googleapis.com/auth/gmail.modify'] 

# Determine the absolute path to THIS script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# Target label (folder) name
TARGET_LABEL_NAME = 'Old Stuff'

# --- Main Logic ---
def run_archive_unread(gmail_service): # Renamed and added parameter
    print(f"{TermColors.BOLD}Starting Email Unread Archiver...{TermColors.RESET}")

    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available for unread archiver. Exiting.{TermColors.RESET}")
        return

    # 1. Find all unread emails
    unread_message_ids = []
    page_token = None
    print(f"{TermColors.STATUS_INFO}Searching for all unread emails...{TermColors.RESET}")

    try:
        while True:
            response = gmail_service.users().messages().list(
                userId='me',
                q='is:unread in:inbox -in:spam -in:trash', # Modified query
                pageToken=page_token,
                maxResults=500 # Fetch in batches
            ).execute()
            
            messages = response.get('messages', [])
            if not messages:
                break # No more unread messages

            unread_message_ids.extend([msg['id'] for msg in messages])
            page_token = response.get('nextPageToken')

            print(f"{TermColors.STATUS_INFO}Found {len(unread_message_ids)} unread emails so far...{TermColors.RESET}")

            if not page_token:
                break # No more pages

        print(f"{TermColors.STATUS_SUCCESS}Finished searching. Found a total of {len(unread_message_ids)} unread emails.{TermColors.RESET}")

    except HttpError as error:
        print(f'{TermColors.STATUS_ERROR}An error occurred while searching for unread emails: {error}{TermColors.RESET}')
        return

    if not unread_message_ids:
        print(f"{TermColors.YELLOW}No unread emails found to archive. Exiting.{TermColors.RESET}")
        return

    # 2. Get or create the target label
    target_label_id = None
    print(f"{TermColors.STATUS_INFO}Checking for target label '{TARGET_LABEL_NAME}'...{TermColors.RESET}")

    try:
        results = gmail_service.users().labels().list(userId='me').execute()
        labels = results.get('labels', [])
        for label in labels:
            if label['name'] == TARGET_LABEL_NAME:
                target_label_id = label['id']
                print(f"{TermColors.STATUS_SUCCESS}Found existing label '{TARGET_LABEL_NAME}' with ID: {target_label_id}{TermColors.RESET}")
                break

        if not target_label_id:
            print(f"{TermColors.STATUS_INFO}Label '{TARGET_LABEL_NAME}' not found. Creating it...{TermColors.RESET}")
            created_label = gmail_service.users().labels().create(userId='me', body={'name': TARGET_LABEL_NAME}).execute()
            target_label_id = created_label['id']
            print(f"{TermColors.STATUS_SUCCESS}Created label '{TARGET_LABEL_NAME}' with ID: {target_label_id}{TermColors.RESET}")

    except HttpError as error:
        print(f'{TermColors.STATUS_ERROR}An error occurred while getting or creating label: {error}{TermColors.RESET}')
        return

    if not target_label_id:
        print(f"{TermColors.STATUS_ERROR}Could not find or create target label. Cannot proceed. Exiting.{TermColors.RESET}")
        return

    # 3. Process emails (Mark Read and Add Label)
    print(f"\n{TermColors.STATUS_INFO}Processing {len(unread_message_ids)} emails: marking as read and moving to '{TARGET_LABEL_NAME}'...{TermColors.RESET}")

    batch_size = 100 # Gmail API modify allows batch operations
    processed_count = 0

    for i in range(0, len(unread_message_ids), batch_size):
        batch_ids = unread_message_ids[i:i + batch_size]
        
        try:
            # Modify messages: remove UNREAD label, add target label
            gmail_service.users().messages().batchModify(
                userId='me',
                body={
                    'ids': batch_ids,
                    'removeLabelIds': ['UNREAD'],
                    'addLabelIds': [target_label_id]
                }
            ).execute()
            processed_count += len(batch_ids)
            print(f"{TermColors.STATUS_INFO}Processed batch {i//batch_size + 1}: {processed_count}/{len(unread_message_ids)} emails...{TermColors.RESET}")

        except HttpError as error:
            print(f'{TermColors.STATUS_ERROR}An error occurred while processing batch starting with ID {batch_ids[0]}: {error}{TermColors.RESET}')
            # Decide how to handle errors - skip batch, retry, etc. For now, just report and continue.

    print(f"\n{TermColors.STATUS_SUCCESS}Finished processing emails. Total processed: {processed_count}.{TermColors.RESET}")
    print(f"{TermColors.BOLD}Email Unread Archiver finished.{TermColors.RESET}")


if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Email Unread Archiver Standalone...{TermColors.RESET}")
    standalone_gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES)
    if not standalone_gmail_service:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize Gmail service for standalone run. Exiting.{TermColors.RESET}")
        sys.exit(1)
    
    run_archive_unread(standalone_gmail_service)
