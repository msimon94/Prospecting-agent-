import os
from dotenv import load_dotenv

load_dotenv()


def load_config() -> dict:
    return {
        # ── Required ──────────────────────────────────────────────────────────
        "anthropic_api_key": os.environ["ANTHROPIC_API_KEY"],
        # ── Gmail OAuth ───────────────────────────────────────────────────────
        "gmail_credentials_file": os.getenv(
            "GMAIL_CREDENTIALS_FILE", "credentials/gmail_credentials.json"
        ),
        "gmail_token_file": os.getenv(
            "GMAIL_TOKEN_FILE", "credentials/gmail_token.json"
        ),
        # ── Apollo.io — primary contact discovery ─────────────────────────────
        # Get your API key at: https://app.apollo.io/settings/integrations/api
        "apollo_api_key": os.getenv("APOLLO_API_KEY"),
        # ── LeadIQ — email enrichment ─────────────────────────────────────────
        # Get your API key at: https://app.leadiq.com/settings/api
        "leadiq_api_key": os.getenv("LEADIQ_API_KEY"),
        # ── Optional Slack notifications ──────────────────────────────────────
        "slack_webhook_url": os.getenv("SLACK_WEBHOOK_URL"),
        # ── Agent identity ────────────────────────────────────────────────────
        "sender_name": os.getenv("SENDER_NAME", ""),
        # ── Behaviour ─────────────────────────────────────────────────────────
        "max_emails_per_run": int(os.getenv("MAX_EMAILS_PER_RUN", "25")),
        "dry_run": os.getenv("DRY_RUN", "false").lower() == "true",
        "recontact_ttl_days": int(os.getenv("RECONTACT_TTL_DAYS", "90")),
        # ── Logging ───────────────────────────────────────────────────────────
        "log_file": os.getenv("LOG_FILE", ".agent_state/sent_log.csv"),
        # ── Queue (dashboard review mode) ─────────────────────────────────────
        "queue_db": os.getenv("QUEUE_DB", ".agent_state/email_queue.db"),
    }
