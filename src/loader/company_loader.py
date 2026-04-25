"""
Loads a company list from CSV or Excel into Company objects.

Supported column names (case-insensitive):
  name    : company_name | company | name | organization | account | account name
  domain  : domain | website | url | company_domain | company_url | web
  industry: industry | vertical | sector
  employees: employee_count | employees | company_size | headcount | num employees
  context : context | notes | note | reason | personalization | campaign | custom note
"""

import csv
import re
from pathlib import Path
from typing import List, Optional
from urllib.parse import urlparse

from ..signals.base import Company

_COLUMN_MAP = {
    "name":     ["company_name", "company", "name", "organization", "account name", "account"],
    "domain":   ["domain", "website", "url", "company_domain", "company_url", "web", "website url"],
    "industry": ["industry", "vertical", "sector"],
    "employees": ["employee_count", "employees", "company_size", "company size",
                  "num_employees", "num employees", "headcount"],
    "context":  ["context", "notes", "note", "reason", "personalization",
                 "campaign", "custom note", "custom_note", "message"],
}


def _build_index(headers: List[str]) -> dict:
    normalized = {h.strip().lower(): i for i, h in enumerate(headers)}
    index = {}
    for field, variants in _COLUMN_MAP.items():
        for variant in variants:
            if variant in normalized:
                index[field] = normalized[variant]
                break
    return index


def _get(row: List[str], index: dict, field: str) -> Optional[str]:
    col = index.get(field)
    if col is None or col >= len(row):
        return None
    val = row[col].strip()
    return val if val else None


def _normalize_domain(raw: str) -> str:
    """Strip protocol/path/www from a URL or domain string."""
    raw = raw.strip()
    if not raw:
        return ""
    # Add scheme so urlparse works
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    try:
        host = urlparse(raw).hostname or ""
        return re.sub(r"^www\.", "", host).lower()
    except Exception:
        return raw


def _row_to_company(row: List[str], index: dict) -> Optional[Company]:
    name = _get(row, index, "name") or ""
    domain_raw = _get(row, index, "domain") or ""

    if not name and not domain_raw:
        return None

    domain = _normalize_domain(domain_raw) if domain_raw else ""

    # Derive domain from name as last resort (e.g. "Acme Corp" → "acmecorp.com")
    # — but only flag it, not actually guess, since guessing is unreliable
    if not domain:
        return None  # can't do anything without a domain

    emp_raw = _get(row, index, "employees")
    try:
        employee_count = int(str(emp_raw).replace(",", "")) if emp_raw else None
    except ValueError:
        employee_count = None

    return Company(
        name=name or domain,
        domain=domain,
        industry=_get(row, index, "industry"),
        employee_count=employee_count,
        context=_get(row, index, "context"),
    )


def load_companies(file_path: str) -> List[Company]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Company file not found: {file_path}")
    if path.suffix.lower() in (".xlsx", ".xls"):
        return _load_excel(path)
    return _load_csv(path)


def _load_csv(path: Path) -> List[Company]:
    companies: List[Company] = []
    skipped = 0
    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        index = _build_index(headers)
        _require_fields(index, path.name)
        for row in reader:
            if not any(c.strip() for c in row):
                continue
            company = _row_to_company(row, index)
            if company:
                companies.append(company)
            else:
                skipped += 1
    _print_summary(path.name, companies, skipped)
    return companies


def _load_excel(path: Path) -> List[Company]:
    try:
        import openpyxl
    except ImportError:
        raise ImportError("openpyxl required for Excel: pip install openpyxl")

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    headers = [str(c) if c is not None else "" for c in rows[0]]
    index = _build_index(headers)
    _require_fields(index, path.name)

    companies: List[Company] = []
    skipped = 0
    for raw in rows[1:]:
        row = [str(c) if c is not None else "" for c in raw]
        if not any(c.strip() for c in row):
            continue
        company = _row_to_company(row, index)
        if company:
            companies.append(company)
        else:
            skipped += 1

    _print_summary(path.name, companies, skipped)
    return companies


def _require_fields(index: dict, filename: str) -> None:
    if "domain" not in index:
        raise ValueError(
            f"{filename} is missing a 'domain' (or 'website') column. "
            "The agent needs a domain to scrape and find contacts."
        )


def _print_summary(filename: str, companies: List[Company], skipped: int) -> None:
    print(
        f"  Loaded {len(companies)} companies from {filename}"
        + (f" ({skipped} skipped — missing domain)" if skipped else "")
    )
