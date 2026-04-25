"""
LeadIQ email enrichment.

Given a person's name + company domain (or LinkedIn URL), LeadIQ returns
a verified work email. Used as the enrichment layer when a contact is
found via Apollo/website/LinkedIn without an email address.

API docs: https://docs.leadiq.com
Endpoint: POST https://api.leadiq.com/graphql  (GraphQL)
Auth:     Authorization: Basic {base64(api_key:)}
          or X-Api-Key: {api_key} depending on your plan tier

Set LEADIQ_API_KEY in .env.
"""

import base64
from typing import Optional

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

LEADIQ_BASE = "https://api.leadiq.com"


class LeadIQEmailFinder:
    def __init__(self, api_key: str):
        self._api_key = api_key
        # LeadIQ uses HTTP Basic auth with the key as the username, empty password
        encoded = base64.b64encode(f"{api_key}:".encode()).decode()
        self._headers = {
            "Content-Type": "application/json",
            "Authorization": f"Basic {encoded}",
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _graphql(self, query: str, variables: dict) -> dict:
        async with httpx.AsyncClient(timeout=25) as client:
            resp = await client.post(
                f"{LEADIQ_BASE}/graphql",
                json={"query": query, "variables": variables},
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def find_email(
        self,
        first_name: str,
        last_name: str,
        domain: str,
        linkedin_url: Optional[str] = None,
    ) -> Optional[str]:
        """
        Enrich a contact and return their verified work email, or None.

        LeadIQ's findEmailAddress mutation accepts either a LinkedIn URL
        (most accurate) or first name + last name + company domain.
        """
        if not (first_name and last_name) and not linkedin_url:
            return None

        # Prefer LinkedIn URL when available — higher accuracy
        if linkedin_url:
            return await self._find_by_linkedin(linkedin_url)

        return await self._find_by_name(first_name, last_name, domain)

    async def _find_by_linkedin(self, linkedin_url: str) -> Optional[str]:
        query = """
        mutation FindEmail($input: FindEmailInput!) {
            findEmailAddress(input: $input) {
                emailAddress
                confidence
            }
        }
        """
        variables = {"input": {"linkedinUrl": linkedin_url}}
        try:
            data = await self._graphql(query, variables)
            result = (data.get("data") or {}).get("findEmailAddress") or {}
            email = result.get("emailAddress")
            confidence = result.get("confidence") or 0
            return email if email and confidence >= 50 else None
        except Exception:
            return None

    async def _find_by_name(
        self, first_name: str, last_name: str, domain: str
    ) -> Optional[str]:
        query = """
        mutation FindEmail($input: FindEmailInput!) {
            findEmailAddress(input: $input) {
                emailAddress
                confidence
            }
        }
        """
        variables = {
            "input": {
                "firstName": first_name,
                "lastName": last_name,
                "companyDomain": domain,
            }
        }
        try:
            data = await self._graphql(query, variables)
            result = (data.get("data") or {}).get("findEmailAddress") or {}
            email = result.get("emailAddress")
            confidence = result.get("confidence") or 0
            return email if email and confidence >= 50 else None
        except Exception:
            return None
