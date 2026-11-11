import base64
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from google_oauth.web import (
    AUTH_URI,
    REVOKE_URI,
    TOKEN_URI,
    OAuthClient,
    OAuthExchangeError,
    authorization_url,
    exchange_code,
    new_pkce,
    new_state,
    revoke,
)

CLIENT = OAuthClient(
    "client-id", "client-secret", "https://app.example.com/oauth/google/callback"
)
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=UTC)


class _Response:
    def __init__(self, status: int, body):
        self.status_code = status
        self._body = body

    def json(self):
        if isinstance(self._body, Exception):
            raise self._body
        return self._body


class _Session:
    def __init__(self, response=None, exc: Exception | None = None):
        self.response = response
        self.exc = exc
        self.calls: list[tuple[str, dict]] = []

    def post(self, url, data=None, timeout=None):
        self.calls.append((url, data))
        if self.exc:
            raise self.exc
        return self.response


def _id_token(claims: dict) -> str:
    def part(obj) -> str:
        return base64.urlsafe_b64encode(json.dumps(obj).encode()).rstrip(b"=").decode()

    return f"{part({'alg': 'none', 'typ': 'JWT'})}.{part(claims)}.c2ln"


def test_new_pkce_challenge_is_s256_of_verifier():
    verifier, challenge = new_pkce()

    expected = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        .rstrip(b"=")
        .decode()
    )
    assert challenge == expected
    assert 43 <= len(verifier) <= 128


def test_new_state_is_random():
    assert new_state() != new_state()


def test_authorization_url_asks_for_offline_consent():
    url = authorization_url(
        CLIENT,
        ["openid", "scope-a"],
        state="st",
        code_challenge="ch",
        login_hint="a@b.cz",
    )

    parsed = urlparse(url)
    query = {k: v[0] for k, v in parse_qs(parsed.query).items()}
    assert f"{parsed.scheme}://{parsed.netloc}{parsed.path}" == AUTH_URI
    assert query == {
        "client_id": "client-id",
        "redirect_uri": CLIENT.redirect_uri,
        "response_type": "code",
        "scope": "openid scope-a",
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": "st",
        "code_challenge": "ch",
        "code_challenge_method": "S256",
        "login_hint": "a@b.cz",
    }


@pytest.mark.parametrize(("scopes", "state"), [([], "st"), (["a"], "")])
def test_authorization_url_requires_scopes_and_state(scopes, state):
    with pytest.raises(ValueError, match="required"):
        authorization_url(CLIENT, scopes, state=state)


def test_oauth_client_requires_all_fields():
    with pytest.raises(ValueError, match="needs client_id"):
        OAuthClient("id", "", "https://x")


def test_exchange_code_returns_grant_with_email():
    session = _Session(
        _Response(
            200,
            {
                "access_token": "at",
                "refresh_token": "rt",
                "expires_in": 3599,
                "scope": "openid https://www.googleapis.com/auth/drive.file",
                "id_token": _id_token({"email": "owner@firma.cz"}),
            },
        )
    )

    grant = exchange_code(
        CLIENT, "code-1", code_verifier="ver", session=session, now=NOW
    )

    url, data = session.calls[0]
    assert url == TOKEN_URI
    assert data["grant_type"] == "authorization_code"
    assert data["code"] == "code-1"
    assert data["code_verifier"] == "ver"
    assert data["redirect_uri"] == CLIENT.redirect_uri
    assert grant.refresh_token == "rt"
    assert grant.expires_at == NOW + timedelta(seconds=3599)
    assert grant.scopes == ("openid", "https://www.googleapis.com/auth/drive.file")
    assert grant.email == "owner@firma.cz"
    assert grant.to_secret(CLIENT) == {
        "provider": "google",
        "clientId": "client-id",
        "clientSecret": "client-secret",
        "refreshToken": "rt",
        "tokenUri": TOKEN_URI,
        "scopes": "openid https://www.googleapis.com/auth/drive.file",
        "email": "owner@firma.cz",
    }


def test_exchange_code_refused_raises_with_reason():
    session = _Session(
        _Response(400, {"error": "invalid_grant", "error_description": "Bad Request"})
    )

    with pytest.raises(OAuthExchangeError, match="invalid_grant"):
        exchange_code(CLIENT, "used-code", session=session)


def test_exchange_code_without_refresh_token_raises():
    session = _Session(_Response(200, {"access_token": "at", "expires_in": 10}))

    with pytest.raises(OAuthExchangeError, match="no refresh token"):
        exchange_code(CLIENT, "code", session=session)


def test_exchange_code_network_error_is_auth_error():
    session = _Session(exc=requests.ConnectionError("down"))

    with pytest.raises(Exception, match="Could not reach Google"):
        exchange_code(CLIENT, "code", session=session)


@pytest.mark.parametrize(
    ("status", "expected"), [(200, True), (400, True), (503, False)]
)
def test_revoke(status, expected):
    session = _Session(_Response(status, {}))

    assert revoke("rt", session=session) is expected
    assert session.calls == [(REVOKE_URI, {"token": "rt"})]


def test_revoke_empty_token_does_nothing():
    session = _Session(_Response(200, {}))

    assert revoke("", session=session) is False
    assert session.calls == []
