"""ContactOut provider.

Endpoint used:
  - POST https://api.contactout.com/v1/people/search (find a person by name/company/title)

Auth: header `token: <API_KEY>`.

VERIFIED against a live call on 2026-10-20 with a real (trial-tier) API
key. Two things were corrected from the first (docs-only) version after
seeing the real response:

  1. `profiles` is a dict keyed by LinkedIn URL/vanity slug, not a list.
  2. Email/phone/verification live under each profile's `contact_info`
     object (`work_emails`, `personal_emails`, `phones`,
     `work_email_status`), not top-level `work_email`/`personal_email`
     fields as the secondhand docs suggested.

That same test call returned ContactOut's documented placeholder/"sample
response" content (`message: "This is a sample response..."`, emails like
`test@gmail.com`/`email1@example.com`) -- the trial-tier key used to test
this proves the request shape, auth, and response parsing are correct,
but does NOT prove real lookups work. A paid plan is required for that;
re-verify with a paid key before trusting results in a normal run.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from app.contacts.base import ContactProvider
from app.models import ContactResult, ContactSearchQuery

logger = logging.getLogger(__name__)

BASE_URL = "https://api.contactout.com"


class ContactOutProvider(ContactProvider):
    name = "contactout"

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def _headers(self) -> dict:
        return {"token": self.api_key, "Content-Type": "application/json"}

    def search_person(self, query: ContactSearchQuery) -> Optional[ContactResult]:
        if not self.is_configured():
            logger.warning("ContactOut not configured (missing CONTACTOUT_API_KEY); skipping.")
            return None

        payload = {
            "name": query.name,
            "company": query.company,
            "job_title": query.title,
        }
        try:
            resp = requests.post(
                f"{BASE_URL}/v1/people/search", json=payload, headers=self._headers(), timeout=15
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("ContactOut search_person failed: %s", e)
            return None

        if data.get("message"):
            logger.info("ContactOut response note: %s", data["message"])

        profiles_obj = data.get("profiles")
        top = None
        if isinstance(profiles_obj, dict) and profiles_obj:
            top = next(iter(profiles_obj.values()))
        elif isinstance(profiles_obj, list) and profiles_obj:
            top = profiles_obj[0]

        if top is None:
            return ContactResult(
                email=None, email_status="not_found", phone=None, confidence=0.0,
                source=self.name, credits_used=0, raw=data,
            )

        contact_info = top.get("contact_info") or {}
        work_emails = contact_info.get("work_emails") or []
        personal_emails = contact_info.get("personal_emails") or []
        phones = contact_info.get("phones") or []
        work_email = work_emails[0] if work_emails else None
        personal_email = personal_emails[0] if personal_emails else None
        email = work_email or personal_email

        email_status = "unverified"
        if work_email:
            status_map = contact_info.get("work_email_status") or {}
            raw_status = str(status_map.get(work_email, "")).lower()
            if "verified" in raw_status and "unverified" not in raw_status:
                email_status = "verified"

        return ContactResult(
            email=email,
            email_status=email_status if email else "not_found",
            phone=phones[0] if phones else None,
            confidence=0.8 if work_email else (0.5 if personal_email else 0.0),
            source=self.name,
            credits_used=1 if email else 0,
            raw=top,
        )

    def verify_email(self, email: str) -> Optional[str]:
        """Not independently re-verified -- the live test above showed
        work_email_status is already embedded in the search response, so
        the pipeline never needs to call this separately for ContactOut
        (see app/pipeline.py's lookup_contacts, which skips the extra call
        for provider.name == 'contactout'). Kept as a documented-but-
        unverified fallback for direct use outside the pipeline."""
        if not self.is_configured():
            return None
        try:
            resp = requests.get(
                f"{BASE_URL}/v1/people/linkedin/work_email_status",
                params={"email": email},
                headers=self._headers(),
                timeout=15,
            )
            resp.raise_for_status()
            data = resp.json()
        except requests.RequestException as e:
            logger.error("ContactOut verify_email failed: %s", e)
            return "unknown"
        status = str(data.get("status", "")).lower()
        if "verified" in status and "unverified" not in status:
            return "valid"
        if "invalid" in status:
            return "invalid"
        return "unknown"

    def usage_info(self) -> dict:
        return {
            "provider": self.name,
            "credits_remaining": None,
            "note": (
                "ContactOut does not expose a dedicated usage endpoint; check "
                "the dashboard at contactout.com for current credit balance."
            ),
        }
