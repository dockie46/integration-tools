import pytest
from google_oauth.auth import CredentialsMissingError, GoogleAuthError
from google_oauth.scopes import SERVICE_SCOPES
from google_oauth.secret import (
    DEFAULT_TOKEN_URI,
    GoogleScopesMissingError,
    GoogleTokenRevokedError,
    credentials_from_secret,
    rotated_refresh_token,
    secret_scopes,
)

from google.auth.exceptions import RefreshError

DRIVE = SERVICE_SCOPES["drive"]
SECRET = {
    "clientId": "cid",
    "clientSecret": "csecret",
    "refreshToken": "rt",
    "scopes": "openid " + " ".join(DRIVE),
}


@pytest.fixture
def refresh_calls(monkeypatch):
    calls = []

    def fake_refresh(self, request):
        calls.append(self)
        self.token = "at"

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", fake_refresh)
    return calls


def test_builds_and_refreshes_credentials(refresh_calls):
    creds = credentials_from_secret(SECRET, required_scopes=DRIVE)

    assert refresh_calls == [creds]
    assert creds.client_id == "cid"
    assert creds.client_secret == "csecret"
    assert creds.refresh_token == "rt"
    assert creds.token_uri == DEFAULT_TOKEN_URI
    assert creds.scopes == ["openid", *DRIVE]


def test_accepts_snake_case_keys(refresh_calls):
    creds = credentials_from_secret(
        {"client_id": "cid", "client_secret": "cs", "refresh_token": "rt"},
        refresh=False,
    )

    assert creds.refresh_token == "rt"
    assert refresh_calls == []


def test_missing_keys_raise_credentials_missing():
    with pytest.raises(CredentialsMissingError, match="clientSecret, refreshToken"):
        credentials_from_secret({"clientId": "cid"})


def test_missing_scopes_raise_before_refresh(refresh_calls):
    with pytest.raises(GoogleScopesMissingError) as err:
        credentials_from_secret(SECRET, required_scopes=SERVICE_SCOPES["calendar"])

    assert err.value.missing == list(SERVICE_SCOPES["calendar"])
    assert refresh_calls == []


def test_invalid_grant_means_revoked(monkeypatch):
    def fail(self, request):
        raise RefreshError(
            "invalid_grant: Token has been expired or revoked.",
            {"error": "invalid_grant"},
        )

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", fail)

    with pytest.raises(GoogleTokenRevokedError):
        credentials_from_secret(SECRET)


def test_other_refresh_errors_are_auth_errors(monkeypatch):
    def fail(self, request):
        raise RefreshError("internal_failure")

    monkeypatch.setattr("google.oauth2.credentials.Credentials.refresh", fail)

    with pytest.raises(GoogleAuthError, match="Failed to refresh") as err:
        credentials_from_secret(SECRET)
    assert not isinstance(err.value, GoogleTokenRevokedError)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("a b", ["a", "b"]), ("a,b", ["a", "b"]), (["a", " b "], ["a", "b"]), (None, [])],
)
def test_secret_scopes_formats(raw, expected):
    secret = {} if raw is None else {"Scopes": raw}

    assert secret_scopes(secret) == expected


def test_rotated_refresh_token(refresh_calls):
    creds = credentials_from_secret(SECRET, refresh=False)
    assert rotated_refresh_token(creds, SECRET) is None

    creds._refresh_token = "rt-2"
    assert rotated_refresh_token(creds, SECRET) == "rt-2"
