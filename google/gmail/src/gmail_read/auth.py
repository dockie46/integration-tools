"""Gmail auth — thin wrapper around shared google_oauth."""

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

# Back-compat alias used by existing Gmail callers/tests.
GmailAuthError = GoogleAuthError

__all__ = [
    "SCOPES",
    "TOKEN_ENV",
    "TOKEN_PATH_ENV",
    "CredentialsMissingError",
    "GmailAuthError",
    "GoogleAuthError",
    "load_credentials",
    "load_credentials_from_env",
]
