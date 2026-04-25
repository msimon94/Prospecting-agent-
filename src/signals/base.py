from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class Contact(BaseModel):
    id: Optional[str] = None
    first_name: str
    last_name: str
    email: Optional[str] = None
    title: str = ""
    company_name: str = ""
    company_domain: str = ""
    linkedin_url: Optional[str] = None
    phone: Optional[str] = None
    # Catches industry, employee_count, and any free-text "context" / "notes"
    # column from the imported list — used by the email generator.
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EmailOutput(BaseModel):
    subject: str
    body: str
    contact: Contact
