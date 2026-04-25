"""
Scrapes a company's website to find team members: names, titles,
emails, and LinkedIn URLs.

Strategy (tried in order per page):
  1. JSON-LD schema.org Person objects
  2. HTML itemtype=schema.org/Person markup
  3. Pattern-based person-card detection (class names, heading + subtitle combos)
  4. LinkedIn <a href> links with surrounding context
"""

import asyncio
import json
import re
from typing import Dict, List, Optional
from urllib.parse import urlparse

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

_TEAM_PAGE_PATHS = [
    "/team", "/about", "/about-us", "/leadership", "/people",
    "/our-team", "/management", "/executives", "/staff",
    "/about/team", "/about/leadership", "/company/team",
    "/company/about", "/company", "/who-we-are",
]

_TEAM_LINK_KEYWORDS = {
    "team", "about", "leadership", "people",
    "management", "executives", "staff",
}

_CARD_CLASS_RE = re.compile(
    r"team|member|person|staff|employee|leader|executive|bio|people",
    re.IGNORECASE,
)


class WebScraper:
    async def find_team_members(self, domain: str) -> List[Dict]:
        base_url = f"https://{domain}"
        urls_to_try = await self._discover_team_pages(base_url)

        # Append standard paths that weren't already found
        found_set = set(urls_to_try)
        for path in _TEAM_PAGE_PATHS:
            candidate = base_url.rstrip("/") + path
            if candidate not in found_set:
                urls_to_try.append(candidate)

        members: List[Dict] = []
        seen_names: set = set()

        for url in urls_to_try[:8]:
            batch = await self._scrape_page(url)
            for m in batch:
                name_key = m.get("name", "").lower().strip()
                if name_key and name_key not in seen_names:
                    seen_names.add(name_key)
                    members.append(m)
            if len(members) >= 30:
                break
            await asyncio.sleep(0.5)

        return members

    # ── page discovery ────────────────────────────────────────────────────────

    async def _discover_team_pages(self, base_url: str) -> List[str]:
        try:
            async with httpx.AsyncClient(
                timeout=12, follow_redirects=True, headers=_HEADERS
            ) as client:
                resp = await client.get(base_url)
                if resp.status_code != 200:
                    return []
                soup = BeautifulSoup(resp.text, "lxml")
                urls = []
                for a in soup.find_all("a", href=True):
                    href = a["href"].lower()
                    text = a.get_text().lower().strip()
                    if any(kw in href or kw in text for kw in _TEAM_LINK_KEYWORDS):
                        full = _make_absolute(base_url, a["href"])
                        if full and _same_origin(base_url, full):
                            urls.append(full)
                return list(dict.fromkeys(urls))[:5]
        except Exception:
            return []

    # ── per-page scraping ─────────────────────────────────────────────────────

    async def _scrape_page(self, url: str) -> List[Dict]:
        try:
            async with httpx.AsyncClient(
                timeout=12, follow_redirects=True, headers=_HEADERS
            ) as client:
                resp = await client.get(url)
                if resp.status_code != 200:
                    return []
                soup = BeautifulSoup(resp.text, "lxml")
        except Exception:
            return []

        # Try strategies in order; stop when we find something useful
        for strategy in (
            self._from_jsonld,
            self._from_schema_html,
            self._from_card_patterns,
            self._from_linkedin_links,
        ):
            results = strategy(soup)
            if results:
                return results
        return []

    # ── strategy 1: JSON-LD ───────────────────────────────────────────────────

    def _from_jsonld(self, soup: BeautifulSoup) -> List[Dict]:
        persons = []
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except Exception:
                continue
            if isinstance(data, dict):
                data = [data]
            for item in (data if isinstance(data, list) else []):
                if not isinstance(item, dict):
                    continue
                if item.get("@type") == "Person":
                    p = _parse_schema_person(item)
                    if p:
                        persons.append(p)
                # Organization may embed employees
                elif item.get("@type") in ("Organization", "Corporation", "LocalBusiness"):
                    for emp in item.get("employee", []) + item.get("member", []):
                        if isinstance(emp, dict):
                            p = _parse_schema_person(emp)
                            if p:
                                persons.append(p)
        return persons

    # ── strategy 2: HTML schema.org markup ───────────────────────────────────

    def _from_schema_html(self, soup: BeautifulSoup) -> List[Dict]:
        persons = []
        for el in soup.find_all(attrs={"itemtype": re.compile(r"schema\.org/Person")}):
            name_el = el.find(attrs={"itemprop": "name"})
            title_el = el.find(attrs={"itemprop": "jobTitle"})
            email_el = el.find(attrs={"itemprop": "email"})
            linkedin_a = el.find("a", href=re.compile(r"linkedin\.com/in/", re.I))
            name = name_el.get_text(strip=True) if name_el else ""
            if not _valid_name(name):
                continue
            persons.append({
                "name": name,
                "title": title_el.get_text(strip=True) if title_el else "",
                "email": (email_el.get_text(strip=True) if email_el else ""),
                "linkedin_url": linkedin_a["href"] if linkedin_a else None,
            })
        return persons

    # ── strategy 3: CSS class pattern cards ──────────────────────────────────

    def _from_card_patterns(self, soup: BeautifulSoup) -> List[Dict]:
        candidates = soup.find_all(class_=_CARD_CLASS_RE)
        persons = []
        seen = set()
        for card in candidates:
            p = _parse_card(card)
            if p and _valid_name(p["name"]) and p["name"] not in seen:
                seen.add(p["name"])
                persons.append(p)
        return persons

    # ── strategy 4: LinkedIn href links ──────────────────────────────────────

    def _from_linkedin_links(self, soup: BeautifulSoup) -> List[Dict]:
        persons = []
        seen_urls: set = set()
        for a in soup.find_all("a", href=re.compile(r"linkedin\.com/in/", re.I)):
            href = a["href"]
            if href in seen_urls:
                continue
            seen_urls.add(href)
            # Gather text from the link's parent block
            parent = a.parent or a
            lines = [
                l.strip()
                for l in parent.get_text(separator="\n").split("\n")
                if l.strip()
            ]
            name = lines[0] if lines else a.get_text(strip=True)
            title = lines[1] if len(lines) > 1 else ""
            if _valid_name(name):
                persons.append({
                    "name": name,
                    "title": title,
                    "email": "",
                    "linkedin_url": href,
                })
        return persons


# ── helpers ───────────────────────────────────────────────────────────────────

def _parse_schema_person(data: dict) -> Optional[Dict]:
    name = data.get("name", "")
    if not _valid_name(name):
        return None
    same_as = data.get("sameAs") or []
    linkedin = next(
        (s for s in same_as if isinstance(s, str) and "linkedin.com" in s), None
    )
    return {
        "name": name,
        "title": data.get("jobTitle", ""),
        "email": str(data.get("email", "")).replace("mailto:", ""),
        "linkedin_url": linkedin,
    }


def _parse_card(el) -> Optional[Dict]:
    text = el.get_text(separator="\n", strip=True)
    if not text or len(text) < 4:
        return None

    linkedin_a = el.find("a", href=re.compile(r"linkedin\.com/in/", re.I))
    mailto_a = el.find("a", href=re.compile(r"^mailto:", re.I))

    email = ""
    if mailto_a:
        email = mailto_a["href"].replace("mailto:", "").split("?")[0].strip()

    # Prefer heading tags for name
    name, title = "", ""
    headings = el.find_all(["h1", "h2", "h3", "h4", "h5", "strong", "b"])
    if headings:
        name = headings[0].get_text(strip=True)
        title = headings[1].get_text(strip=True) if len(headings) > 1 else ""
    if not name:
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        name = lines[0] if lines else ""
        title = lines[1] if len(lines) > 1 else ""

    return {
        "name": name,
        "title": title,
        "email": email,
        "linkedin_url": linkedin_a["href"] if linkedin_a else None,
    }


def _valid_name(name: str) -> bool:
    if not name or len(name) < 3 or len(name) > 60:
        return False
    junk = {"read more", "learn more", "view", "click here", "button", "menu", "nav"}
    return name.lower() not in junk and not name.startswith("<")


def _make_absolute(base_url: str, href: str) -> Optional[str]:
    if not href or href.startswith(("#", "javascript:", "mailto:")):
        return None
    if href.startswith("http"):
        return href
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        parsed = urlparse(base_url)
        return f"{parsed.scheme}://{parsed.netloc}{href}"
    return base_url.rstrip("/") + "/" + href


def _same_origin(base_url: str, url: str) -> bool:
    return urlparse(base_url).netloc == urlparse(url).netloc
