import os
from openai import OpenAI
from dotenv import load_dotenv

# Import utilities from email_utils
from email_utils import get_gmail_service, TermColors

# Placeholder for importing refactored module functions
from email_triage import run_triage # Import the refactored function
from email_categorize_opportunities import run_opportunity_categorization
from email_draft_reply import run_reply_drafting
from email_plan_cleanup import run_cleanup_planning
from email_execute_cleanup import run_cleanup_execution
from email_archive_unread import run_archive_unread
from email_general_categorizer import run_general_categorization
from email_manage_filters import run_filter_management
# ... other imports will go here

# Load environment variables
load_dotenv(override=True)

# --- Configuration for cli.py ---
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
TOKEN_FILE = os.path.join(SCRIPT_DIR, "token.json")
CREDENTIALS_FILE = os.path.join(SCRIPT_DIR, "credentials.json")

# Define a comprehensive set of scopes that might be needed by any module.
# This ensures the token obtained by cli.py is sufficient.
CLI_SCOPES = [
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.send',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.settings.basic', # For filters
    'https://www.googleapis.com/auth/gmail.labels'          # For labels & filters
]

def display_menu():
    """Displays the main menu options."""
    print(f"\n{TermColors.BOLD}{TermColors.BLUE}--- Email Assistant CLI ---{TermColors.RESET}")
    print("What would you like to do today?")
    print("1. Triage important emails (Identify emails needing response)")
    print("2. Categorize business opportunities")
    print("3. Draft replies to important emails")
    print("4. Plan email cleanup (Identify deletion candidates & unsubscribes)")
    print("5. Execute email cleanup (Interactive unsubscribe & delete)")
    print("6. Archive all unread emails (Inbox Zero)")
    print("7. General categorization & labeling of recent emails")
    print("8. Manage Gmail filters")
    print("0. Exit")
    choice = input("Enter your choice: ")
    return choice

def main():
    """Main function to run the CLI assistant."""
    print(f"{TermColors.STATUS_INFO}Initializing Email Assistant...{TermColors.RESET}")

    # Initialize Gmail Service
    gmail_service = get_gmail_service(TOKEN_FILE, CREDENTIALS_FILE, CLI_SCOPES)
    if not gmail_service:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize Gmail service. Exiting.{TermColors.RESET}")
        return

    # Initialize OpenAI Client
    try:
        openai_client = OpenAI()
        # Test client (optional, but good for early check)
        # openai_client.models.list() 
        print(f"{TermColors.STATUS_SUCCESS}OpenAI client initialized.{TermColors.RESET}")
    except Exception as e:
        print(f"{TermColors.STATUS_ERROR}Failed to initialize OpenAI client: {e}{TermColors.RESET}")
        return

    while True:
        choice = display_menu()
        if choice == '1':
            print(f"\n{TermColors.STATUS_INFO}Starting Email Triage...{TermColors.RESET}")
            try:
                run_triage(gmail_service, openai_client) # Call the imported and refactored function
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during triage: {e}{TermColors.RESET}")
        elif choice == '2':
            print(f"\n{TermColors.STATUS_INFO}Starting Opportunity Categorization...{TermColors.RESET}")
            try:
                run_opportunity_categorization(gmail_service, openai_client)
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during opportunity categorization: {e}{TermColors.RESET}")
        elif choice == '3':
            print(f"\n{TermColors.STATUS_INFO}Starting Reply Drafting...{TermColors.RESET}")
            try:
                run_reply_drafting(gmail_service, openai_client)
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during reply drafting: {e}{TermColors.RESET}")
        elif choice == '4':
            print(f"\n{TermColors.STATUS_INFO}Starting Email Cleanup Planning...{TermColors.RESET}")
            try:
                run_cleanup_planning(gmail_service, openai_client)
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during cleanup planning: {e}{TermColors.RESET}")
        elif choice == '5':
            print(f"\n{TermColors.STATUS_INFO}Starting Email Cleanup Execution...{TermColors.RESET}")
            try:
                run_cleanup_execution(gmail_service) # openai_client not needed by this module
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during cleanup execution: {e}{TermColors.RESET}")
        elif choice == '6':
            print(f"\n{TermColors.STATUS_INFO}Starting Unread Email Archiver...{TermColors.RESET}")
            try:
                run_archive_unread(gmail_service) # openai_client not needed
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during unread email archiving: {e}{TermColors.RESET}")
        elif choice == '7':
            print(f"\n{TermColors.STATUS_INFO}Starting General Email Categorization & Labeling...{TermColors.RESET}")
            try:
                run_general_categorization(gmail_service, openai_client)
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during general categorization: {e}{TermColors.RESET}")
        elif choice == '8':
            print(f"\n{TermColors.STATUS_INFO}Starting Gmail Filter Management...{TermColors.RESET}")
            try:
                run_filter_management(gmail_service) # openai_client not needed
            except Exception as e:
                print(f"{TermColors.STATUS_ERROR}An error occurred during filter management: {e}{TermColors.RESET}")
        elif choice == '0':
            print(f"{TermColors.STATUS_INFO}Exiting Email Assistant. Goodbye!{TermColors.RESET}")
            break
        else:
            print(f"{TermColors.STATUS_ERROR}Invalid choice. Please try again.{TermColors.RESET}")

if __name__ == "__main__":
    main()
