import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


def load_config() -> dict:
    return {
        # Required
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        # Gmail OAuth
        "gmail_credentials_file": os.getenv(
            "GMAIL_CREDENTIALS_FILE", "credentials/gmail_credentials.json"
        ),
        "gmail_token_file": os.getenv(
            "GMAIL_TOKEN_FILE", "credentials/gmail_token.json"
        ),
        # Optional notifications
        "slack_webhook_url": os.getenv("SLACK_WEBHOOK_URL"),
        # Agent identity
        "sender_name": os.getenv("SENDER_NAME", ""),
        # Behavior
        "max_emails_per_run": int(os.getenv("MAX_EMAILS_PER_RUN", "50")),
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
        # Local log file
        "log_file": os.getenv("LOG_FILE", ".agent_state/sent_log.csv"),
    }


def _parse_list(value: str) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]
