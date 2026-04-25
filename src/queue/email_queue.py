"""
SQLite-backed email queue.

Emails land here with status='pending' when the agent runs in queue mode
(python main.py run --queue). The dashboard reads, edits, and approves
or rejects them without touching any email until the user confirms.

Status lifecycle:
  pending  →  sent      (approved from dashboard)
  pending  →  rejected  (rejected from dashboard)
"""

import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional

from ..signals.base import EmailOutput

DEFAULT_DB = ".agent_state/email_queue.db"

_DDL = """
CREATE TABLE IF NOT EXISTS email_queue (
    id              TEXT PRIMARY KEY,
    status          TEXT NOT NULL DEFAULT 'pending',
    created_at      TEXT NOT NULL,
    updated_at      TEXT NOT NULL,

    -- contact
    first_name      TEXT,
    last_name       TEXT,
    email           TEXT,
    title           TEXT,
    company_name    TEXT,
    company_domain  TEXT,
    linkedin_url    TEXT,
    source          TEXT,

    -- generated email
    subject         TEXT,
    body            TEXT,

    -- company context (for display only)
    industry        TEXT,
    employee_count  INTEGER,
    context         TEXT,

    -- populated after send
    gmail_id        TEXT,
    sent_at         TEXT,
    rejection_reason TEXT
);
"""


class EmailQueue:
    def __init__(self, db_path: str = DEFAULT_DB):
        self._path = db_path
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._init()

    # ── setup ─────────────────────────────────────────────────────────────────

    def _conn(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def _init(self) -> None:
        with self._conn() as c:
            c.execute(_DDL)

    # ── writes ────────────────────────────────────────────────────────────────

    def enqueue(self, email_output: EmailOutput) -> str:
        """Insert a generated email as pending. Returns the row id."""
        row_id = str(uuid.uuid4())
        now = _now()
        ct = email_output.contact
        m = ct.metadata

        with self._conn() as c:
            c.execute(
                """
                INSERT INTO email_queue (
                    id, status, created_at, updated_at,
                    first_name, last_name, email, title,
                    company_name, company_domain, linkedin_url, source,
                    subject, body,
                    industry, employee_count, context
                ) VALUES (
                    ?,?,?,?,  ?,?,?,?,  ?,?,?,?,  ?,?,  ?,?,?
                )
                """,
                (
                    row_id, "pending", now, now,
                    ct.first_name, ct.last_name, ct.email or "", ct.title,
                    ct.company_name, ct.company_domain, ct.linkedin_url, ct.source,
                    email_output.subject, email_output.body,
                    m.get("industry"), m.get("employee_count"), m.get("context"),
                ),
            )
        return row_id

    def mark_sent(self, row_id: str, gmail_id: str) -> None:
        now = _now()
        with self._conn() as c:
            c.execute(
                "UPDATE email_queue SET status='sent', gmail_id=?, sent_at=?, updated_at=? WHERE id=?",
                (gmail_id, now, now, row_id),
            )

    def mark_rejected(self, row_id: str, reason: str = "") -> None:
        now = _now()
        with self._conn() as c:
            c.execute(
                "UPDATE email_queue SET status='rejected', rejection_reason=?, updated_at=? WHERE id=?",
                (reason, now, row_id),
            )

    def update_draft(self, row_id: str, subject: str, body: str) -> None:
        with self._conn() as c:
            c.execute(
                "UPDATE email_queue SET subject=?, body=?, updated_at=? WHERE id=?",
                (subject, body, _now(), row_id),
            )

    # ── reads ─────────────────────────────────────────────────────────────────

    def get(self, row_id: str) -> Optional[Dict]:
        with self._conn() as c:
            row = c.execute(
                "SELECT * FROM email_queue WHERE id=?", (row_id,)
            ).fetchone()
        return dict(row) if row else None

    def list_by_status(self, status: str = "pending") -> List[Dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM email_queue WHERE status=? ORDER BY created_at DESC",
                (status,),
            ).fetchall()
        return [dict(r) for r in rows]

    def list_all(self) -> List[Dict]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT * FROM email_queue ORDER BY created_at DESC"
            ).fetchall()
        return [dict(r) for r in rows]

    def counts(self) -> Dict[str, int]:
        with self._conn() as c:
            rows = c.execute(
                "SELECT status, COUNT(*) AS n FROM email_queue GROUP BY status"
            ).fetchall()
        return {r["status"]: r["n"] for r in rows}


def _now() -> str:
    return datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
