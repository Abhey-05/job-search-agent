"""ContactOut provider.

Built against ContactOut's public API documentation at
https://api.contactout.com/ (reviewed October 2026). Endpoints used:

  - POST https://api.contactout.com/v1/people/search   (find a person by name/company/title)
  - GET  https://api.contactout.com/v1/people/linkedin/work_email_status  (verify a found work email)

Auth: header `token: <API_KEY>`. ContactOut does not offer self-serve key
issuance -- a key is obtained by booking a meeting with their team. This
class will simply report `is_configured() == False` and the pipeline falls
back to the mock provider until CONTACTOUT_API_KEY is set.

IMPORTANT: this integration has NOT been exercised against a live account
(no credentials were available while building it). The request/response
shapes below follow the published docs as closely as possible, but treat
this as untested until you run `python -m app verify-contacts contactout`
with a real key and confirm it against your own dashboard's usage counter.
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

        profiles = data.get("profiles") or data.get("results") or []
        if not profiles:
            return ContactResult(
                email=None, email_status="not_found", phone=None, confidence=0.0,
                source=self.name, credits_used=0, raw=data,
            )

        top = profiles[0]
        work_email = top.get("work_email")
        personal_email = top.get("personal_email")
        email = work_email or personal_email
        email_status = "unverified"
        if work_email:
            status = self.verify_email(work_email)
            if status == "valid":
                email_status = "verified"

        return ContactResult(
            email=email,
            email_status=email_status if email else "not_found",
            phone=top.get("phone"),
            confidence=0.8 if work_email else (0.5 if personal_email else 0.0),
            source=self.name,
            credits_used=1 if email else 0,
            raw=top,
        )

    def verify_email(self, email: str) -> Optional[str]:
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
        status = (data.get("status") or "").lower()
        if status in ("verified", "valid"):
            return "valid"
        if status in ("invalid", "unverified"):
            return "invalid" if status == "invalid" else "unknown"
        return "unknown"

    def usage_info(self) -> dict:
        return {
            "provider": self.name,
            "credits_remaining": None,
            "note": (
                "ContactOut does not expose a dedicated usage endpoint in the "
                "reviewed public docs; check the dashboard at contactout.com "
                "for current credit balance."
            ),
        }
