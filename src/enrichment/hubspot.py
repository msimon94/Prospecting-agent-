import httpx
from datetime import datetime
from typing import Optional
from tenacity import retry, stop_after_attempt, wait_exponential

from ..signals.base import Contact, CompanySignal, EnrichedContact

HUBSPOT_BASE = "https://api.hubapi.com"


class HubSpotClient:
    def __init__(self, access_token: str):
        self._headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        }

    # ── HTTP helpers ──────────────────────────────────────────────────────────

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _get(self, path: str, params: Optional[dict] = None) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(
                f"{HUBSPOT_BASE}{path}",
                headers=self._headers,
                params=params or {},
            )
            resp.raise_for_status()
            return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _post(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{HUBSPOT_BASE}{path}",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=2, max=10))
    async def _patch(self, path: str, payload: dict) -> dict:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.patch(
                f"{HUBSPOT_BASE}{path}",
                json=payload,
                headers=self._headers,
            )
            resp.raise_for_status()
            return resp.json()

    # ── CRM lookups ───────────────────────────────────────────────────────────

    async def find_contact_by_email(self, email: str) -> Optional[dict]:
        payload = {
            "filterGroups": [
                {
                    "filters": [
                        {"propertyName": "email", "operator": "EQ", "value": email}
                    ]
                }
            ],
            "properties": [
                "email", "firstname", "lastname",
                "hs_last_contacted", "dealstage",
            ],
        }
        try:
            data = await self._post("/crm/v3/objects/contacts/search", payload)
            results = data.get("results") or []
            return results[0] if results else None
        except Exception:
            return None

    async def has_active_deal(self, contact_id: str) -> bool:
        try:
            data = await self._get(
                f"/crm/v3/objects/contacts/{contact_id}/associations/deals"
            )
            return bool(data.get("results"))
        except Exception:
            return False

    # ── Enrichment entry point ────────────────────────────────────────────────

    async def enrich_contact(
        self, contact: Contact, signal: CompanySignal
    ) -> EnrichedContact:
        record = await self.find_contact_by_email(contact.email)

        hubspot_id: Optional[str] = None
        in_active_deal = False
        last_contacted: Optional[datetime] = None

        if record:
            hubspot_id = record["id"]
            props = record.get("properties") or {}
            ts_str = props.get("hs_last_contacted")
            if ts_str:
                try:
                    last_contacted = datetime.fromtimestamp(int(ts_str) / 1000)
                except (ValueError, TypeError):
                    pass
            in_active_deal = await self.has_active_deal(hubspot_id)

        return EnrichedContact(
            contact=contact,
            signal=signal,
            hubspot_id=hubspot_id,
            in_active_deal=in_active_deal,
            last_contacted=last_contacted,
        )

    # ── Write operations ──────────────────────────────────────────────────────

    async def upsert_contact(self, contact: Contact) -> str:
        props = {
            "email": contact.email,
            "firstname": contact.first_name,
            "lastname": contact.last_name,
            "jobtitle": contact.title,
            "company": contact.company_name,
            "website": f"https://{contact.company_domain}",
        }
        existing = await self.find_contact_by_email(contact.email)
        if existing:
            await self._patch(
                f"/crm/v3/objects/contacts/{existing['id']}",
                {"properties": props},
            )
            return existing["id"]
        data = await self._post("/crm/v3/objects/contacts", {"properties": props})
        return data["id"]

    async def log_email_activity(
        self,
        contact_id: str,
        subject: str,
        body: str,
        signal_type: str,
    ) -> None:
        note = (
            f"[AI Prospecting Agent]\n"
            f"Signal: {signal_type}\n\n"
            f"Subject: {subject}\n\n"
            f"{body}"
        )
        payload = {
            "properties": {
                "hs_note_body": note,
                "hs_timestamp": str(int(datetime.utcnow().timestamp() * 1000)),
            },
            "associations": [
                {
                    "to": {"id": contact_id},
                    "types": [
                        {
                            "associationCategory": "HUBSPOT_DEFINED",
                            "associationTypeId": 202,
                        }
                    ],
                }
            ],
        }
        await self._post("/crm/v3/objects/notes", payload)
