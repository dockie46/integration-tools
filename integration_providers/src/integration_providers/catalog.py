"""Known provider types — add one line when introducing a new integration."""

from __future__ import annotations

from .base import ProviderType
from .google_provider import GoogleProvider
from .icloud_provider import ICloudProvider
from .microsoft_provider import MicrosoftProvider

PROVIDER_TYPES: tuple[type[ProviderType], ...] = (
    GoogleProvider,
    ICloudProvider,
    MicrosoftProvider,
)
