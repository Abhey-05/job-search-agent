"""Email-sending provider contract."""
from __future__ import annotations

from abc import ABC, abstractmethod


class EmailProvider(ABC):
    name: str = "unnamed_email_provider"

    @abstractmethod
    def is_configured(self) -> bool:
        raise NotImplementedError

    @abstractmethod
    def send(self, to_email: str, subject: str, body: str) -> str:
        """Send the email and return a provider message id."""
        raise NotImplementedError
