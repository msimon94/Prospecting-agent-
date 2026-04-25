"""
Local activity log — appends one row per sent email to a CSV file.
This replaces HubSpot as the record of what was sent and when.
"""

import csv
from datetime import datetime
from pathlib import Path

from ..signals.base import EmailOutput

DEFAULT_LOG_FILE = ".agent_state/sent_log.csv"

_HEADERS = [
    "sent_at", "first_name", "last_name", "email",
    "title", "company", "subject", "body", "gmail_id",
]


class ActivityLogger:
    def __init__(self, log_file: str = DEFAULT_LOG_FILE):
        self._path = Path(log_file)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        if not self._path.exists():
            self._write_row(_HEADERS)

    def log(self, email_output: EmailOutput, gmail_id: str) -> None:
        c = email_output.contact
        self._write_row([
            datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC"),
            c.first_name,
            c.last_name,
            c.email or "",
            c.title,
            c.company_name,
            email_output.subject,
            email_output.body.replace("\n", " "),
            gmail_id,
        ])

    def already_sent(self, email: str) -> bool:
        """Check the log to avoid re-sending to the same address."""
        if not self._path.exists():
            return False
        with open(self._path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if row.get("email", "").lower() == email.lower():
                    return True
        return False

    def _write_row(self, row: list) -> None:
        with open(self._path, "a", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(row)
