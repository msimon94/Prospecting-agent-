"""
File-backed deduplication store keyed on company domain.

Prevents re-processing the same company across multiple runs.
TTL defaults to 90 days — after that a company is eligible again.
"""

import hashlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from ..signals.base import Company


class CompanyDeduplicator:
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

    def _load(self) -> None:
        if self._path.exists():
            with open(self._path) as f:
                self._store = json.load(f)

    def _save(self) -> None:
        with open(self._path, "w") as f:
            json.dump(self._store, f, indent=2)

    def _key(self, domain: str) -> str:
        return hashlib.md5(domain.strip().lower().encode()).hexdigest()

    def _purge_expired(self) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=self.ttl_days)).isoformat()
        self._store = {k: v for k, v in self._store.items() if v > cutoff}

    def filter_new(self, companies: List[Company]) -> List[Company]:
        """Return companies not yet processed within the TTL window."""
        self._purge_expired()
        return [c for c in companies if self._key(c.domain) not in self._store]

    def mark_processed(self, domain: str) -> None:
        self._store[self._key(domain)] = datetime.utcnow().isoformat()
        self._save()

    def already_processed(self, domain: str) -> bool:
        key = self._key(domain)
        if key not in self._store:
            return False
        ts = datetime.fromisoformat(self._store[key])
        return datetime.utcnow() - ts < timedelta(days=self.ttl_days)
