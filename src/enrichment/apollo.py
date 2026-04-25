import httpx
from typing import List, Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from ..signals.base import Contact, CompanySignal, SignalType

APOLLO_BASE = "https://api.apollo.io/v1"

DEFAULT_TARGET_TITLES = [
    "VP of Sales", "VP Sales", "CRO", "Chief Revenue Officer",
    "Head of Sales", "Director of Sales", "Sales Director",
    "VP of Revenue", "Head of Revenue Operations",
]


class ApolloEnrichmentClient:
    def __init__(self, api_key: str):
        self._headers = {
            "Content-Type": "application/json",
            "X-Api-Key": api_key,
        }

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _post(self, endpoint: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{APOLLO_BASE}{endpoint}",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    async def find_contact(
        self,
        signal: CompanySignal,
        target_titles: Optional[List[str]] = None,
    ) -> Optional[Contact]:
        titles = target_titles or DEFAULT_TARGET_TITLES

        payload = {
            "page": 1,
            "per_page": 5,
            "person_titles": titles,
            "organization_domains": [signal.company_domain],
            "person_seniorities": ["director", "vp", "c_suite", "owner", "founder"],
            "contact_email_status_v2": ["verified"],
        }

        # If the signal already has a specific person, target them directly
        person_id = signal.metadata.get("person_id")
        if signal.signal_type == SignalType.JOB_CHANGE and person_id:
            payload["person_ids"] = [person_id]

        data = await self._post("/mixed_people/search", payload)
        people = data.get("people") or []
        if not people:
            return None

        person = people[0]
        email = self._extract_email(person)

        if not email:
            email = await self._reveal_email(person["id"])

        if not email:
            return None

        org = person.get("organization") or {}
        return Contact(
            id=person["id"],
            first_name=person.get("first_name", ""),
            last_name=person.get("last_name", ""),
            email=email,
            title=person.get("title", ""),
            company_name=signal.company_name,
            company_domain=signal.company_domain,
            linkedin_url=person.get("linkedin_url"),
            metadata={
                "city": person.get("city"),
                "state": person.get("state"),
                "employee_count": org.get("estimated_num_employees"),
                "industry": org.get("industry"),
                "seniority": person.get("seniority"),
            },
        )

    def _extract_email(self, person: dict) -> Optional[str]:
        email = person.get("email")
        if email and person.get("email_status") == "verified":
            return email
        for entry in person.get("email_addresses") or []:
            if entry.get("email_status") == "verified":
                return entry.get("email")
        return None

    async def _reveal_email(self, person_id: str) -> Optional[str]:
        try:
            data = await self._post(
                "/people/match",
                {"id": person_id, "reveal_personal_emails": False},
            )
            person = data.get("person") or {}
            return self._extract_email(person)
        except Exception:
            return None
