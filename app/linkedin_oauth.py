"""LinkedIn Sign-In via OpenID Connect -- NOT a job-search integration.

Built against LinkedIn's official documentation (learn.microsoft.com/en-us/linkedin),
reviewed 2026-10-21:
  - Authorization endpoint: https://www.linkedin.com/oauth/v2/authorization
  - Token endpoint:         https://www.linkedin.com/oauth/v2/accessToken
  - Userinfo endpoint:      https://api.linkedin.com/v2/userinfo
  - Discovery document:     https://www.linkedin.com/oauth/.well-known/openid-configuration

Scope requested: `openid profile email` ONLY. This is the entirety of
LinkedIn's "Open Permissions" tier -- the only self-serve, no-approval-
required products on their platform (confirmed against
learn.microsoft.com/en-us/linkedin/shared/authentication/getting-access).
It grants exactly: the member's name, headline/photo, and email address.

It does NOT grant, and this module makes NO attempt to access: job
search, job postings, messaging, connections, or Easy Apply. Those all
sit behind LinkedIn's Talent Solutions partner programs (Recruiter
System Connect, Apply Connect, Apply with LinkedIn), which require a
formal ATS-partner application -- not available to an individual
developer, and not implemented here. `w_member_social` (posting on the
member's behalf) is also deliberately not requested: it doesn't serve
this app's job-search-outreach purpose and would be an unnecessary,
unused permission.

This entire feature is OFF unless LINKEDIN_CLIENT_ID, LINKEDIN_CLIENT_SECRET,
and LINKEDIN_REDIRECT_URI are all set -- see docs/INTEGRATIONS.md for setup.
UNTESTED: no LinkedIn Developer app was available while building this: the
request shapes follow the official docs exactly, but no real authorization
round-trip has been completed. Do not treat "LinkedIn connected" as true
anywhere in this app unless a real callback has actually succeeded.
"""
from __future__ import annotations

import logging
import os
import secrets
import time
from typing import Optional
from urllib.parse import urlencode

import requests

logger = logging.getLogger(__name__)

AUTHORIZATION_URL = "https://www.linkedin.com/oauth/v2/authorization"
TOKEN_URL = "https://www.linkedin.com/oauth/v2/accessToken"
USERINFO_URL = "https://api.linkedin.com/v2/userinfo"
SCOPE = "openid profile email"


def is_configured() -> bool:
    return bool(
        os.environ.get("LINKEDIN_CLIENT_ID")
        and os.environ.get("LINKEDIN_CLIENT_SECRET")
        and os.environ.get("LINKEDIN_REDIRECT_URI")
    )


def generate_state() -> str:
    return secrets.token_urlsafe(32)


def build_authorization_url(state: str) -> str:
    params = {
        "response_type": "code",
        "client_id": os.environ["LINKEDIN_CLIENT_ID"],
        "redirect_uri": os.environ["LINKEDIN_REDIRECT_URI"],
        "state": state,
        "scope": SCOPE,
    }
    return f"{AUTHORIZATION_URL}?{urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    """POST to LinkedIn's token endpoint. Returns the raw JSON response
    (access_token, expires_in, scope, ...). Raises requests.RequestException
    on failure -- callers must handle that explicitly rather than assume success."""
    resp = requests.post(
        TOKEN_URL,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": code,
            "client_id": os.environ["LINKEDIN_CLIENT_ID"],
            "client_secret": os.environ["LINKEDIN_CLIENT_SECRET"],
            "redirect_uri": os.environ["LINKEDIN_REDIRECT_URI"],
        },
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def fetch_userinfo(access_token: str) -> dict:
    """GET the userinfo endpoint. Returns sub/name/given_name/family_name/
    picture/email/email_verified -- email/email_verified may be absent
    per LinkedIn's own documented response schema."""
    resp = requests.get(
        USERINFO_URL,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=15,
    )
    resp.raise_for_status()
    return resp.json()


def build_connection_record(token_response: dict, userinfo: dict) -> dict:
    """What gets stored in app_state under 'linkedin_connection'. Deliberately
    excludes nothing from the access token's reach beyond what's needed to
    display connection status and disconnect -- but the raw access_token
    itself IS stored (there is no way to call the userinfo endpoint again
    without it), so this value must never be rendered in any template or
    logged. Only app/dashboard/server.py's own disconnect route reads it
    back out, and only to send the revoke-adjacent "forget it" action --
    LinkedIn has no token-revocation endpoint in the open-permissions
    tier, so "disconnect" here means "this app deletes its copy," not
    "LinkedIn is notified." Say that plainly in the UI."""
    now = time.time()
    expires_in = token_response.get("expires_in", 0)
    return {
        "access_token": token_response.get("access_token"),
        "connected_at": now,
        "expires_at": now + expires_in,
        "scope": token_response.get("scope", SCOPE),
        "name": userinfo.get("name"),
        "given_name": userinfo.get("given_name"),
        "family_name": userinfo.get("family_name"),
        "email": userinfo.get("email"),
        "picture": userinfo.get("picture"),
    }


def is_token_expired(connection: Optional[dict]) -> bool:
    if not connection or not connection.get("expires_at"):
        return True
    return time.time() >= connection["expires_at"]
