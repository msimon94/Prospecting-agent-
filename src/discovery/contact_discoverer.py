"""
Contact discovery pipeline.

For each company it runs three sources in parallel, then picks the
single best contact based on role priority + email availability:

  Source A — Hunter.io domain search (emails + names + titles)
  Source B — Company website team/leadership page scraping
  Source C — LinkedIn profile search via DuckDuckGo

Role priority order (lower index = higher priority):
  CRO → VP Sales → CEO → CMO → VP Revenue → VP Growth → COO / Ops
"""

import asyncio
import re
from typing import Dict, List, Optional, Tuple

from ..signals.base import Company, Contact
from .web_scraper import WebScraper
from .linkedin_finder import LinkedInFinder
from .email_finder import HunterEmailFinder

# Ordered from highest to lowest outreach priority
_ROLE_PRIORITY: List[str] = [
    "chief revenue officer", "cro",
    "vp of sales", "vp sales", "head of sales",
    "vp revenue", "vp of revenue", "head of revenue",
    "chief executive officer", "ceo",
    "chief marketing officer", "cmo",
    "vp of marketing", "vp marketing", "head of marketing",
    "revenue operations", "revops",
    "vp of growth", "vp growth", "head of growth",
    "chief operating officer", "coo",
    "vp of operations", "vp operations", "head of operations",
    "director of sales", "sales director",
    "director of marketing",
    "founder", "co-founder",
]

_TARGET_KEYWORDS = {
    "cro", "chief revenue", "chief executive", "ceo",
    "chief marketing", "cmo", "chief operating", "coo",
    "vp", "vice president", "head of", "director",
    "sales", "revenue", "growth", "marketing",
    "operations", "founder",
}


class ContactDiscoverer:
    def __init__(self, hunter_api_key: Optional[str] = None):
        self._scraper = WebScraper()
        self._linkedin = LinkedInFinder()
        self._hunter = HunterEmailFinder(hunter_api_key) if hunter_api_key else None

    async def discover(self, company: Company) -> Optional[Contact]:
        """
        Run all three discovery sources concurrently, merge results,
        pick the highest-priority contact that has (or can get) an email.
        """
        # Run sources concurrently
        hunter_task = (
            self._hunter.domain_search(company.domain)
            if self._hunter
            else asyncio.coroutine(lambda: [])()
        )
        web_task = self._scraper.find_team_members(company.domain)
        linkedin_task = self._linkedin.find_profiles(company.name, company.domain)

        hunter_results, web_results, linkedin_results = await asyncio.gather(
            hunter_task, web_task, linkedin_task, return_exceptions=True
        )

        candidates: List[Dict] = []

        # Hunter results already have emails
        if isinstance(hunter_results, list):
            for r in hunter_results:
                # Normalise to unified dict shape
                name = f"{r.get('first_name', '')} {r.get('last_name', '')}".strip()
                candidates.append({
                    "name": name,
                    "first_name": r.get("first_name", ""),
                    "last_name": r.get("last_name", ""),
                    "title": r.get("title", ""),
                    "email": r.get("email", ""),
                    "linkedin_url": r.get("linkedin_url"),
                    "source": "hunter",
                })

        # Website / LinkedIn results — need email looked up separately
        for results, src in (
            (web_results, "website"),
            (linkedin_results, "linkedin_search"),
        ):
            if isinstance(results, list):
                for r in results:
                    r = dict(r)
                    r.setdefault("source", src)
                    if "first_name" not in r:
                        first, last = _split_name(r.get("name", ""))
                        r["first_name"] = first
                        r["last_name"] = last
                    candidates.append(r)

        if not candidates:
            return None

        # Filter to target roles, rank by priority
        ranked = _rank(candidates)
        if not ranked:
            return None

        # Walk ranked list until we find one we can get an email for
        for candidate in ranked:
            email = candidate.get("email", "").strip()

            if not email and self._hunter:
                email = await self._hunter.find_email(
                    company.domain,
                    candidate.get("first_name", ""),
                    candidate.get("last_name", ""),
                ) or ""

            if not email:
                continue  # Can't send without a verified email

            return Contact(
                first_name=candidate.get("first_name", ""),
                last_name=candidate.get("last_name", ""),
                email=email,
                title=candidate.get("title", ""),
                company_name=company.name,
                company_domain=company.domain,
                linkedin_url=candidate.get("linkedin_url"),
                source=candidate.get("source", ""),
                metadata={
                    "industry": company.industry,
                    "employee_count": company.employee_count,
                    "context": company.context,
                },
            )

        return None  # No emailable contact found


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_target_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _TARGET_KEYWORDS)


def _role_score(title: str) -> int:
    """Lower = higher outreach priority."""
    t = title.lower()
    for i, role in enumerate(_ROLE_PRIORITY):
        if role in t:
            return i
    return len(_ROLE_PRIORITY)


def _rank(candidates: List[Dict]) -> List[Dict]:
    filtered = [c for c in candidates if not c.get("title") or _is_target_role(c.get("title", ""))]
    if not filtered:
        filtered = candidates  # If nothing matches, try everyone

    def sort_key(c: Dict) -> Tuple[int, int]:
        role_rank = _role_score(c.get("title", ""))
        has_email = 0 if c.get("email") else 1  # prefer candidates with existing email
        return (role_rank, has_email)

    return sorted(filtered, key=sort_key)


def _split_name(full_name: str) -> Tuple[str, str]:
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])
