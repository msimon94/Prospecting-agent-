import asyncio
import httpx
from typing import Optional

APIFY_BASE = "https://api.apify.com/v2"
LINKEDIN_ACTOR = "curious_coder/linkedin-profile-scraper"


class ApifyLinkedInScraper:
    """Optionally enriches a contact with LinkedIn profile data via Apify."""

    def __init__(self, api_token: str):
        self._token = api_token

    async def get_profile(self, linkedin_url: str) -> Optional[dict]:
        if not linkedin_url or not self._token:
            return None
        try:
            run_id = await self._start_run(linkedin_url)
            return await self._poll_results(run_id)
        except Exception:
            return None

    async def _start_run(self, linkedin_url: str) -> str:
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.post(
                f"{APIFY_BASE}/acts/{LINKEDIN_ACTOR}/runs",
                params={"token": self._token},
                json={
                    "startUrls": [{"url": linkedin_url}],
                    "proxy": {"useApifyProxy": True},
                },
            )
            resp.raise_for_status()
            return resp.json()["data"]["id"]

    async def _poll_results(
        self, run_id: str, max_seconds: int = 90
    ) -> Optional[dict]:
        for _ in range(max_seconds // 5):
            await asyncio.sleep(5)
            async with httpx.AsyncClient(timeout=15) as client:
                status_resp = await client.get(
                    f"{APIFY_BASE}/actor-runs/{run_id}",
                    params={"token": self._token},
                )
                status = status_resp.json().get("data", {}).get("status")
                if status == "SUCCEEDED":
                    items_resp = await client.get(
                        f"{APIFY_BASE}/actor-runs/{run_id}/dataset/items",
                        params={"token": self._token},
                    )
                    items = items_resp.json()
                    return items[0] if items else None
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    return None
        return None
