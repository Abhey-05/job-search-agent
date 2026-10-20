"""SignalHire provider.

Built against SignalHire's public API documentation at
https://docs.signalhire.com/ (reviewed October 2026). Endpoint used:

  - POST https://www.signalhire.com/api/v1/candidate/search

Auth: header `apikey: <API_KEY>`. Supports an async mode (callbackUrl) and
a synchronous mode (`withoutWaterfall: true`) -- this provider uses the
synchronous mode so it fits the pipeline's simple request/response flow.
Credit balance is returned via the `X-Credits-Left` response header.

IMPORTANT: this integration has NOT been exercised against a live account
(no credentials were available while building it). Treat it as untested
until you run it with a real SIGNALHIRE_API_KEY and confirm behavior
against your own account.
"""
from __future__ import annotations

import logging
from typing import Optional

import requests

from app.contacts.base import ContactProvider
from app.models import ContactResult, ContactSearchQuery

logger = logging.getLogger(__name__)

SEARCH_URL = "https://www.signalhire.com/api/v1/candidate/search"


class SignalHireProvider(ContactProvider):
    name = "signalhire"

    def __init__(self, api_key: Optional[str]):
        self.api_key = api_key
        self._last_credits_left: Optional[int] = None

    def is_configured(self) -> bool:
        return bool(self.api_key)

    def search_person(self, query: ContactSearchQuery) -> Optional[ContactResult]:
        if not self.is_configured():
            logger.warning("SignalHire not configured (missing SIGNALHIRE_API_KEY); skipping.")
            return None

        # SignalHire's documented Person API matches on identifiers
        # (LinkedIn URL / email / phone / UID), not free-text name+company.
        # Without a verified LinkedIn URL for this person, the only
        # documented path is their Search API (filters, no contact reveal)
        # followed by a Person API call on a resulting identifier. That
        # two-step flow needs live testing against a real account before
        # being wired into the pipeline, so for now this surfaces a clear
        # "not supported without a profile URL" result instead of guessing.
        if not query.linkedin_url:
            logger.info(
                "SignalHire search_person requires a LinkedIn URL identifier; "
                "none available for %s at %s.", query.name, query.company,
            )
            return None

        return self.enrich_profile(query.linkedin_url)

    def enrich_profile(self, linkedin_url: str) -> Optional[ContactResult]:
        if not self.is_configured():
            return None
        payload = {"items": [linkedin_url], "withoutWaterfall": True}
        try:
            resp = requests.post(
                SEARCH_URL,
                json=payload,
                headers={"apikey": self.api_key, "Content-Type": "application/json"},
                timeout=20,
            )
            resp.raise_for_status()
            self._last_credits_left = resp.headers.get("X-Credits-Left")
            data = resp.json()
        except requests.RequestException as e:
            logger.error("SignalHire enrich_profile failed: %s", e)
            return None

        results = data if isinstance(data, list) else data.get("results", [])
        if not results:
            return ContactResult(
                email=None, email_status="not_found", phone=None, confidence=0.0,
                source=self.name, credits_used=0, raw=data,
            )
        item = results[0]
        if item.get("status") != "success":
            return ContactResult(
                email=None, email_status="not_found", phone=None, confidence=0.0,
                source=self.name, credits_used=0, raw=item,
            )
        candidate = item.get("candidate", {})
        contacts = candidate.get("contacts", [])
        email = next((c.get("value") for c in contacts if c.get("type") == "email"), None)
        phone = next((c.get("value") for c in contacts if c.get("type") == "phone"), None)
        return ContactResult(
            email=email,
            email_status="unverified" if email else "not_found",
            phone=phone,
            confidence=0.7 if email else 0.0,
            source=self.name,
            credits_used=1 if email else 0,
            raw=item,
        )

    def usage_info(self) -> dict:
        return {
            "provider": self.name,
            "credits_remaining": self._last_credits_left,
            "note": "Populated from the X-Credits-Left header after the most recent call.",
        }
