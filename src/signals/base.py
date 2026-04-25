from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class Company(BaseModel):
    name: str
    domain: str
    industry: Optional[str] = None
    employee_count: Optional[int] = None
    context: Optional[str] = None  # free-text personalization notes from CSV


class Contact(BaseModel):
    first_name: str
    last_name: str
    email: Optional[str] = None
    title: str = ""
    company_name: str = ""
    company_domain: str = ""
    linkedin_url: Optional[str] = None
    source: str = ""  # "hunter" | "website" | "linkedin_search"
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EmailOutput(BaseModel):
    subject: str
    body: str
    contact: Contact
