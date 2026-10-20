"""Gmail sending provider via the Gmail REST API, authenticated with an
OAuth2 refresh token (no google-api-python-client dependency needed -- just
two documented REST calls).

Setup required (see docs/INTEGRATIONS.md for the full walkthrough):
  1. Create a Google Cloud project, enable the Gmail API.
  2. Create an OAuth 2.0 Client ID (Desktop app type is simplest).
  3. Grant yourself the `gmail.send` scope and complete the consent flow
     once (e.g. via Google's OAuth Playground) to obtain a refresh token.
  4. Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, GMAIL_REFRESH_TOKEN as env
     vars / platform secrets, and set email.provider = "gmail" in settings.

IMPORTANT: this has NOT been exercised against a real Google account --
no credentials were available while building it. The two calls below
(token refresh, then users.messages.send) follow Google's official,
documented REST API exactly, but treat this as untested until you send
one real email through it and confirm it arrives.
"""
from __future__ import annotations

import base64
import logging
from email.mime.text import MIMEText
from typing import Optional

import requests

from app.email_module.base import EmailProvider

logger = logging.getLogger(__name__)

TOKEN_URL = "https://oauth2.googleapis.com/token"
SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailProvider(EmailProvider):
    name = "gmail"

    def __init__(self, client_id: Optional[str], client_secret: Optional[str],
                 refresh_token: Optional[str], from_email: Optional[str]):
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.from_email = from_email

    def is_configured(self) -> bool:
        return bool(self.client_id and self.client_secret and self.refresh_token)

    def _get_access_token(self) -> str:
        resp = requests.post(TOKEN_URL, data={
            "client_id": self.client_id,
            "client_secret": self.client_secret,
            "refresh_token": self.refresh_token,
            "grant_type": "refresh_token",
        }, timeout=15)
        resp.raise_for_status()
        return resp.json()["access_token"]

    def send(self, to_email: str, subject: str, body: str) -> str:
        if not self.is_configured():
            raise RuntimeError(
                "Gmail is not configured. Set GMAIL_CLIENT_ID, GMAIL_CLIENT_SECRET, "
                "and GMAIL_REFRESH_TOKEN. See docs/INTEGRATIONS.md."
            )
        access_token = self._get_access_token()

        message = MIMEText(body)
        message["to"] = to_email
        message["subject"] = subject
        if self.from_email:
            message["from"] = self.from_email
        raw = base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")

        resp = requests.post(
            SEND_URL,
            headers={"Authorization": f"Bearer {access_token}", "Content-Type": "application/json"},
            json={"raw": raw},
            timeout=15,
        )
        resp.raise_for_status()
        return resp.json()["id"]
