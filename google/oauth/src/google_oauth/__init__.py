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
from .scopes import IDENTITY_SCOPES, SERVICE_SCOPES, missing_scopes, scopes_for
from .secret import (
    GoogleScopesMissingError,
    GoogleTokenRevokedError,
    credentials_from_secret,
    refresh_credentials,
    rotated_refresh_token,
    secret_scopes,
)
from .web import (
    OAuthClient,
    OAuthExchangeError,
    TokenGrant,
    authorization_url,
    exchange_code,
    new_pkce,
    new_state,
    revoke,
)

__all__ = [
    "IDENTITY_SCOPES",
    "SCOPES",
    "SERVICE_SCOPES",
    "TOKEN_ENV",
    "TOKEN_PATH_ENV",
    "CredentialsMissingError",
    "GoogleAuthError",
    "load_credentials",
    "GoogleScopesMissingError",
    "GoogleTokenRevokedError",
    "OAuthClient",
    "OAuthExchangeError",
    "TokenGrant",
    "authorization_url",
    "credentials_from_secret",
    "exchange_code",
    "load_credentials_from_env",
    "missing_scopes",
    "new_pkce",
    "new_state",
    "refresh_credentials",
    "revoke",
    "rotated_refresh_token",
    "scopes_for",
    "secret_scopes",
]

__version__ = "0.2.0"
