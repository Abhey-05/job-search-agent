"""Chooses a contact provider from config. Pipeline code only ever calls
get_contact_provider(config) -- it never imports a specific provider."""
from __future__ import annotations

import logging

from app.contacts.base import ContactProvider
from app.contacts.contactout_provider import ContactOutProvider
from app.contacts.mock_provider import MockContactProvider
from app.contacts.signalhire_provider import SignalHireProvider

logger = logging.getLogger(__name__)


def get_contact_provider(config) -> ContactProvider:
    enabled = config.contacts.get("enabled_provider")

    if enabled == "contactout":
        api_key = config.resolve_env_secret(config.contacts["contactout"]["api_key_env"])
        provider = ContactOutProvider(api_key)
    elif enabled == "signalhire":
        api_key = config.resolve_env_secret(config.contacts["signalhire"]["api_key_env"])
        provider = SignalHireProvider(api_key)
    elif enabled is None:
        return MockContactProvider()
    else:
        raise ValueError(f"Unknown contacts.enabled_provider '{enabled}'")

    if not provider.is_configured():
        logger.warning(
            "Contact provider '%s' is enabled in config but not configured "
            "(missing API key env var). Falling back to the mock provider "
            "for this run.", enabled,
        )
        return MockContactProvider()
    return provider
