"""Shared Google OAuth for local desktop clients and headless Lambda."""

from __future__ import annotations

import json
import os
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

# Grow this list as packages are added. Re-run `*-read auth` after changing it.
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/calendar.readonly",
]

TOKEN_ENV = "GOOGLE_TOKEN_JSON"
TOKEN_PATH_ENV = "GOOGLE_TOKEN_PATH"
# Back-compat with the original Gmail Lambda env names.
_LEGACY_TOKEN_ENV = "GMAIL_TOKEN_JSON"
_LEGACY_TOKEN_PATH_ENV = "GMAIL_TOKEN_PATH"


class CredentialsMissingError(RuntimeError):
    """Raised when OAuth client credentials or a token are not present."""


class GoogleAuthError(RuntimeError):
    """Raised when authentication or token refresh fails."""


def _scopes_satisfied(creds: Credentials, scopes: list[str]) -> bool:
    granted = set(creds.scopes or [])
    if not granted:
        return True
    return set(scopes).issubset(granted)


def _env(name: str, legacy: str) -> str:
    return os.environ.get(name, "").strip() or os.environ.get(legacy, "").strip()


def load_credentials(
    credentials_path: Path,
    token_path: Path,
    *,
    allow_browser: bool = True,
    scopes: list[str] | None = None,
) -> Credentials:
    """Load a cached OAuth token, refreshing or re-authenticating as needed.

    Never logs token contents. Raises CredentialsMissingError with a precise
    remediation message when credentials.json is absent.
    """
    required_scopes = scopes or SCOPES
    creds: Credentials | None = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), required_scopes)
        except ValueError as exc:
            raise GoogleAuthError(f"Stored token at {token_path} is invalid: {exc}") from exc

    if creds and creds.valid and _scopes_satisfied(creds, required_scopes):
        return creds

    if creds and creds.expired and creds.refresh_token and _scopes_satisfied(creds, required_scopes):
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise GoogleAuthError(f"Failed to refresh Google token: {exc}") from exc
        token_path.write_text(creds.to_json())
        return creds

    if not allow_browser:
        raise GoogleAuthError(
            "Google token is missing, expired, or missing required scopes, "
            "and interactive login is not available.\n"
            "Run `gmail-read auth` or `gcal-read auth` on a machine with a browser, "
            f"then set {TOKEN_ENV} (or {TOKEN_PATH_ENV}) to that token.json."
        )

    if not credentials_path.exists():
        raise CredentialsMissingError(
            "Google OAuth credentials not found.\n"
            f"Expected file: {credentials_path}\n\n"
            "To fix this:\n"
            "  1. Go to https://console.cloud.google.com/apis/credentials\n"
            "  2. Create an OAuth client ID of type 'Desktop app'\n"
            "  3. Download the JSON file\n"
            f"  4. Save it as: {credentials_path}"
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), required_scopes)
        creds = flow.run_local_server(port=0)
    except Exception as exc:
        raise GoogleAuthError(f"Google authentication failed: {exc}") from exc

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def load_credentials_from_env(*, scopes: list[str] | None = None) -> Credentials:
    """Load a refreshable user token from the environment (Lambda / headless)."""
    required_scopes = scopes or SCOPES
    raw = _env(TOKEN_ENV, _LEGACY_TOKEN_ENV)
    token_path_value = _env(TOKEN_PATH_ENV, _LEGACY_TOKEN_PATH_ENV)
    token_path = Path(token_path_value) if token_path_value else None

    if not raw and token_path is not None and token_path.exists():
        raw = token_path.read_text()

    if not raw:
        raise CredentialsMissingError(
            "Google token not found in the environment.\n"
            f"Set {TOKEN_ENV} to the contents of token.json, or {TOKEN_PATH_ENV} "
            "to its path.\n"
            "Create that file first with `gmail-read auth` or `gcal-read auth`."
        )

    try:
        info = json.loads(raw)
        creds = Credentials.from_authorized_user_info(info, required_scopes)
    except (json.JSONDecodeError, ValueError) as exc:
        raise GoogleAuthError(f"Google token in the environment is invalid: {exc}") from exc

    if not _scopes_satisfied(creds, required_scopes):
        raise GoogleAuthError(
            "Google token is missing required scopes. "
            "Re-run local auth and update the environment token."
        )

    if creds.valid:
        return creds

    if creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise GoogleAuthError(f"Failed to refresh Google token: {exc}") from exc
        if token_path is not None:
            token_path.parent.mkdir(parents=True, exist_ok=True)
            token_path.write_text(creds.to_json())
        return creds

    raise GoogleAuthError(
        "Google token in the environment is not valid and has no refresh_token. "
        "Run local auth and copy the new token.json."
    )
