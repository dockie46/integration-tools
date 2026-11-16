"""App-only auth for Microsoft Graph (client-credentials grant).

A Microsoft 365 connection is a tenant-wide app registration (Entra ID) with admin consent, not a per-user
OAuth token: the stored secret carries ``tenantId``, ``clientId`` and ``clientSecret``. Graph is then called
without a signed-in user, scoped to the room mailboxes by an Application Access Policy on the tenant side.
"""

from __future__ import annotations

import time
from collections.abc import Mapping
from typing import Any, Protocol

DEFAULT_AUTHORITY = "https://login.microsoftonline.com"
GRAPH_DEFAULT_SCOPE = "https://graph.microsoft.com/.default"
GRAPH_BASE_URL = "https://graph.microsoft.com/v1.0"

# Refresh a little before the token actually expires.
_EXPIRY_SKEW_SECONDS = 60


class MicrosoftAuthError(RuntimeError):
    """The account must be connected again (missing/invalid app registration, consent revoked)."""


class MicrosoftCredentialsError(MicrosoftAuthError):
    """The stored secret is missing ``tenantId`` / ``clientId`` / ``clientSecret``."""


class AppCredentials:
    """One tenant's app registration, read from the connection secret."""

    __slots__ = ("tenant_id", "client_id", "client_secret", "authority")

    def __init__(self, tenant_id: str, client_id: str, client_secret: str, *, authority: str = DEFAULT_AUTHORITY) -> None:
        self.tenant_id = tenant_id
        self.client_id = client_id
        self.client_secret = client_secret
        self.authority = authority.rstrip("/")

    @classmethod
    def from_secret(cls, secret: Mapping[str, Any]) -> AppCredentials:
        def pick(*names: str) -> str:
            for name in names:
                value = next((v for k, v in secret.items() if str(k).lower() == name.lower()), None)
                if value is not None and str(value).strip():
                    return str(value).strip()
            return ""

        tenant_id = pick("tenantId", "tenant", "tenant_id")
        client_id = pick("clientId", "client_id", "appId")
        client_secret = pick("clientSecret", "client_secret", "secret")
        if not (tenant_id and client_id and client_secret):
            raise MicrosoftCredentialsError(
                "Microsoft 365 connection needs tenantId, clientId and clientSecret."
            )
        authority = pick("authority") or DEFAULT_AUTHORITY
        return cls(tenant_id, client_id, client_secret, authority=authority)

    @property
    def token_url(self) -> str:
        return f"{self.authority}/{self.tenant_id}/oauth2/v2.0/token"


class TokenProvider(Protocol):
    def token(self) -> str: ...


class AppOnlyToken:
    """Fetches and caches a client-credentials access token for Graph."""

    def __init__(self, credentials: AppCredentials, session: Any, *, scope: str = GRAPH_DEFAULT_SCOPE) -> None:
        self._credentials = credentials
        self._session = session
        self._scope = scope
        self._value = ""
        self._expires_at = 0.0

    def token(self) -> str:
        if self._value and time.time() < self._expires_at:
            return self._value
        response = self._session.post(
            self._credentials.token_url,
            data={
                "client_id": self._credentials.client_id,
                "client_secret": self._credentials.client_secret,
                "scope": self._scope,
                "grant_type": "client_credentials",
            },
            timeout=30,
        )
        payload: dict[str, Any] = {}
        try:
            payload = response.json()
        except ValueError:
            payload = {}
        if response.status_code != 200 or not payload.get("access_token"):
            reason = payload.get("error_description") or payload.get("error") or f"HTTP {response.status_code}"
            raise MicrosoftAuthError(f"Microsoft token request failed: {reason}")
        self._value = str(payload["access_token"])
        self._expires_at = time.time() + max(0, int(payload.get("expires_in") or 0) - _EXPIRY_SKEW_SECONDS)
        return self._value
