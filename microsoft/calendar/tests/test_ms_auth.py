import pytest
from mscal_read.auth import (
    AppCredentials,
    AppOnlyToken,
    MicrosoftAuthError,
    MicrosoftCredentialsError,
)


class _Resp:
    def __init__(self, status_code: int, body: dict) -> None:
        self.status_code = status_code
        self._body = body

    def json(self) -> dict:
        return self._body


class _Session:
    def __init__(self, *responses: _Resp) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url, *, data=None, timeout=None):
        self.calls.append({"url": url, "data": data})
        return self._responses.pop(0)


def test_credentials_from_secret_accepts_aliases():
    creds = AppCredentials.from_secret({"tenant": "t-1", "appId": "c-1", "clientSecret": "s-1"})
    assert (creds.tenant_id, creds.client_id, creds.client_secret) == ("t-1", "c-1", "s-1")
    assert creds.token_url == "https://login.microsoftonline.com/t-1/oauth2/v2.0/token"


def test_credentials_require_all_three_fields():
    with pytest.raises(MicrosoftCredentialsError):
        AppCredentials.from_secret({"tenantId": "t-1", "clientId": "c-1"})


def test_token_is_fetched_and_cached():
    creds = AppCredentials.from_secret({"tenantId": "t", "clientId": "c", "clientSecret": "s"})
    session = _Session(_Resp(200, {"access_token": "tok-1", "expires_in": 3600}))

    token = AppOnlyToken(creds, session)
    assert token.token() == "tok-1"
    assert token.token() == "tok-1"  # cached: no second request
    assert len(session.calls) == 1
    assert session.calls[0]["data"]["grant_type"] == "client_credentials"
    assert session.calls[0]["data"]["scope"] == "https://graph.microsoft.com/.default"


def test_token_failure_raises_auth_error():
    creds = AppCredentials.from_secret({"tenantId": "t", "clientId": "c", "clientSecret": "s"})
    session = _Session(_Resp(401, {"error": "invalid_client", "error_description": "bad secret"}))

    with pytest.raises(MicrosoftAuthError, match="bad secret"):
        AppOnlyToken(creds, session).token()
