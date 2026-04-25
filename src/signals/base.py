from enum import Enum
from datetime import datetime
from typing import Optional, Dict, Any
from pydantic import BaseModel, Field


class SignalType(str, Enum):
    JOB_CHANGE = "job_change"
    FUNDING_ROUND = "funding_round"
    TECH_INSTALL = "tech_install"
    TECH_UNINSTALL = "tech_uninstall"
    HIRING_SURGE = "hiring_surge"
    G2_INTENT = "g2_intent"


class SignalPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class CompanySignal(BaseModel):
    id: str
    signal_type: SignalType
    company_name: str
    company_domain: str
    company_id: Optional[str] = None
    priority: SignalPriority = SignalPriority.MEDIUM
    detected_at: datetime = Field(default_factory=datetime.utcnow)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class Contact(BaseModel):
    id: Optional[str] = None
    first_name: str
    last_name: str
    email: Optional[str] = None
    title: str
    company_name: str
    company_domain: str
    linkedin_url: Optional[str] = None
    phone: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class EnrichedContact(BaseModel):
    contact: Contact
    signal: CompanySignal
    hubspot_id: Optional[str] = None
    in_active_deal: bool = False
    last_contacted: Optional[datetime] = None
    linkedin_data: Optional[Dict[str, Any]] = None


class EmailOutput(BaseModel):
    subject: str
    body: str
    contact: Contact
    signal: CompanySignal
