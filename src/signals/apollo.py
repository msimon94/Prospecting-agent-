import httpx
from typing import List
from tenacity import retry, stop_after_attempt, wait_exponential

from .base import CompanySignal, SignalType, SignalPriority

APOLLO_BASE = "https://api.apollo.io/v1"


class ApolloSignalMonitor:
    def __init__(self, api_key: str):
        self._headers = {
            "Content-Type": "application/json",
            "Cache-Control": "no-cache",
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

    async def get_job_change_signals(
        self,
        target_titles: List[str],
        target_industries: List[str],
    ) -> List[CompanySignal]:
        """People who recently started a new role matching our ICP."""
        payload = {
            "page": 1,
            "per_page": 25,
            "person_titles": target_titles or [
                "VP of Sales", "VP Sales", "CRO", "Chief Revenue Officer",
                "Head of Sales", "Director of Sales",
            ],
            "person_seniorities": ["manager", "director", "vp", "c_suite", "owner", "founder"],
            "event_categories": ["job_change"],
            "sort_by_field": "person_job_start_date",
            "sort_ascending": False,
        }
        if target_industries:
            payload["organization_industry_tag_ids"] = target_industries

        data = await self._post("/mixed_people/search", payload)
        signals = []
        for person in data.get("people", []):
            org = person.get("organization") or {}
            domain = org.get("primary_domain", "")
            if not domain:
                continue
            emp_history = person.get("employment_history") or [{}]
            signals.append(
                CompanySignal(
                    id=f"job_change_{person['id']}",
                    signal_type=SignalType.JOB_CHANGE,
                    company_name=org.get("name", ""),
                    company_domain=domain,
                    company_id=org.get("id"),
                    priority=SignalPriority.HIGH,
                    metadata={
                        "person_id": person["id"],
                        "person_name": f"{person.get('first_name', '')} {person.get('last_name', '')}".strip(),
                        "title": person.get("title", ""),
                        "job_start_date": emp_history[0].get("start_date"),
                        "seniority": person.get("seniority"),
                    },
                )
            )
        return signals

    async def get_funding_signals(
        self,
        min_funding_usd: int = 1_000_000,
    ) -> List[CompanySignal]:
        """Companies that recently raised a funding round."""
        payload = {
            "page": 1,
            "per_page": 25,
            "organization_latest_funding_stage_cd": [
                "seed", "series_a", "series_b", "series_c", "series_d",
            ],
            "sort_by_field": "organization_latest_funding_date",
            "sort_ascending": False,
        }
        data = await self._post("/organizations/search", payload)
        signals = []
        for org in data.get("organizations", []):
            amount = org.get("latest_funding_round_amount") or 0
            if amount < min_funding_usd:
                continue
            domain = org.get("primary_domain", "")
            if not domain:
                continue
            signals.append(
                CompanySignal(
                    id=f"funding_{org['id']}",
                    signal_type=SignalType.FUNDING_ROUND,
                    company_name=org.get("name", ""),
                    company_domain=domain,
                    company_id=org.get("id"),
                    priority=SignalPriority.HIGH,
                    metadata={
                        "funding_amount": amount,
                        "funding_stage": org.get("latest_funding_round_type"),
                        "funding_date": org.get("latest_funding_round_date"),
                        "employee_count": org.get("estimated_num_employees"),
                        "industry": org.get("industry"),
                    },
                )
            )
        return signals

    async def get_tech_install_signals(
        self,
        technology_uids: List[str],
    ) -> List[CompanySignal]:
        """Companies currently using a relevant/competitor technology."""
        if not technology_uids:
            return []
        payload = {
            "page": 1,
            "per_page": 25,
            "currently_using_any_of_technology_uids": technology_uids,
            "sort_by_field": "organization_estimated_num_employees",
            "sort_ascending": False,
        }
        data = await self._post("/organizations/search", payload)
        signals = []
        for org in data.get("organizations", []):
            domain = org.get("primary_domain", "")
            if not domain:
                continue
            signals.append(
                CompanySignal(
                    id=f"tech_{org['id']}",
                    signal_type=SignalType.TECH_INSTALL,
                    company_name=org.get("name", ""),
                    company_domain=domain,
                    company_id=org.get("id"),
                    priority=SignalPriority.MEDIUM,
                    metadata={
                        "technologies": [
                            t.get("name") for t in (org.get("current_technologies") or [])
                        ],
                        "employee_count": org.get("estimated_num_employees"),
                        "industry": org.get("industry"),
                    },
                )
            )
        return signals

    async def get_hiring_surge_signals(
        self,
        target_departments: List[str],
        min_open_jobs: int = 5,
    ) -> List[CompanySignal]:
        """Companies aggressively hiring in relevant departments."""
        payload = {
            "page": 1,
            "per_page": 25,
            "organization_job_titles_any_of": target_departments,
            "sort_by_field": "organization_num_current_employees",
            "sort_ascending": False,
        }
        data = await self._post("/organizations/search", payload)
        signals = []
        for org in data.get("organizations", []):
            job_count = org.get("num_jobs") or 0
            if job_count < min_open_jobs:
                continue
            domain = org.get("primary_domain", "")
            if not domain:
                continue
            signals.append(
                CompanySignal(
                    id=f"hiring_{org['id']}",
                    signal_type=SignalType.HIRING_SURGE,
                    company_name=org.get("name", ""),
                    company_domain=domain,
                    company_id=org.get("id"),
                    priority=SignalPriority.MEDIUM,
                    metadata={
                        "open_positions": job_count,
                        "departments": target_departments,
                        "employee_count": org.get("estimated_num_employees"),
                        "industry": org.get("industry"),
                    },
                )
            )
        return signals
