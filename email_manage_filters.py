import os
import json

# Import utilities
from email_utils import get_gmail_service, TermColors
import sys # For sys.exit in standalone mode

from googleapiclient.errors import HttpError

# Load environment variables
from dotenv import load_dotenv
load_dotenv(override=True)

# --- Configuration ---
# Gmail API Scopes needed by THIS script (for managing filters AND labels)
SCOPES = [
    'https://www.googleapis.com/auth/gmail.settings.basic', # For filters
    'https://www.googleapis.com/auth/gmail.labels'          # For reading and creating labels
] 

# Determine the absolute path to THIS script's directory
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# Define the labels that filters will apply (must match names used in filter_definitions)
TARGET_LABELS = [
    "Transactional",
    "Notifications",
    "Newsletters/Promotions",
    "Forums/Groups"
]

# Define the filters to create
# Each dictionary represents one filter.
# 'criteria' keys map to Gmail API FilterCriteria fields (from, subject, query, etc.)
# 'action' keys map to Gmail API FilterAction fields (addLabelIds, removeLabelIds, etc.)
# Use placeholder values like "example.com" and "Keyword" that you will need to customize.
filter_definitions = [
    {
        'name': 'Transactional - Common Senders',
        'criteria': {
            'from': 'amazon.com OR ebay.com OR paypal.com OR apple.com OR google.com OR microsoft.com OR uber.com OR lyft.com OR doordash.com OR grubhub.com OR netflix.com OR hulu.com OR spotify.com OR disneyplus.com'
        },
        'action': {
            'addLabelIds': ['Transactional'] # Use the actual label name here
        }
    },
    {
        'name': 'Transactional - Financial Senders',
        'criteria': {
            'from': 'bankofamerica.com OR chase.com OR wellsfargo.com OR citibank.com OR americanexpress.com OR capitalone.com OR discover.com'
        },
        'action': {
            'addLabelIds': ['Transactional']
        }
    },
     {
        'name': 'Transactional - Utility/Town Senders (Customize)',
        'criteria': {
            'from': 'eversource.com OR nationalgridus.com OR xfinity.com OR verizon.com OR townofcanton.org' # CUSTOMIZE THESE DOMAINS
        },
        'action': {
            'addLabelIds': ['Transactional']
        }
    },
    {
        'name': 'Transactional - Subject Keywords',
        'criteria': {
            'subject': '"Order Confirmation" OR "Your Receipt" OR "Shipping Update" OR "Tracking Number" OR "Your Invoice" OR "Payment Received" OR "Your bill is ready" OR "Automatic Payment" OR "Policy Document"'
        },
        'action': {
            'addLabelIds': ['Transactional']
        }
    },

    {
        'name': 'Notifications - Social Media Senders',
        'criteria': {
            'from': 'facebookmail.com OR notification@twitter.com OR linkedin.com OR messages-noreply@linkedin.com OR pinterest.com OR instagram.com OR nextdoor.com'
        },
        'action': {
            'addLabelIds': ['Notifications'],
            'removeLabelIds': ['INBOX'] # Skip inbox
        }
    },
    {
        'name': 'Notifications - App/Service Alerts',
        'criteria': {
            'from': 'no-reply@slack.com OR github.com OR no-reply@google.com OR dropbox.com OR evernote.com'
        },
        'action': {
            'addLabelIds': ['Notifications']
        }
    },
    {
        'name': 'Notifications - Security/Account Keywords',
        'criteria': {
            'subject': '"Security Alert" OR "New sign-in" OR "Password changed" OR "Unusual activity"'
        },
        'action': {
            'addLabelIds': ['Notifications']
        }
    },

    {
        'name': 'Newsletters/Promotions - Unsubscribe Keywords',
        'criteria': {
            'query': '"unsubscribe" OR "view this email in your browser" OR "manage your preferences" OR "email preferences"' # Searches all parts
        },
        'action': {
            'addLabelIds': ['Newsletters/Promotions'],
            'removeLabelIds': ['INBOX'],
            # Note: Filters cannot directly mark as read upon arrival via API action.
            # This action is typically done by the user or another script after filtering.
        }
    },
    {
        'name': 'Newsletters/Promotions - Subject Keywords',
        'criteria': {
            'subject': '"Special Offer" OR "Discount" OR "% off" OR "Sale Ends" OR "Weekly Ad" OR "Daily Deal" OR "Exclusive" OR "Savings"'
        },
        'action': {
            'addLabelIds': ['Newsletters/Promotions'],
            'removeLabelIds': ['INBOX']
        }
    },
    {
        'name': 'Newsletters/Promotions - Placeholder Senders (Customize)',
        'criteria': {
            'from': 'deals@bestbuy.com OR news@homedepot.com OR email@target.com OR news@yourfavoritestore.com' # CUSTOMIZE THESE SENDERS
        },
        'action': {
            'addLabelIds': ['Newsletters/Promotions'],
            'removeLabelIds': ['INBOX']
        }
    },

    {
        'name': 'Forums/Groups - Platform Senders',
        'criteria': {
            'from': 'googlegroups.com OR discoursemail.com OR noreply@github.com'
        },
        'action': {
            'addLabelIds': ['Forums/Groups'],
            'removeLabelIds': ['INBOX']
        }
    },
    {
        'name': 'Forums/Groups - Subject Brackets',
        'criteria': {
            'subject': '*[*]*' # Looks for subjects containing brackets
        },
        'action': {
            'addLabelIds': ['Forums/Groups']
        }
    },
]


# --- Main Logic ---
def run_filter_management(gmail_service): # Renamed and added parameter
    print(f"{TermColors.BOLD}Starting Gmail Filter Manager...{TermColors.RESET}")

    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Gmail service not available for filter management. Exiting.{TermColors.RESET}")
        return

    # 1. Get or create necessary labels and map names to IDs
    label_name_to_id = {}
    print(f"{TermColors.STATUS_INFO}Checking for necessary labels...{TermColors.RESET}")
    try:
        results = gmail_service.users().labels().list(userId='me').execute()
        existing_labels = {label['name']: label['id'] for label in results.get('labels', [])}

        for label_name in TARGET_LABELS:
            if label_name in existing_labels:
                label_name_to_id[label_name] = existing_labels[label_name]
                print(f"{TermColors.STATUS_SUCCESS}Found existing label '{label_name}' with ID: {label_name_to_id[label_name]}{TermColors.RESET}")
            else:
                print(f"{TermColors.STATUS_INFO}Label '{label_name}' not found. Creating it...{TermColors.RESET}")
                created_label = gmail_service.users().labels().create(userId='me', body={'name': label_name}).execute()
                label_name_to_id[label_name] = created_label['id']
                print(f"{TermColors.STATUS_SUCCESS}Created label '{label_name}' with ID: {label_name_to_id[label_name]}{TermColors.RESET}")

    except HttpError as error:
        print(f'{TermColors.STATUS_ERROR}An error occurred while getting or creating labels: {error}{TermColors.RESET}')
        return
    
    if len(label_name_to_id) != len(TARGET_LABELS):
         print(f"{TermColors.STATUS_ERROR}Could not find or create all required labels. Cannot proceed with filter creation.{TermColors.RESET}")
         return

    # 2. Create filters
    print(f"\n{TermColors.STATUS_INFO}Creating filters...{TermColors.RESET}")
    created_filter_count = 0

    for filter_def in filter_definitions:
        filter_name = filter_def.get('name', 'Unnamed Filter')
        criteria = filter_def.get('criteria', {})
        action = filter_def.get('action', {})

        # Replace placeholder label IDs with actual IDs
        action_with_ids = {}
        if 'addLabelIds' in action:
            action_with_ids['addLabelIds'] = [
                label_name_to_id.get(label_name) for label_name in action['addLabelIds']
                if label_name in label_name_to_id # Ensure label exists
            ]
        if 'removeLabelIds' in action:
             action_with_ids['removeLabelIds'] = action['removeLabelIds'] # These are standard IDs like 'INBOX'

        filter_body = {
            'criteria': criteria,
            'action': action_with_ids
        }

        print(f"{TermColors.STATUS_INFO}Attempting to create filter: '{filter_name}'...{TermColors.RESET}")
        # print(f"  Body: {json.dumps(filter_body)}") # Debug print

        try:
            created_filter = gmail_service.users().settings().filters().create(userId='me', body=filter_body).execute()
            created_filter_count += 1
            print(f"{TermColors.STATUS_SUCCESS}Successfully created filter: '{filter_name}' (ID: {created_filter.get('id')}){TermColors.RESET}")

        except HttpError as error:
            # Check if the error is due to a duplicate filter
            if error.resp.status == 409: # 409 Conflict usually indicates a duplicate
                 print(f"{TermColors.YELLOW}Warning: Filter '{filter_name}' likely already exists. Skipping creation.{TermColors.RESET}")
            else:
                print(f'{TermColors.STATUS_ERROR}An error occurred while creating filter "{filter_name}": {error}{TermColors.RESET}')
            # Decide how to handle errors - skip, retry, etc. For now, just report and continue.

    print(f"\n{TermColors.STATUS_SUCCESS}Finished creating filters. Total filters attempted: {len(filter_definitions)}. Total created/found duplicates: {created_filter_count}.{TermColors.RESET}")
    print(f"{TermColors.BOLD}Gmail Filter Manager finished.{TermColors.RESET}")


if __name__ == "__main__":
    print(f"{TermColors.BOLD}Running Gmail Filter Manager Standalone...{TermColors.RESET}")
    standalone_gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, SCOPES)
    if not standalone_gmail_service:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize Gmail service for standalone run. Exiting.{TermColors.RESET}")
        sys.exit(1)
        
    run_filter_management(standalone_gmail_service)
