"""Credentials from a stored secret (multi-tenant / Lambda): no files, no environment.

The secret is the flat map written by ``web.TokenGrant.to_secret`` (camelCase keys; snake_case aliases are
accepted too)::

    {"clientId": "...", "clientSecret": "...", "refreshToken": "...", "tokenUri": "...", "scopes": "a b c"}
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from google.auth.exceptions import RefreshError
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials

from .auth import CredentialsMissingError, GoogleAuthError
from .scopes import missing_scopes

DEFAULT_TOKEN_URI = "https://oauth2.googleapis.com/token"  # - endpoint, not a secret


class GoogleTokenRevokedError(GoogleAuthError):
    """The refresh token no longer works (revoked, expired, password changed): the user must connect again."""


class GoogleScopesMissingError(GoogleAuthError):
    """The connection was granted fewer scopes than this client needs: connect again with the new service."""

    def __init__(self, missing: list[str]) -> None:
        super().__init__(
            "The Google connection is missing permissions: "
            + ", ".join(missing)
            + ". Connect the account again."
        )
        self.missing = missing


def _pick(secret: Mapping[str, Any], *keys: str) -> str:
    lower = {str(k).lower(): v for k, v in secret.items()}
    for key in keys:
        value = lower.get(key.lower())
        if value is not None and str(value).strip():
            return str(value).strip()
    return ""


def secret_scopes(secret: Mapping[str, Any]) -> list[str]:
    """Scopes recorded in the secret at connect time (space- or comma-separated string, or a list)."""
    raw = None
    for key, value in secret.items():
        if str(key).lower() == "scopes":
            raw = value
            break
    if raw is None:
        return []
    if isinstance(raw, list | tuple):
        return [str(s).strip() for s in raw if str(s).strip()]
    return [s for s in str(raw).replace(",", " ").split() if s]


def credentials_from_secret(
    secret: Mapping[str, Any],
    *,
    required_scopes: list[str] | tuple[str, ...] = (),
    refresh: bool = True,
    request: Request | None = None,
) -> Credentials:
    """Refreshable user credentials from a stored secret.

    Raises ``CredentialsMissingError`` (secret incomplete), ``GoogleScopesMissingError`` (needs reconnect with
    more services), ``GoogleTokenRevokedError`` (needs reconnect) or ``GoogleAuthError``.
    """
    client_id = _pick(secret, "clientId", "client_id")
    client_secret = _pick(secret, "clientSecret", "client_secret")
    refresh_token = _pick(secret, "refreshToken", "refresh_token")
    missing = [
        name
        for name, value in (
            ("clientId", client_id),
            ("clientSecret", client_secret),
            ("refreshToken", refresh_token),
        )
        if not value
    ]
    if missing:
        raise CredentialsMissingError(
            f"Google secret is missing {', '.join(missing)}. Connect the Google account again."
        )

    granted = secret_scopes(secret)
    if granted:
        lacking = missing_scopes(granted, required_scopes)
        if lacking:
            raise GoogleScopesMissingError(lacking)

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        client_id=client_id,
        client_secret=client_secret,
        token_uri=_pick(secret, "tokenUri", "token_uri") or DEFAULT_TOKEN_URI,
        # Ask for exactly what was granted; requesting more on refresh fails with invalid_scope.
        scopes=granted or list(required_scopes) or None,
    )
    if refresh:
        refresh_credentials(creds, request=request)
    return creds


def refresh_credentials(
    creds: Credentials, *, request: Request | None = None
) -> Credentials:
    """Refresh in place, mapping Google's answers to errors the caller can act on."""
    try:
        creds.refresh(request or Request())
    except RefreshError as exc:
        if _is_invalid_grant(exc):
            raise GoogleTokenRevokedError(
                "Google no longer accepts this connection (access was removed or the token expired). "
                "Connect the Google account again."
            ) from exc
        raise GoogleAuthError(f"Failed to refresh Google token: {exc}") from exc
    return creds


def rotated_refresh_token(creds: Credentials, secret: Mapping[str, Any]) -> str | None:
    """A new refresh token Google issued during refresh, if any; store it back into the secret."""
    current = _pick(secret, "refreshToken", "refresh_token")
    new = creds.refresh_token or ""
    return new if new and new != current else None


def _is_invalid_grant(exc: RefreshError) -> bool:
    text = " ".join(str(a) for a in exc.args)
    return "invalid_grant" in text
