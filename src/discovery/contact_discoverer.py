"""
Contact discovery pipeline — three-tier, priority-ordered.

Tier 1  Apollo.io (primary)
        Searches the Apollo database for target-role contacts at the
        company's domain. Returns names, titles, LinkedIn URLs, and
        often emails. Highest accuracy and coverage.

Tier 2  Website scraping + LinkedIn search (fallback)
        Used when Apollo returns nothing (company not in their DB).
        Scrapes the company's team/leadership pages and searches
        DuckDuckGo for LinkedIn profiles of target roles.

Tier 3  LeadIQ email enrichment (email layer)
        For contacts discovered without an email, LeadIQ resolves the
        verified work address from the name + domain (or LinkedIn URL).
        Applied to both Apollo and fallback contacts.

Role priority (lower index = higher outreach priority):
  CRO > VP Sales/Revenue > CEO > CMO > VP Marketing > RevOps >
  VP Growth > COO/Ops > Director of Sales > Founder
"""

import asyncio
from typing import Dict, List, Optional, Tuple

from ..signals.base import Company, Contact
from .apollo_finder import ApolloFinder
from .web_scraper import WebScraper
from .linkedin_finder import LinkedInFinder
from .email_finder import LeadIQEmailFinder

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
    def __init__(
        self,
        apollo_api_key: Optional[str] = None,
        leadiq_api_key: Optional[str] = None,
    ):
        self._apollo = ApolloFinder(apollo_api_key) if apollo_api_key else None
        self._scraper = WebScraper()
        self._linkedin = LinkedInFinder()
        self._leadiq = LeadIQEmailFinder(leadiq_api_key) if leadiq_api_key else None

    async def discover(self, company: Company) -> Optional[Contact]:
        """
        Return the single highest-priority emailable contact at the company,
        or None if no contact with a verified email can be found.
        """
        candidates = await self._gather_candidates(company)
        if not candidates:
            return None

        ranked = _rank(candidates)
        if not ranked:
            return None

        for candidate in ranked:
            email = candidate.get("email", "").strip()

            # Try LeadIQ enrichment when email is missing
            if not email and self._leadiq:
                email = await self._leadiq.find_email(
                    first_name=candidate.get("first_name", ""),
                    last_name=candidate.get("last_name", ""),
                    domain=company.domain,
                    linkedin_url=candidate.get("linkedin_url"),
                ) or ""

            # Apollo reveal as last resort (costs a credit)
            if not email and self._apollo and candidate.get("apollo_id"):
                email = await self._apollo.reveal_email(candidate["apollo_id"]) or ""

            if not email:
                continue

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

        return None

    async def _gather_candidates(self, company: Company) -> List[Dict]:
        """
        Run Apollo first. Fall back to web + LinkedIn only when
        Apollo returns no results for this company.
        """
        # Tier 1: Apollo
        apollo_results: List[Dict] = []
        if self._apollo:
            try:
                apollo_results = await self._apollo.find_contacts(company.domain)
            except Exception:
                apollo_results = []

        if apollo_results:
            return apollo_results

        # Tier 2: web scraping + LinkedIn (concurrent)
        web_task = self._scraper.find_team_members(company.domain)
        linkedin_task = self._linkedin.find_profiles(company.name, company.domain)
        web_results, linkedin_results = await asyncio.gather(
            web_task, linkedin_task, return_exceptions=True
        )

        candidates: List[Dict] = []
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

        return candidates


# ── helpers ───────────────────────────────────────────────────────────────────

def _is_target_role(title: str) -> bool:
    t = title.lower()
    return any(kw in t for kw in _TARGET_KEYWORDS)


def _role_score(title: str) -> int:
    t = title.lower()
    for i, role in enumerate(_ROLE_PRIORITY):
        if role in t:
            return i
    return len(_ROLE_PRIORITY)


def _rank(candidates: List[Dict]) -> List[Dict]:
    targeted = [c for c in candidates if not c.get("title") or _is_target_role(c.get("title", ""))]
    pool = targeted or candidates  # if nothing matches titles, try everyone

    def key(c: Dict) -> Tuple[int, int]:
        return (_role_score(c.get("title", "")), 0 if c.get("email") else 1)

    return sorted(pool, key=key)


def _split_name(full: str) -> Tuple[str, str]:
    parts = full.strip().split()
    if not parts:
        return "", ""
    return parts[0], " ".join(parts[1:]) if len(parts) > 1 else ""
