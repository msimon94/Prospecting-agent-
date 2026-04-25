"""
Finds LinkedIn profiles for target roles at a company by searching
DuckDuckGo for `site:linkedin.com/in` queries.

No LinkedIn account or API key required. Results come from search
engine snippets so name + title are extracted from snippet text,
not from LinkedIn directly.
"""

import asyncio
import re
from typing import Dict, List, Optional
from urllib.parse import unquote

import httpx
from bs4 import BeautifulSoup

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
}

# Each group is one DuckDuckGo query. We search highest-priority roles first
# and stop early once we have enough candidates.
_ROLE_QUERY_GROUPS = [
    ['"CRO"', '"Chief Revenue Officer"'],
    ['"VP of Sales"', '"VP Sales"', '"Head of Sales"', '"Director of Sales"'],
    ['"CEO"', '"Chief Executive Officer"', '"Founder"', '"Co-Founder"'],
    ['"VP of Marketing"', '"CMO"', '"Chief Marketing Officer"', '"Head of Marketing"'],
    ['"VP of Revenue"', '"Head of Revenue"', '"Revenue Operations"', '"RevOps"'],
    ['"VP of Growth"', '"Head of Growth"'],
    ['"COO"', '"Chief Operating Officer"', '"VP of Operations"', '"Head of Operations"'],
]


class LinkedInFinder:
    async def find_profiles(
        self, company_name: str, company_domain: str
    ) -> List[Dict]:
        all_profiles: List[Dict] = []
        seen_urls: set = set()

        for title_terms in _ROLE_QUERY_GROUPS:
            query = _build_query(company_name, title_terms)
            batch = await self._search(query)
            for p in batch:
                url = p.get("linkedin_url", "")
                if url and url not in seen_urls:
                    seen_urls.add(url)
                    all_profiles.append(p)

            if len(all_profiles) >= 8:
                break

            # Polite delay between search requests
            await asyncio.sleep(1.5)

        return all_profiles

    async def _search(self, query: str) -> List[Dict]:
        try:
            async with httpx.AsyncClient(
                timeout=20, headers=_HEADERS, follow_redirects=True
            ) as client:
                resp = await client.post(
                    "https://html.duckduckgo.com/html/",
                    data={"q": query},
                )
                if resp.status_code != 200:
                    return []
                return _parse_results(resp.text)
        except Exception:
            return []


# ── helpers ───────────────────────────────────────────────────────────────────

def _build_query(company_name: str, title_terms: List[str]) -> str:
    terms = " OR ".join(title_terms[:4])
    return f'site:linkedin.com/in "{company_name}" ({terms})'


def _parse_results(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, "lxml")
    profiles = []

    for result in soup.select(".result"):
        link_el = result.select_one(".result__a")
        snippet_el = result.select_one(".result__snippet")
        if not link_el:
            continue

        linkedin_url = _extract_linkedin_url(link_el.get("href", ""))
        if not linkedin_url:
            continue

        title_text = link_el.get_text(strip=True)
        snippet_text = snippet_el.get_text(strip=True) if snippet_el else ""
        name, title = _parse_name_title(title_text, snippet_text)

        if name:
            profiles.append({
                "name": name,
                "title": title,
                "linkedin_url": linkedin_url,
                "email": "",
            })

    return profiles


def _extract_linkedin_url(href: str) -> Optional[str]:
    # Direct LinkedIn URL in href
    if "linkedin.com/in/" in href:
        m = re.search(r'https?://[a-z.]*linkedin\.com/in/[^&?\s"\']+', href)
        if m:
            return m.group(0).rstrip("/")

    # DuckDuckGo redirect: /l/?uddg={encoded_url}
    m = re.search(r'uddg=([^&]+)', href)
    if m:
        decoded = unquote(m.group(1))
        if "linkedin.com/in/" in decoded:
            return decoded.rstrip("/")

    return None


def _parse_name_title(title_text: str, snippet_text: str) -> tuple:
    """
    LinkedIn result titles look like:
      "John Smith - CRO at Acme Corp | LinkedIn"
      "Jane Doe – VP of Sales · Acme Corp"
    """
    text = re.sub(r"\|\s*LinkedIn\s*$", "", title_text, flags=re.IGNORECASE).strip()
    text = re.sub(r"\s+", " ", text)

    # Split on common separators
    parts = re.split(r"\s[-–·|]\s", text, maxsplit=2)

    if len(parts) >= 2:
        name = parts[0].strip()
        job = parts[1].strip()
        # Drop company suffix: "CRO at Acme" → "CRO"
        job = re.sub(r"\s+(?:at|@)\s+.+$", "", job, flags=re.IGNORECASE).strip()
        return name, job

    return text.strip(), ""
