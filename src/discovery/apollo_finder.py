"""
Apollo.io contact discovery.

Uses the mixed_people/search endpoint to find target-role contacts at
a company by domain. Apollo often returns verified emails directly,
so this is the highest-quality source in the pipeline.

API docs: https://apolloio.github.io/apollo-api-docs
Endpoint: POST https://api.apollo.io/api/v1/mixed_people/search
Auth: X-Api-Key header  (set APOLLO_API_KEY in .env)
"""

from typing import Dict, List, Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

APOLLO_BASE = "https://api.apollo.io/api/v1"

# Ordered highest → lowest outreach priority; Apollo filters on these
_TARGET_TITLES = [
    "CRO", "Chief Revenue Officer",
    "VP of Sales", "VP Sales", "Head of Sales", "Director of Sales",
    "VP of Revenue", "Head of Revenue",
    "CEO", "Chief Executive Officer", "Founder", "Co-Founder",
    "CMO", "Chief Marketing Officer",
    "VP of Marketing", "VP Marketing", "Head of Marketing",
    "VP of Growth", "Head of Growth",
    "COO", "Chief Operating Officer",
    "VP of Operations", "Head of Operations",
]


class ApolloFinder:
    def __init__(self, api_key: str):
        self._api_key = api_key
        self._headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
            "X-Api-Key": api_key,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{APOLLO_BASE}{path}",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def find_contacts(self, domain: str) -> List[Dict]:
        """
        Return up to 10 target-role contacts at the given domain,
        sorted by Apollo's relevance score.
        """
        payload = {
            "q_organization_domains": domain,
            "person_titles": _TARGET_TITLES,
            "person_seniorities": ["c_suite", "vp", "director", "owner", "founder"],
            "contact_email_status_v2": ["verified", "likely_to_engage"],
            "page": 1,
            "per_page": 10,
        }
        try:
            data = await self._post("/mixed_people/search", payload)
        except Exception:
            return []

        results = []
        for person in data.get("people") or []:
            email = _best_email(person)
            results.append({
                "first_name": person.get("first_name", ""),
                "last_name": person.get("last_name", ""),
                "name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                "title": person.get("title", ""),
                "email": email or "",
                "linkedin_url": person.get("linkedin_url"),
                "apollo_id": person.get("id"),
                "source": "apollo",
            })
        return results

    async def reveal_email(self, apollo_id: str) -> Optional[str]:
        """
        Call Apollo's people/match to reveal the email for a person
        that was returned without one in the search results.
        Costs one Apollo credit per call — use sparingly.
        """
        try:
            data = await self._post(
                "/people/match",
                {
                    "id": apollo_id,
                    "reveal_personal_emails": False,
                    "reveal_phone_number": False,
                },
            )
            return _best_email(data.get("person") or {})
        except Exception:
            return None


def _best_email(person: dict) -> Optional[str]:
    """Return the highest-confidence email from an Apollo person object."""
    email = person.get("email")
    status = person.get("email_status", "")
    if email and status in ("verified", "likely_to_engage"):
        return email
    for entry in person.get("email_addresses") or []:
        if entry.get("email_status") in ("verified", "likely_to_engage"):
            return entry.get("email")
    # Fall back to any email even without status
    return email or None
