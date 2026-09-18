import json

import pytest

from gmail_read.auth import (
    TOKEN_ENV,
    TOKEN_PATH_ENV,
    CredentialsMissingError,
    GmailAuthError,
    load_credentials,
    load_credentials_from_env,
)


class _FakeCreds:
    def __init__(
        self,
        *,
        valid: bool,
        expired: bool = False,
        refresh_token: str | None = "refresh-token",
        scopes: list[str] | None = None,
    ):
        self.valid = valid
        self.expired = expired
        self.refresh_token = refresh_token
        self.scopes = scopes
        self.refresh_calls = 0

    def refresh(self, _request):
        self.refresh_calls += 1
        self.valid = True
        self.expired = False

    def to_json(self):
        return json.dumps({"token": "new-access-token", "refresh_token": self.refresh_token})


def test_load_credentials_from_env_missing(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.delenv(TOKEN_PATH_ENV, raising=False)
    monkeypatch.delenv("GMAIL_TOKEN_JSON", raising=False)
    monkeypatch.delenv("GMAIL_TOKEN_PATH", raising=False)
    with pytest.raises(CredentialsMissingError):
        load_credentials_from_env()


def test_load_credentials_from_env_invalid_json(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, "not-json")
    with pytest.raises(GmailAuthError, match="invalid"):
        load_credentials_from_env()


def test_load_credentials_from_env_valid_token(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, json.dumps({"token": "access-token"}))
    creds = _FakeCreds(valid=True)
    monkeypatch.setattr(
        "google_oauth.auth.Credentials.from_authorized_user_info",
        lambda *_args, **_kwargs: creds,
    )
    assert load_credentials_from_env() is creds
    assert creds.refresh_calls == 0


def test_load_credentials_from_env_refreshes_expired(monkeypatch, tmp_path):
    token_path = tmp_path / "token.json"
    monkeypatch.setenv(TOKEN_ENV, json.dumps({"refresh_token": "refresh-token"}))
    monkeypatch.setenv(TOKEN_PATH_ENV, str(token_path))
    creds = _FakeCreds(valid=False, expired=True)
    monkeypatch.setattr(
        "google_oauth.auth.Credentials.from_authorized_user_info",
        lambda *_args, **_kwargs: creds,
    )

    result = load_credentials_from_env()
    assert result is creds
    assert creds.refresh_calls == 1
    assert token_path.exists()


def test_load_credentials_from_env_expired_without_refresh(monkeypatch):
    monkeypatch.setenv(TOKEN_ENV, json.dumps({"token": "stale"}))
    creds = _FakeCreds(valid=False, expired=True, refresh_token=None)
    monkeypatch.setattr(
        "google_oauth.auth.Credentials.from_authorized_user_info",
        lambda *_args, **_kwargs: creds,
    )
    with pytest.raises(GmailAuthError, match="no refresh_token"):
        load_credentials_from_env()


def test_load_credentials_without_browser_when_token_missing(tmp_path):
    with pytest.raises(GmailAuthError, match="interactive login is not available"):
        load_credentials(tmp_path / "credentials.json", tmp_path / "token.json", allow_browser=False)


def test_load_credentials_from_env_accepts_legacy_gmail_env(monkeypatch):
    monkeypatch.delenv(TOKEN_ENV, raising=False)
    monkeypatch.setenv("GMAIL_TOKEN_JSON", json.dumps({"token": "access-token"}))
    creds = _FakeCreds(valid=True)
    monkeypatch.setattr(
        "google_oauth.auth.Credentials.from_authorized_user_info",
        lambda *_args, **_kwargs: creds,
    )
    assert load_credentials_from_env() is creds
