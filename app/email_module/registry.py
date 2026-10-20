from __future__ import annotations

from app.email_module.base import EmailProvider
from app.email_module.gmail_provider import GmailProvider
from app.email_module.mock_email_provider import MockEmailProvider


def get_email_provider(config) -> EmailProvider:
    choice = config.email.get("provider", "mock")
    if choice == "mock":
        return MockEmailProvider()
    if choice == "gmail":
        provider = GmailProvider(
            client_id=config.resolve_env_secret("GMAIL_CLIENT_ID"),
            client_secret=config.resolve_env_secret("GMAIL_CLIENT_SECRET"),
            refresh_token=config.resolve_env_secret("GMAIL_REFRESH_TOKEN"),
            from_email=config.email.get("from_email"),
        )
        if not provider.is_configured():
            import logging
            logging.getLogger(__name__).warning(
                "email.provider is 'gmail' but GMAIL_CLIENT_ID/SECRET/REFRESH_TOKEN "
                "are not all set; falling back to the mock email provider."
            )
            return MockEmailProvider()
        return provider
    raise ValueError(f"Unknown email.provider '{choice}'")
