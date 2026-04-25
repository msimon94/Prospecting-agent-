"""
Finds email addresses for discovered contacts using Hunter.io.

Hunter.io free tier: 25 searches/month.
Plans start at $49/month for 500 searches.
Sign up at https://hunter.io to get an API key.

Two endpoints used:
  /domain-search  — returns all verified emails found for a domain
  /email-finder   — returns the most likely email for a specific person
"""

from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

HUNTER_BASE = "https://api.hunter.io/v2"

# Title keywords that indicate a target role
_TARGET_KEYWORDS = {
    "cro", "chief revenue", "vp", "vice president",
    "ceo", "chief executive", "coo", "chief operating",
    "cmo", "chief marketing", "head of", "director",
    "founder", "co-founder", "revenue", "growth",
    "sales", "marketing", "operations",
}


class HunterEmailFinder:
    def __init__(self, api_key: str):
        self._key = api_key

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _get(self, path: str, params: dict) -> dict:
        params["api_key"] = self._key
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(f"{HUNTER_BASE}{path}", params=params)
            resp.raise_for_status()
            return resp.json()

    async def domain_search(self, domain: str) -> List[Dict]:
        """Return all emails Hunter has for the domain, filtered to target roles."""
        try:
            data = await self._get(
                "/domain-search",
                {"domain": domain, "limit": 10, "seniority": "senior,executive,management"},
            )
            emails = (data.get("data") or {}).get("emails") or []
            results = []
            for e in emails:
                addr = e.get("value")
                if not addr:
                    continue
                title = e.get("position") or ""
                if not title or _is_target_role(title):
                    results.append({
                        "email": addr,
                        "first_name": e.get("first_name") or "",
                        "last_name": e.get("last_name") or "",
                        "title": title,
                        "confidence": e.get("confidence") or 0,
                        "linkedin_url": e.get("linkedin") or None,
                        "source": "hunter",
                    })
            return results
        except Exception:
            return []

    async def find_email(
        self, domain: str, first_name: str, last_name: str
    ) -> Optional[str]:
        """Best-guess email for a specific person. Returns None if score < 50."""
        if not first_name or not last_name:
            return None
        try:
            data = await self._get(
                "/email-finder",
                {"domain": domain, "first_name": first_name, "last_name": last_name},
            )
            result = data.get("data") or {}
            email = result.get("email")
            score = result.get("score") or 0
            return email if email and score >= 50 else None
        except Exception:
            return None


def _is_target_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _TARGET_KEYWORDS)
