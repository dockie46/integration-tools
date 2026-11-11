"""Server-side (web) OAuth for multi-tenant apps: redirect the user, exchange the code, keep the refresh token.

Unlike ``auth.load_credentials`` (desktop loopback flow, token.json on disk) nothing here touches the
filesystem: the caller stores ``TokenGrant.to_secret()`` wherever it keeps credentials (e.g. AWS Secrets
Manager) and later rebuilds credentials with ``secret.credentials_from_secret``.

Flow::

    verifier, challenge = new_pkce()
    url = authorization_url(client, scopes_for("calendar"), state=state, code_challenge=challenge)
    # ... user consents, Google redirects to client.redirect_uri?code=...&state=...
    grant = exchange_code(client, code, code_verifier=verifier)
    store(grant.to_secret(client))
"""

from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any
from urllib.parse import urlencode

import requests

from google.auth import jwt

from .auth import GoogleAuthError

AUTH_URI = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URI = "https://oauth2.googleapis.com/token"  # - endpoint, not a secret
REVOKE_URI = "https://oauth2.googleapis.com/revoke"

_TIMEOUT = 30


class OAuthExchangeError(GoogleAuthError):
    """Google refused the authorization code (expired, reused, wrong redirect URI or verifier)."""


@dataclass(frozen=True, slots=True)
class OAuthClient:
    """A Google OAuth client of type 'Web application'."""

    client_id: str
    client_secret: str
    redirect_uri: str

    def __post_init__(self) -> None:
        if not (self.client_id and self.client_secret and self.redirect_uri):
            raise ValueError(
                "OAuthClient needs client_id, client_secret and redirect_uri."
            )


@dataclass(frozen=True, slots=True)
class TokenGrant:
    """Result of a code exchange. ``refresh_token`` is what must be stored."""

    access_token: str
    refresh_token: str
    expires_at: datetime
    scopes: tuple[str, ...]
    email: str = ""

    def to_secret(self, client: OAuthClient) -> dict[str, str]:
        """Flat string map to store as the connection's secret (read back by ``credentials_from_secret``)."""
        data = {
            "provider": "google",
            "clientId": client.client_id,
            "clientSecret": client.client_secret,
            "refreshToken": self.refresh_token,
            "tokenUri": TOKEN_URI,
            "scopes": " ".join(self.scopes),
        }
        if self.email:
            data["email"] = self.email
        return data


def new_state() -> str:
    """Opaque anti-CSRF value; the caller binds it to the company/user starting the flow."""
    return secrets.token_urlsafe(32)


def new_pkce() -> tuple[str, str]:
    """(code_verifier, code_challenge) for PKCE with S256."""
    verifier = secrets.token_urlsafe(64)[:96]
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


def authorization_url(
    client: OAuthClient,
    scopes: list[str] | tuple[str, ...],
    *,
    state: str,
    code_challenge: str | None = None,
    login_hint: str | None = None,
) -> str:
    """Consent URL. Always offline + prompt=consent so Google returns a refresh token every time."""
    if not scopes:
        raise ValueError("At least one scope is required.")
    if not state:
        raise ValueError("state is required (CSRF protection).")

    params: dict[str, str] = {
        "client_id": client.client_id,
        "redirect_uri": client.redirect_uri,
        "response_type": "code",
        "scope": " ".join(scopes),
        "access_type": "offline",
        "prompt": "consent",
        "include_granted_scopes": "true",
        "state": state,
    }
    if code_challenge:
        params["code_challenge"] = code_challenge
        params["code_challenge_method"] = "S256"
    if login_hint:
        params["login_hint"] = login_hint
    return f"{AUTH_URI}?{urlencode(params)}"


def exchange_code(
    client: OAuthClient,
    code: str,
    *,
    code_verifier: str | None = None,
    session: requests.Session | None = None,
    now: datetime | None = None,
) -> TokenGrant:
    """Swap the code from the redirect for tokens. Raises ``OAuthExchangeError`` when Google refuses it."""
    if not code:
        raise ValueError("code is required.")

    data = {
        "code": code,
        "client_id": client.client_id,
        "client_secret": client.client_secret,
        "redirect_uri": client.redirect_uri,
        "grant_type": "authorization_code",
    }
    if code_verifier:
        data["code_verifier"] = code_verifier

    http = session or requests
    try:
        response = http.post(TOKEN_URI, data=data, timeout=_TIMEOUT)
    except requests.RequestException as exc:
        raise GoogleAuthError(
            f"Could not reach Google to finish sign-in: {exc}"
        ) from exc

    body = _json(response)
    if response.status_code != 200 or "error" in body:
        error = body.get("error") or f"HTTP {response.status_code}"
        detail = body.get("error_description") or ""
        raise OAuthExchangeError(
            f"Google refused the sign-in code ({error}). {detail}".strip()
        )

    refresh_token = str(body.get("refresh_token") or "")
    if not refresh_token:
        raise OAuthExchangeError(
            "Google returned no refresh token. Remove the app's access at "
            "https://myaccount.google.com/permissions and connect again."
        )

    issued = now or datetime.now(UTC)
    return TokenGrant(
        access_token=str(body.get("access_token") or ""),
        refresh_token=refresh_token,
        expires_at=issued + timedelta(seconds=int(body.get("expires_in") or 0)),
        scopes=tuple(str(body.get("scope") or "").split()),
        email=_email_from_id_token(body.get("id_token")),
    )


def revoke(token: str, *, session: requests.Session | None = None) -> bool:
    """Revoke a refresh (or access) token when a connection is removed. True when Google accepted it."""
    if not token:
        return False
    http = session or requests
    try:
        response = http.post(REVOKE_URI, data={"token": token}, timeout=_TIMEOUT)
    except requests.RequestException:
        return False
    # 400 invalid_token = already revoked or expired; nothing left to undo.
    return response.status_code in (200, 400)


def _json(response: Any) -> dict[str, Any]:
    try:
        body = response.json()
    except ValueError:
        return {}
    return body if isinstance(body, dict) else {}


def _email_from_id_token(id_token: Any) -> str:
    """Email claim of the id_token. Received straight from Google's token endpoint over TLS, so the
    signature is not re-verified; it is only used to label the connection, never to authenticate."""
    if not id_token:
        return ""
    try:
        claims = jwt.decode(str(id_token), verify=False)
    except (ValueError, TypeError):
        return ""
    return str(claims.get("email") or "")
