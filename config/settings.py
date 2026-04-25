import os
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
        # Hunter.io — recommended for reliable email discovery
        "hunter_api_key": os.getenv("HUNTER_API_KEY"),
        # Optional Slack notifications
        "slack_webhook_url": os.getenv("SLACK_WEBHOOK_URL"),
        # Agent identity
        "sender_name": os.getenv("SENDER_NAME", ""),
        # Behaviour
        "max_emails_per_run": int(os.getenv("MAX_EMAILS_PER_RUN", "25")),
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
        # How many days before re-contacting a company (default 90)
        "recontact_ttl_days": int(os.getenv("RECONTACT_TTL_DAYS", "90")),
        # Local log file
        "log_file": os.getenv("LOG_FILE", ".agent_state/sent_log.csv"),
    }
