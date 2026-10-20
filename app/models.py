"""Plain data containers shared across pipeline stages.

These are transport objects between stages, not an ORM layer -- persistence
lives in app/db.py.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class JobPosting:
    """A normalized job posting as produced by a source adapter, before
    it has been written to the database."""

    source: str
    external_id: str
    url: str
    title: str
    company: str
    location: str
    description: str
    posted_at: Optional[str] = None  # ISO date string, source-reported
    is_sample: bool = False
    # Evidence about who posted it / who the recruiter might be, as reported
    # by the source. Nothing here is assumed to be verified -- recruiter
    # matching logic decides how much to trust it.
    named_recruiter: Optional[dict] = None       # {"name":..., "title":...}
    hiring_manager: Optional[dict] = None         # {"name":..., "title":...}
    poster_is_recruiter: bool = False
    poster: Optional[dict] = None                 # {"name":..., "title":...}
    careers_email: Optional[str] = None
    raw: dict = field(default_factory=dict)


@dataclass
class ContactSearchQuery:
    name: Optional[str]
    company: Optional[str]
    title: Optional[str] = None
    linkedin_url: Optional[str] = None


@dataclass
class ContactResult:
    email: Optional[str]
    email_status: str   # "verified" | "unverified" | "not_found"
    phone: Optional[str]
    confidence: float
    source: str          # provider name, e.g. "contactout", "signalhire", "mock"
    credits_used: int = 0
    raw: dict = field(default_factory=dict)


@dataclass
class EmailDraftContent:
    subject: str
    body: str
