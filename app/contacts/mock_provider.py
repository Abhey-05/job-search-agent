"""Deterministic mock contact provider.

Used whenever no real provider is configured (the default), and in all
tests / sample-data demonstrations. It never makes a network call and
never claims a "verified" email -- only "unverified", so downstream code
and the dashboard can never mistake mock output for a real lookup.
"""
from __future__ import annotations

import hashlib
import re
from typing import Optional

from app.contacts.base import ContactProvider
from app.models import ContactResult, ContactSearchQuery


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]", "", text.lower())


class MockContactProvider(ContactProvider):
    name = "mock"

    def is_configured(self) -> bool:
        return True

    def search_person(self, query: ContactSearchQuery) -> Optional[ContactResult]:
        if not query.name or not query.company:
            return None
        parts = query.name.strip().split()
        first = _slug(parts[0]) if parts else "contact"
        domain = _slug(query.company) + ".example.com"
        email = f"{first}@{domain}"
        digest = hashlib.sha256(f"{query.name}{query.company}".encode()).hexdigest()
        confidence = 0.4 + (int(digest[:2], 16) / 255) * 0.3  # 0.4-0.7, deterministic
        return ContactResult(
            email=email,
            email_status="unverified",
            phone=None,
            confidence=round(confidence, 2),
            source=self.name,
            credits_used=0,
            raw={"note": "MOCK DATA - not a real lookup", "query": query.__dict__},
        )

    def verify_email(self, email: str) -> Optional[str]:
        return "unknown"

    def usage_info(self) -> dict:
        return {"provider": self.name, "credits_remaining": None, "note": "mock provider, no real credits"}
