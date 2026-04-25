"""
In-memory + file-backed deduplication store.

For list-based outreach we deduplicate on email address so the same
contact is never emailed twice across runs, even if they appear in
multiple imported files.
"""

import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import List

from ..signals.base import Contact


class ContactDeduplicator:
    def __init__(
        self,
        state_file: str = ".agent_state/dedup.json",
        ttl_days: int = 90,
    ):
        self._path = Path(state_file)
        self.ttl_days = ttl_days
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._store: dict = {}
        self._load()

    # ── persistence ───────────────────────────────────────────────────────────

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path) as f:
                self._store = json.load(f)

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._store, f, indent=2)

    # ── helpers ───────────────────────────────────────────────────────────────

    def _key(self, email: str) -> str:
        return hashlib.md5(email.strip().lower().encode()).hexdigest()

    def _purge_expired(self) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=self.ttl_days)).isoformat()
        self._store = {k: v for k, v in self._store.items() if v > cutoff}

    # ── public API ────────────────────────────────────────────────────────────

    def filter_new(self, contacts: List[Contact]) -> List[Contact]:
        """Return contacts not emailed within the TTL window."""
        self._purge_expired()
        new: List[Contact] = []
        for contact in contacts:
            if not contact.email:
                continue
            key = self._key(contact.email)
            if key not in self._store:
                new.append(contact)
        return new

    def mark_sent(self, email: str) -> None:
        key = self._key(email)
        self._store[key] = datetime.utcnow().isoformat()
        self._save()

    def already_sent(self, email: str) -> bool:
        key = self._key(email)
        if key not in self._store:
            return False
        ts = datetime.fromisoformat(self._store[key])
        return datetime.utcnow() - ts < timedelta(days=self.ttl_days)
