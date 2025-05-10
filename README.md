# HelixMail

![HelixMail Logo](logo.png)

HelixMail is an email management suite for Gmail. It provides a suite of Python scripts to help manage your Gmail inbox using AI-powered analysis and automation. It leverages OpenAI's GPT models for tasks like identifying important emails, categorizing messages, and assisting with cleanup, while using the Gmail API for direct inbox interaction.

A new **unified command-line interface (`cli.py`)** is now available to provide a guided, Q&A style experience for accessing the suite's functionalities.

![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![OpenAI](https://img.shields.io/badge/AI-OpenAI%20GPT-purple)
![Gmail API](https://img.shields.io/badge/API-Gmail-red)

## 🌟 Core Features

*   **Unified CLI (`cli.py`):** A single entry point to access all email management tools through an interactive menu.
*   **Gmail Integration:** Directly interacts with your Gmail account using the Gmail API.
*   **Intelligent Email Triage (`email_triage.py`):** Identifies emails requiring your attention/response from a user-defined recent period. Now includes an option to scan both read and unread emails, and generates a detailed Markdown report with clear statuses (Urgent, Needs Response, Already Responded, No Response Needed).
*   **Opportunity Categorization (`email_categorize_opportunities.py`):** Categorizes emails to find potential business opportunities (sponsorships, inquiries).
*   **AI-Assisted Reply Drafting (`email_draft_reply.py`):** Helps generate draft responses to important emails identified by the triage script.
*   **Email Cleanup Planning (`email_plan_cleanup.py`):**
    *   Analyzes emails (e.g., older emails or recent ones) to suggest candidates for deletion.
    *   Extracts `List-Unsubscribe` information from email headers.
*   **Interactive Cleanup Execution (`email_execute_cleanup.py`):**
    *   Allows interactive review of cleanup plan.
    *   Assists with unsubscribing via `mailto:` links or visiting HTTP unsubscribe links.
    *   Moves selected emails to trash.
*   **Inbox Zero Archiver (`email_archive_unread.py`):** Marks all unread emails in the inbox as read and moves them to a specified folder (default: 'Old Stuff') to help achieve a clean slate.
*   **General AI Categorization & Labeling (`email_general_categorizer.py`):**
    *   Categorizes recent emails into user-defined general categories using AI.
    *   Automatically creates and applies corresponding Gmail labels.
*   **Gmail Filter Management (`email_manage_filters.py`):**
    *   Programmatically creates Gmail filters based on defined rules (sender, subject, keywords) to automatically label incoming emails.
*   **Modular Utilities (`email_utils.py`):** Centralized functions for Gmail service authentication (now with improved scope handling), sending emails, and terminal colorization.
*   **Configuration:** Uses a `.env` file for API keys and has script-specific configurations for timeframes, labels, etc.

## 📋 Scripts Overview

The system consists of the following Python scripts located in the `email-agents` directory. While each script can still be run standalone, their functionalities are now also accessible via the main `cli.py` script.

1.  **`cli.py`**:
    *   **Purpose:** Provides a unified, interactive command-line interface to access all other script functionalities.
    *   **Features:** Presents a menu of options, initializes shared resources (Gmail service, OpenAI client), and calls the appropriate functions in other modules based on user selection.

2.  **`email_utils.py`**:
    *   **Purpose:** A utility module providing shared functions for Gmail API authentication (`get_gmail_service` - improved scope handling), sending emails (`send_email`), and terminal color formatting (`TermColors`). Not run directly.

3.  **`email_triage.py`**:
    *   **Purpose:** Identifies important emails needing a response.
    *   **Features:** Prompts for lookback period (days/hours), analyzes primary inbox emails (optionally including read emails) using AI. Checks against sent emails (lookback period now aligns with incoming scan) to identify previously responded messages.
    *   **Output:** `needs_response_report.md` (Markdown format with detailed statuses), `needs_response_emails.json` (for drafting replies), `all_analyzed_emails.json` (includes all analyzed emails).

4.  **`email_categorize_opportunities.py`**:
    *   **Purpose:** Scans recent emails to identify and categorize business opportunities.
    *   **Features:** Uses AI for multi-stage classification (sponsorship, inquiry, other) and report generation.
    *   **Output:** `categorized_emails.json`, `opportunity_report.txt`.

5.  **`email_draft_reply.py`**:
    *   **Purpose:** Assists in drafting replies to emails identified by `email_triage.py`.
    *   **Features:** Reads `needs_response_emails.json`, generates AI draft responses, allows user to review, edit, and send.
    *   **Output:** `response_history.json`.

6.  **`email_plan_cleanup.py`**:
    *   **Purpose:** Analyzes emails to create a plan for deletion and identify unsubscribe options.
    *   **Features:** Configurable timeframe, AI analysis for deletion candidacy, extracts `List-Unsubscribe` links.
    *   **Output:** `deletion_plan_report.txt`, `deletion_candidates.json`.

7.  **`email_execute_cleanup.py`**:
    *   **Purpose:** Interactively executes the cleanup plan from `email_plan_cleanup.py`.
    *   **Features:** Prompts user to unsubscribe (mailto/HTTP) and/or delete emails. Colorized terminal output.
    *   **Input:** `deletion_candidates.json`.
    *   **Output:** `cline/action_executor_log.txt`.

8.  **`email_archive_unread.py`**:
    *   **Purpose:** Helps achieve "Inbox Zero" by archiving all unread inbox emails.
    *   **Features:** Finds all unread emails in the inbox, marks them as read, and moves them to a specified label (default: 'Old Stuff', created if it doesn't exist).
    *   **Note:** Processes emails in batches.

9.  **`email_general_categorizer.py`**:
    *   **Purpose:** Categorizes recent emails into general user-defined categories and applies Gmail labels.
    *   **Features:** Fetches recent emails, uses AI for categorization, creates/applies labels.
    *   **Output:** `categorization_report.txt`, `categorized_emails_general.json`.

10. **`email_manage_filters.py`**:
    *   **Purpose:** Programmatically creates filters in your Gmail settings.
    *   **Features:** Uses predefined rules (sender, subject, keywords) to apply labels to incoming emails. Creates labels if they don't exist.
    *   **Note:** Requires `gmail.settings.basic` and `gmail.labels` scopes.

## 🚀 Getting Started

### Prerequisites

*   Python 3.8+
*   OpenAI API Key
*   Google Cloud Project with Gmail API enabled:
    *   Follow Google's documentation to create a project, enable the Gmail API, and download `credentials.json` for a "Desktop app" OAuth 2.0 client. Place this file in the `email-agents` directory.

### Installation

1.  Clone the repository (if you haven't already):
    ```bash
    git clone <your_repo_url> # Replace with your actual repo URL
    cd email-agents
    ```

2.  Create and activate a Python virtual environment:
    ```bash
    python3 -m venv venv
    source venv/bin/activate  # On Windows: venv\Scripts\activate
    ```

3.  Install the required dependencies:
    ```bash
    pip install -r requirements.txt
    ```

4.  Create a `.env` file in the `email-agents` directory with your OpenAI API key:
    ```
    OPENAI_API_KEY=your_openai_api_key_here
    ```

5.  Ensure `credentials.json` (downloaded from Google Cloud Console) is in the `email-agents` directory.

### First Run & Authentication

When you run `cli.py` (or any script that interacts with Gmail) for the first time (or after deleting `token.json`), a browser window will open asking you to log in to your Google account and grant the necessary permissions. After successful authorization, a `token.json` file will be created in the `email-agents` directory. This file stores your access tokens for future runs.

The `cli.py` script requests a comprehensive set of scopes to cover all functionalities. The `email_utils.py` script has been improved to better handle cases where an existing `token.json` might have insufficient scopes, prompting re-authentication when needed.

## 🔍 Usage Examples

*   **Run the Unified Assistant:**
    ```bash
    python cli.py
    ```
    Follow the on-screen menu and prompts.

*   **Run Individual Scripts (as before):**
    ```bash
    python email_triage.py
    python email_plan_cleanup.py
    # etc.
    ```

## 🚀 Recommended Workflow for First-Time Use (and Beyond!)

If you're new to this suite or have a large number of emails to manage, here's a suggested approach using the unified `python cli.py` assistant:

### Phase 1: Initial Inbox Taming

The goal here is to quickly reduce noise and tackle the backlog.

1.  **Optional Fresh Start: Archive Old Unread Emails**
    *   **Action:** Choose option `6. Archive all unread emails (Inbox Zero)` from the `cli.py` menu.
    *   **Purpose:** If you have many old, unread emails, this moves them to an 'Old Stuff' folder, giving you a cleaner immediate view.
    *   **Note:** Be sure you're comfortable with this bulk action.

2.  **Major Cleanup: Plan and Execute**
    *   **Action (Plan):** Choose option `4. Plan email cleanup`.
        *   When prompted, consider a **long lookback period** (e.g., emails older than 90, 180, or even 365 days).
        *   Process a **larger batch of emails** (e.g., 200-500).
    *   **Review:** Carefully check the generated `deletion_plan_report.txt`.
    *   **Action (Execute):** Choose option `5. Execute email cleanup`.
        *   Interactively unsubscribe from unwanted senders and delete emails based on the plan. This is key to reducing future clutter.

3.  **Triage Recent Important Communications**
    *   **Action:** Choose option `1. Triage important emails`.
        *   Use a shorter lookback (e.g., last 7-30 days).
        *   Decide if you want to include read emails.
    *   **Review:** Check the `needs_response_report.md`.
    *   **Action (Optional):** If urgent items are found, use option `3. Draft replies to important emails`.

### Phase 2: Organizing and Setting Up Automation

With the major clutter reduced, let's organize what's left and prepare for the future.

4.  **Categorize and Label Recent Emails**
    *   **Action:** Choose option `7. General categorization & labeling of recent emails`.
    *   **Purpose:** Applies labels like "Work," "Personal," etc., to your recent emails, helping with organization.

5.  **Automate Future Organization: Set Up Filters**
    *   **Action:** Choose option `8. Manage Gmail filters`.
    *   **Purpose:** Creates Gmail filters to automatically handle and label new incoming emails.
    *   **Note:** Review and customize the filter definitions in `email_manage_filters.py` beforehand for best results. You might be prompted to re-authenticate if this is the first time granting filter management permissions.

### Phase 3: Specialized and Ongoing Management

6.  **Find Business Opportunities (If Applicable)**
    *   **Action:** Choose option `2. Categorize business opportunities`.
    *   **Purpose:** If you receive business-related inquiries, run this periodically.

### Ongoing Regular Workflow

*   **Daily/Regularly:**
    *   `1. Triage important emails` (short lookback, e.g., 24-48 hours).
    *   `3. Draft replies to important emails`.
*   **Periodically (e.g., Weekly/Monthly):**
    *   `4. Plan email cleanup` & `5. Execute email cleanup` (moderate lookback).
    *   `7. General categorization & labeling of recent emails`.
    *   Review/update filters via `8. Manage Gmail filters` as needed.

### Key Considerations

*   **Review AI Suggestions:** Always double-check AI-generated suggestions, especially for deletions or important categorizations.
*   **Customization:** Advanced users can modify constants and AI prompts within the individual Python scripts for tailored behavior.
*   **Authentication:** The `cli.py` and `email_utils.py` aim to handle authentication scopes smoothly, but re-authentication might occasionally be needed if new permissions are required by a specific module.

## ⚙️ Configuration

*   **API Keys:** `OPENAI_API_KEY` in `.env`.
*   **Gmail Credentials:** `credentials.json`.
*   **Script-Specific Constants:** Many scripts have constants at the top (e.g., `TARGET_LABEL_NAME` in `email_archive_unread.py`, filter rules in `email_manage_filters.py`) that you can modify to change their behavior.
*   **AI Prompts:** The prompts used for AI analysis are embedded within the respective scripts and can be customized.

## 📡 Using Local LLMs for Sensitive Data

The original project included a note about local LLMs. While the current scripts are configured for OpenAI, the principle of modifying the client creation and API calls would still apply if you wish to adapt them for a local LLM. This would involve replacing `client = OpenAI()` and the `client.chat.completions.create(...)` calls with your local LLM's specific SDK.

## 📁 Output Files

The system generates several output files, typically in the script's directory or a `cline/` subdirectory:

*   `needs_response_report.md` (Markdown triage report)
*   `needs_response_emails.json` (emails flagged for response, used by draft reply script)
*   `all_analyzed_emails.json` (includes all emails analyzed by the triage script)
*   `categorized_emails.json`, `opportunity_report.txt` (from `email_categorize_opportunities.py`)
*   `response_history.json` (from `email_draft_reply.py`)
*   `deletion_plan_report.txt`, `deletion_candidates.json` (from `email_plan_cleanup.py`)
*   `cline/action_executor_log.txt` (from `email_execute_cleanup.py`)
*   `categorization_report.txt`, `categorized_emails_general.json` (from `email_general_categorizer.py`)
*   `token.json` (stores Google API access tokens)

## 🛡️ Security

*   API keys are stored in `.env` (which should be in `.gitignore`).
*   `credentials.json` and `token.json` contain sensitive Google API access information and should also be in `.gitignore` and not committed to public repositories.
*   Be mindful of the permissions (scopes) you grant to the application.

## 🤝 Contributing

Contributions are welcome! Feel free to submit issues or pull requests if you have ideas for improvements.

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 🙏 Acknowledgements

*   🙏 Based on a tutorial by AllAboutAI-YT.
*   🙏 OpenAI for providing the GPT models.
*   🙏 Google for the Gmail API.
