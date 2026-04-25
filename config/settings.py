import os
from typing import List
from dotenv import load_dotenv

load_dotenv()


def load_config() -> dict:
    return {
        "apollo_api_key": os.environ["APOLLO_API_KEY"],
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        "hubspot_access_token": os.environ["HUBSPOT_ACCESS_TOKEN"],
        "apify_api_token": os.getenv("APIFY_API_TOKEN"),
        "slack_webhook_url": os.getenv("SLACK_WEBHOOK_URL"),
        "gmail_credentials_file": os.getenv(
            "GMAIL_CREDENTIALS_FILE", "credentials/gmail_credentials.json"
        ),
        "gmail_token_file": os.getenv(
            "GMAIL_TOKEN_FILE", "credentials/gmail_token.json"
        ),
        "sender_name": os.getenv("SENDER_NAME", ""),
        "max_emails_per_run": int(os.getenv("MAX_EMAILS_PER_RUN", "10")),
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
        "target_titles": _parse_list(os.getenv("TARGET_TITLES", "")),
        "target_industries": _parse_list(os.getenv("TARGET_INDUSTRIES", "")),
        "competitor_technologies": _parse_list(
            os.getenv("COMPETITOR_TECHNOLOGIES", "")
        ),
        "hiring_departments": _parse_list(
            os.getenv("HIRING_DEPARTMENTS", "sales,revenue,growth")
        ),
    }


def _parse_list(value: str) -> List[str]:
    if not value:
        return []
    return [v.strip() for v in value.split(",") if v.strip()]
