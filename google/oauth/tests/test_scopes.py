import pytest
from google_oauth.scopes import (
    IDENTITY_SCOPES,
    SERVICE_SCOPES,
    missing_scopes,
    scopes_for,
)


def test_scopes_for_unions_services_in_order_with_identity():
    scopes = scopes_for("calendar", "drive", "calendar")

    assert scopes[: len(IDENTITY_SCOPES)] == list(IDENTITY_SCOPES)
    assert scopes[len(IDENTITY_SCOPES) :] == [
        *SERVICE_SCOPES["calendar"],
        *SERVICE_SCOPES["drive"],
    ]


def test_scopes_for_without_identity():
    assert scopes_for("drive", identity=False) == list(SERVICE_SCOPES["drive"])


def test_scopes_for_unknown_service_raises():
    with pytest.raises(ValueError, match="Unknown Google service"):
        scopes_for("photos")


def test_missing_scopes_ignores_identity():
    required = [*IDENTITY_SCOPES, *SERVICE_SCOPES["drive"]]

    assert missing_scopes(SERVICE_SCOPES["drive"], required) == []
    assert missing_scopes([], required) == list(SERVICE_SCOPES["drive"])
