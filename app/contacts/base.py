"""Contact-provider contract.

Any provider (ContactOut, SignalHire, a future one, or the mock) implements
this interface. The pipeline only ever talks to this interface, so swapping
providers -- or running with none configured -- never touches pipeline code.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Optional

from app.models import ContactResult, ContactSearchQuery


class ContactProvider(ABC):
    name: str = "unnamed_provider"

    @abstractmethod
    def is_configured(self) -> bool:
        """True if credentials are present and this provider can be called."""
        raise NotImplementedError

    @abstractmethod
    def search_person(self, query: ContactSearchQuery) -> Optional[ContactResult]:
        """Find a person by name + company (+ optional title) and return
        whatever contact info the provider can surface in one call."""
        raise NotImplementedError

    def enrich_profile(self, linkedin_url: str) -> Optional[ContactResult]:
        """Optional: enrich a known profile URL. Default: unsupported."""
        return None

    def verify_email(self, email: str) -> Optional[str]:
        """Optional: returns 'valid' | 'invalid' | 'unknown'. Default: unsupported."""
        return None

    def usage_info(self) -> dict:
        """Optional: credits remaining / usage stats, if the provider exposes them."""
        return {}
