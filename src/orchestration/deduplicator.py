import json
import hashlib
from pathlib import Path
from datetime import datetime, timedelta
from typing import List

from ..signals.base import CompanySignal


class SignalDeduplicator:
    """
    File-backed deduplication store. Prevents re-emailing the same
    company+signal combo within the TTL window.
    """

    def __init__(self, state_file: str = ".agent_state/dedup.json", ttl_days: int = 30):
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

    def _key(self, namespace: str, value: str) -> str:
        return hashlib.md5(f"{namespace}:{value}".encode()).hexdigest()

    def _purge_expired(self) -> None:
        cutoff = (datetime.utcnow() - timedelta(days=self.ttl_days)).isoformat()
        self._store = {k: v for k, v in self._store.items() if v > cutoff}

    # ── public API ────────────────────────────────────────────────────────────

    def filter_new(self, signals: List[CompanySignal]) -> List[CompanySignal]:
        """Return only signals not seen within the TTL window, recording them."""
        self._purge_expired()
        new: List[CompanySignal] = []
        for signal in signals:
            key = self._key(signal.signal_type.value, signal.company_domain)
            if key not in self._store:
                new.append(signal)
                self._store[key] = datetime.utcnow().isoformat()
        self._save()
        return new

    def mark_emailed(self, domain: str) -> None:
        key = self._key("emailed", domain)
        self._store[key] = datetime.utcnow().isoformat()
        self._save()

    def already_emailed(self, domain: str) -> bool:
        key = self._key("emailed", domain)
        if key not in self._store:
            return False
        ts = datetime.fromisoformat(self._store[key])
        return datetime.utcnow() - ts < timedelta(days=self.ttl_days)
