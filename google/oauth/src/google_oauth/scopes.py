"""OAuth scopes per Google service.

A connection asks for the union of the services it needs (``scopes_for("calendar", "drive")``);
each client then checks only the scopes it uses, so one token can serve several services.
"""

from __future__ import annotations

IDENTITY_SCOPES: tuple[str, ...] = (
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
)

SERVICE_SCOPES: dict[str, tuple[str, ...]] = {
    # Mail
    "gmail": ("https://www.googleapis.com/auth/gmail.readonly",),
    # Calendar: write events (bookings) + list calendars and free/busy.
    "calendar": (
        "https://www.googleapis.com/auth/calendar.events",
        "https://www.googleapis.com/auth/calendar.readonly",
    ),
    "calendar_readonly": ("https://www.googleapis.com/auth/calendar.readonly",),
    # Create calendars of its own (e.g. one per meeting room) and share them.
    "calendar_manage": (
        "https://www.googleapis.com/auth/calendar.app.created",
        "https://www.googleapis.com/auth/calendar.acls",
    ),
    # Drive: only files and folders this app created or the user picked for it.
    "drive": ("https://www.googleapis.com/auth/drive.file",),
}


def scopes_for(*services: str, identity: bool = True) -> list[str]:
    """Union of the scopes for ``services`` in a stable order (plus openid + email by default)."""
    unknown = [s for s in services if s not in SERVICE_SCOPES]
    if unknown:
        known = ", ".join(sorted(SERVICE_SCOPES))
        raise ValueError(
            f"Unknown Google service(s): {', '.join(unknown)}. Known: {known}"
        )

    ordered: list[str] = list(IDENTITY_SCOPES) if identity else []
    for service in services:
        for scope in SERVICE_SCOPES[service]:
            if scope not in ordered:
                ordered.append(scope)
    return ordered


def missing_scopes(
    granted: list[str] | tuple[str, ...] | set[str] | None,
    required: list[str] | tuple[str, ...],
) -> list[str]:
    """Required scopes not in ``granted`` (identity scopes never count as missing)."""
    have = set(granted or ())
    return [s for s in required if s not in have and s not in IDENTITY_SCOPES]
