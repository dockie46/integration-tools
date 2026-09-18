"""Factory / registry over configured providers."""

from __future__ import annotations

import os
from pathlib import Path

from .base import Provider
from .catalog import PROVIDER_TYPES
from .models import CalendarItem, CalendarRefItem, EmailItem


class Providers:
    """Load N integrations and read mail/calendar across a subset of them.

    Example::

        p = Providers.discover()
        emails = p.read_emails("google", "icloud", limit=5)
        events = p.read_calendar(limit=10)  # next 10 across all loaded
        print(p.list_calendars("google"))   # discover calendar ids/names
    """

    def __init__(self, providers: dict[str, Provider]) -> None:
        self._providers = dict(providers)

    @classmethod
    def discover(
        cls,
        *,
        root: Path | None = None,
        allow_browser: bool = True,
        providers: list[str] | tuple[str, ...] | None = None,
    ) -> Providers:
        """Load every registered provider that has credentials under ``root`` or env.

        Optional ``providers`` / env ``PROVIDERS`` (comma-separated) limits which
        types are considered, e.g. ``PROVIDERS=google`` or ``google,icloud``.
        """
        base = root or Path.cwd()
        wanted = providers
        if wanted is None:
            raw = (os.environ.get("PROVIDERS") or "").strip()
            if raw:
                wanted = tuple(part.strip() for part in raw.split(",") if part.strip())

        loaded: dict[str, Provider] = {}
        for provider_type in PROVIDER_TYPES:
            if wanted is not None and provider_type.name not in wanted:
                continue
            if provider_type.available(base):
                loaded[provider_type.name] = provider_type.create(
                    base,
                    allow_browser=allow_browser,
                )
        return cls(loaded)

    @classmethod
    def load(cls, *names: str, root: Path | None = None, allow_browser: bool = True) -> Providers:
        """Load only the named providers (must have credentials)."""
        all_found = cls.discover(root=root, allow_browser=allow_browser)
        missing = [n for n in names if n not in all_found._providers]
        if missing:
            raise KeyError(
                f"Providers not configured or credentials missing: {', '.join(missing)}"
            )
        return cls({n: all_found._providers[n] for n in names})

    @property
    def names(self) -> list[str]:
        return list(self._providers)

    def get(self, name: str) -> Provider:
        try:
            return self._providers[name]
        except KeyError as exc:
            raise KeyError(f"Unknown provider {name!r}. Loaded: {self.names}") from exc

    def _selected(self, names: tuple[str, ...]) -> list[Provider]:
        if not self._providers:
            raise RuntimeError(
                "No providers loaded. Add credentials under credentials/ and call discover()."
            )
        if not names:
            return list(self._providers.values())
        return [self.get(name) for name in names]

    def read_emails(self, *provider_names: str, limit: int = 10) -> list[EmailItem]:
        """Read recent emails — ``limit`` per selected provider."""
        items: list[EmailItem] = []
        for provider in self._selected(provider_names):
            items.extend(provider.read_emails(limit=limit))
        return items

    def list_calendars(self, *provider_names: str) -> list[CalendarRefItem]:
        """List calendars for selected providers (default: all loaded)."""
        items: list[CalendarRefItem] = []
        for provider in self._selected(provider_names):
            items.extend(provider.list_calendars())
        return items

    def read_calendar(
        self,
        *provider_names: str,
        limit: int = 10,
        calendars: list[str] | None = None,
    ) -> list[CalendarItem]:
        """Read upcoming events, merged by start — at most ``limit`` total.

        ``calendars`` overrides each provider's configured calendar filter for this call
        (Google: calendar ids, iCloud: display names).
        """
        items: list[CalendarItem] = []
        for provider in self._selected(provider_names):
            items.extend(provider.read_calendar(limit=limit, calendars=calendars))
        items.sort(key=lambda item: item.start)
        return items[:limit]
