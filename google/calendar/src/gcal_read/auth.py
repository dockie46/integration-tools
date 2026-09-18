"""Calendar auth — thin wrapper around shared google_oauth."""

from __future__ import annotations

from google_oauth.auth import (
    SCOPES,
    TOKEN_ENV,
    TOKEN_PATH_ENV,
    CredentialsMissingError,
    GoogleAuthError,
    load_credentials,
    load_credentials_from_env,
)

CalendarAuthError = GoogleAuthError

__all__ = [
    "SCOPES",
    "TOKEN_ENV",
    "TOKEN_PATH_ENV",
    "CredentialsMissingError",
    "CalendarAuthError",
    "GoogleAuthError",
    "load_credentials",
    "load_credentials_from_env",
]
