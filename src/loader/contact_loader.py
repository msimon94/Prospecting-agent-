"""
Loads a contact list from CSV or Excel and returns a list of Contact objects.

Supported export formats (column names are matched case-insensitively):
  - Apollo.io, LinkedIn Sales Navigator, ZoomInfo, manual CSV/XLSX

Required columns (any variant accepted):
  first_name  | "First Name" | "firstname"
  last_name   | "Last Name"  | "lastname"
  email       | "Email Address" | "Work Email"
  company     | "Company Name"  | "Organization"

Optional columns:
  title       | "Job Title" | "Position"
  domain      | "Company Domain" | "Website"
  industry    | "Industry"
  employees   | "Company Size" | "Num Employees"
  linkedin    | "LinkedIn URL"
  phone       | "Phone" | "Mobile"
  context     | "Notes" | "Campaign" | "Reason" | "Personalization"
"""

import csv
from pathlib import Path
from typing import List, Optional

from ..signals.base import Contact

# Each logical field maps to a list of accepted column-name variants (lowercase)
_COLUMN_MAP = {
    "first_name":     ["first_name", "first name", "firstname", "first"],
    "last_name":      ["last_name", "last name", "lastname", "last"],
    "email":          ["email", "email_address", "email address", "work email", "work_email"],
    "company":        ["company", "company_name", "company name", "organization", "account name"],
    "title":          ["title", "job_title", "job title", "position", "role"],
    "company_domain": ["company_domain", "domain", "website", "company_url", "company url"],
    "industry":       ["industry", "vertical", "sector"],
    "employee_count": ["employee_count", "employees", "company_size", "company size",
                       "num_employees", "num employees", "headcount"],
    "linkedin_url":   ["linkedin_url", "linkedin url", "linkedin", "profile url", "profile_url"],
    "phone":          ["phone", "phone_number", "phone number", "mobile", "direct phone"],
    "context":        ["context", "notes", "note", "campaign", "reason",
                       "personalization", "custom note", "custom_note", "message"],
}


def _build_header_index(headers: List[str]) -> dict:
    """Map logical field names → column index using the variant table."""
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


def load_contacts(file_path: str) -> List[Contact]:
    path = Path(file_path)
    if not path.exists():
        raise FileNotFoundError(f"Contact file not found: {file_path}")

    suffix = path.suffix.lower()
    if suffix in (".xlsx", ".xls"):
        return _load_excel(path)
    return _load_csv(path)


def _load_csv(path: Path) -> List[Contact]:
    contacts: List[Contact] = []
    skipped = 0

    with open(path, newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        headers = next(reader)
        index = _build_header_index(headers)

        _require_fields(index, path.name)

        for row in reader:
            if not any(cell.strip() for cell in row):
                continue  # skip blank rows
            contact = _row_to_contact(row, index)
            if contact:
                contacts.append(contact)
            else:
                skipped += 1

    _print_summary(path.name, contacts, skipped)
    return contacts


def _load_excel(path: Path) -> List[Contact]:
    try:
        import openpyxl
    except ImportError:
        raise ImportError(
            "openpyxl is required for Excel files. Install it with: pip install openpyxl"
        )

    wb = openpyxl.load_workbook(path, read_only=True, data_only=True)
    ws = wb.active
    rows = list(ws.iter_rows(values_only=True))
    wb.close()

    if not rows:
        return []

    headers = [str(cell) if cell is not None else "" for cell in rows[0]]
    index = _build_header_index(headers)
    _require_fields(index, path.name)

    contacts: List[Contact] = []
    skipped = 0
    for raw_row in rows[1:]:
        row = [str(cell) if cell is not None else "" for cell in raw_row]
        if not any(cell.strip() for cell in row):
            continue
        contact = _row_to_contact(row, index)
        if contact:
            contacts.append(contact)
        else:
            skipped += 1

    _print_summary(path.name, contacts, skipped)
    return contacts


def _row_to_contact(row: List[str], index: dict) -> Optional[Contact]:
    email = _get(row, index, "email")
    first_name = _get(row, index, "first_name") or ""
    last_name = _get(row, index, "last_name") or ""
    company = _get(row, index, "company") or ""

    # Must have email; at least a name or company to personalize
    if not email or "@" not in email:
        return None
    if not (first_name or last_name) and not company:
        return None

    employee_raw = _get(row, index, "employee_count")
    try:
        employee_count = int(str(employee_raw).replace(",", "")) if employee_raw else None
    except ValueError:
        employee_count = None

    return Contact(
        first_name=first_name,
        last_name=last_name,
        email=email,
        title=_get(row, index, "title") or "",
        company_name=company,
        company_domain=_get(row, index, "company_domain") or "",
        linkedin_url=_get(row, index, "linkedin_url"),
        phone=_get(row, index, "phone"),
        metadata={
            "industry": _get(row, index, "industry"),
            "employee_count": employee_count,
            "context": _get(row, index, "context"),
        },
    )


def _require_fields(index: dict, filename: str) -> None:
    missing = [f for f in ("first_name", "last_name", "email", "company") if f not in index]
    if missing:
        raise ValueError(
            f"{filename} is missing required columns: {missing}\n"
            "Expected headers (case-insensitive): "
            "first_name, last_name, email, company"
        )


def _print_summary(filename: str, contacts: List[Contact], skipped: int) -> None:
    print(f"  Loaded {len(contacts)} contacts from {filename}"
          + (f" ({skipped} skipped — missing email)" if skipped else ""))
