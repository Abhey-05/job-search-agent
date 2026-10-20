"""LinkedIn OAuth: URL building, state validation, and the dashboard
routes -- all against mocked HTTP, since no real LinkedIn Developer app
credentials exist for this project. Confirms: minimum scope only
(openid profile email, never w_member_social), CSRF state is single-use,
a mismatched state is rejected, and the feature is a no-op without the
three required env vars (never silently "half works")."""
from unittest.mock import patch

import pytest

from app import linkedin_oauth
from app.db import get_db


LINKEDIN_ENV = {
    "LINKEDIN_CLIENT_ID": "test-client-id",
    "LINKEDIN_CLIENT_SECRET": "test-client-secret",
    "LINKEDIN_REDIRECT_URI": "https://example.com/auth/linkedin/callback",
}


def test_not_configured_without_all_three_env_vars(monkeypatch):
    monkeypatch.delenv("LINKEDIN_CLIENT_ID", raising=False)
    monkeypatch.delenv("LINKEDIN_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("LINKEDIN_REDIRECT_URI", raising=False)
    assert linkedin_oauth.is_configured() is False

    monkeypatch.setenv("LINKEDIN_CLIENT_ID", "x")
    assert linkedin_oauth.is_configured() is False  # still missing secret/redirect


def test_configured_with_all_three(monkeypatch):
    for k, v in LINKEDIN_ENV.items():
        monkeypatch.setenv(k, v)
    assert linkedin_oauth.is_configured() is True


def test_authorization_url_requests_minimum_scope_only(monkeypatch):
    for k, v in LINKEDIN_ENV.items():
        monkeypatch.setenv(k, v)
    state = linkedin_oauth.generate_state()
    url = linkedin_oauth.build_authorization_url(state)

    assert url.startswith("https://www.linkedin.com/oauth/v2/authorization?")
    assert "response_type=code" in url
    assert f"state={state}" in url
    assert "scope=openid+profile+email" in url
    assert "w_member_social" not in url  # never requested -- not needed, not asked for


def test_state_is_random_and_long_enough():
    s1 = linkedin_oauth.generate_state()
    s2 = linkedin_oauth.generate_state()
    assert s1 != s2
    assert len(s1) >= 32


def test_token_exchange_and_userinfo_use_documented_endpoints(monkeypatch):
    for k, v in LINKEDIN_ENV.items():
        monkeypatch.setenv(k, v)

    class FakeTokenResp:
        def raise_for_status(self): pass
        def json(self): return {"access_token": "fake-token", "expires_in": 5184000, "scope": "openid profile email"}

    class FakeUserinfoResp:
        def raise_for_status(self): pass
        def json(self): return {"sub": "abc", "name": "Abhey Garg", "email": "abhey@example.com"}

    with patch("app.linkedin_oauth.requests.post", return_value=FakeTokenResp()) as mock_post:
        token_response = linkedin_oauth.exchange_code_for_token("fake-code")
    assert mock_post.call_args.args[0] == "https://www.linkedin.com/oauth/v2/accessToken"
    assert mock_post.call_args.kwargs["data"]["grant_type"] == "authorization_code"
    assert token_response["access_token"] == "fake-token"

    with patch("app.linkedin_oauth.requests.get", return_value=FakeUserinfoResp()) as mock_get:
        userinfo = linkedin_oauth.fetch_userinfo("fake-token")
    assert mock_get.call_args.args[0] == "https://api.linkedin.com/v2/userinfo"
    assert mock_get.call_args.kwargs["headers"]["Authorization"] == "Bearer fake-token"
    assert userinfo["name"] == "Abhey Garg"

    connection = linkedin_oauth.build_connection_record(token_response, userinfo)
    assert connection["name"] == "Abhey Garg"
    assert connection["email"] == "abhey@example.com"
    assert connection["access_token"] == "fake-token"
    assert linkedin_oauth.is_token_expired(connection) is False
    assert linkedin_oauth.is_token_expired(None) is True
    assert linkedin_oauth.is_token_expired({}) is True


def test_oauth_state_is_single_use(tmp_path):
    db = get_db(f"sqlite:///{tmp_path / 'app.db'}")
    db.set_oauth_state("linkedin", "abc123")
    assert db.pop_oauth_state("linkedin") == "abc123"
    assert db.pop_oauth_state("linkedin") is None  # consumed -- cannot be replayed
    db.close()


def test_linkedin_connection_round_trip(tmp_path):
    db = get_db(f"sqlite:///{tmp_path / 'app.db'}")
    assert db.get_linkedin_connection() is None
    db.set_linkedin_connection({"name": "Abhey Garg", "email": "abhey@example.com", "access_token": "secret"})
    stored = db.get_linkedin_connection()
    assert stored["name"] == "Abhey Garg"
    db.clear_linkedin_connection()
    assert db.get_linkedin_connection() is None
    db.close()


def test_dashboard_connect_route_requires_configuration(tmp_path, monkeypatch):
    monkeypatch.delenv("LINKEDIN_CLIENT_ID", raising=False)
    monkeypatch.delenv("LINKEDIN_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("LINKEDIN_REDIRECT_URI", raising=False)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")

    from app.dashboard.server import create_app
    client = create_app().test_client()
    resp = client.get("/auth/linkedin/connect", auth=("admin", "changeme"))
    assert resp.status_code == 400


def test_dashboard_callback_rejects_mismatched_state(tmp_path, monkeypatch):
    for k, v in LINKEDIN_ENV.items():
        monkeypatch.setenv(k, v)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'app.db'}")

    from app.dashboard.server import create_app
    client = create_app().test_client()

    connect_resp = client.get("/auth/linkedin/connect", auth=("admin", "changeme"))
    assert connect_resp.status_code == 302
    assert "linkedin.com/oauth/v2/authorization" in connect_resp.headers["Location"]

    callback_resp = client.get(
        "/auth/linkedin/callback?code=fake&state=WRONG_STATE",
        auth=("admin", "changeme"),
    )
    assert callback_resp.status_code == 401
