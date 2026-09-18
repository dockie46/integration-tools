"""Tests for iCloud credential loading."""

from __future__ import annotations

from pathlib import Path

from icloud_read.auth import load_credentials


def test_load_credentials_with_calendars(tmp_path: Path) -> None:
    path = tmp_path / "icloud.json"
    path.write_text(
        '{"email": "a@icloud.com", "password": "xxxx", "calendars": ["Home", "Work"]}'
    )
    creds = load_credentials(path)
    assert creds.calendars == ("Home", "Work")


def test_load_credentials_without_calendars(tmp_path: Path) -> None:
    path = tmp_path / "icloud.json"
    path.write_text('{"email": "a@icloud.com", "password": "xxxx"}')
    creds = load_credentials(path)
    assert creds.calendars is None
