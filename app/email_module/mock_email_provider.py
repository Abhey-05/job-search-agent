"""Records a 'send' in memory/log only -- no real email is ever transmitted.
This is the only provider wired up out of the box, by design: real sending
requires an explicit, authenticated provider the user configures themselves."""
from __future__ import annotations

import logging
import uuid

from app.email_module.base import EmailProvider

logger = logging.getLogger(__name__)


class MockEmailProvider(EmailProvider):
    name = "mock"

    def is_configured(self) -> bool:
        return True

    def send(self, to_email: str, subject: str, body: str) -> str:
        message_id = f"mock-{uuid.uuid4().hex[:12]}"
        logger.info("[MOCK SEND] to=%s subject=%r message_id=%s", to_email, subject, message_id)
        return message_id
