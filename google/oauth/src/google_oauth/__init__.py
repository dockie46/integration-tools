"""Shared Google OAuth helpers for integration-tools packages."""

from .auth import (
    SCOPES,
    TOKEN_ENV,
    TOKEN_PATH_ENV,
    CredentialsMissingError,
    GoogleAuthError,
    load_credentials,
    load_credentials_from_env,
)

__all__ = [
    "SCOPES",
    "TOKEN_ENV",
    "TOKEN_PATH_ENV",
    "CredentialsMissingError",
    "GoogleAuthError",
    "load_credentials",
    "load_credentials_from_env",
]

__version__ = "0.1.0"
