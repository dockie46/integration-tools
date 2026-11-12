from datetime import UTC, datetime

import gdrive.client as drive_module
import pytest
from fake_drive import FOLDER, FakeDrive
from gdrive import DriveClient, DriveError, split_key

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)


class _FakeDownload:
    def __init__(self, buffer, request):
        self._buffer = buffer
        self._file_id = request[1]

    def next_chunk(self):
        self._buffer.write(DRIVE.contents[self._file_id])
        return None, True


DRIVE: FakeDrive


@pytest.fixture
def drive(monkeypatch):
    global DRIVE  # - the fake download reads the same fake
    DRIVE = FakeDrive()
    monkeypatch.setattr(drive_module, "MediaIoBaseDownload", _FakeDownload)
    return DRIVE


def _folders(fake: FakeDrive) -> list[str]:
    return sorted(f["name"] for f in fake.items.values() if f["mimeType"] == FOLDER)


@pytest.mark.parametrize("key", ["", "/a.pdf", "a/../b.pdf"])
def test_split_key_rejects(key):
    with pytest.raises(ValueError, match="Invalid file key"):
        split_key(key)


def test_put_creates_root_and_nested_folders_once(drive):
    client = DriveClient(drive)

    client.put("smlouvy/2026/a.pdf", b"one", "application/pdf")
    client.put("smlouvy/2026/b.pdf", b"two", "application/pdf")

    assert _folders(drive) == ["2026", "Softwareify", "smlouvy"]
    assert [c for c in drive.calls if c[0] == "create"] == [
        ("create", "Softwareify"),
        ("create", "smlouvy"),
        ("create", "2026"),
        ("create", "a.pdf"),
        ("create", "b.pdf"),
    ]


def test_put_same_key_updates_instead_of_duplicating(drive):
    client = DriveClient(drive)
    first = client.put("a.txt", b"v1", "text/plain")

    second = client.put("a.txt", b"version 2", "text/plain")

    assert second.file_id == first.file_id
    assert second.size == 9
    assert ("update", first.file_id) in drive.calls


def test_get_and_stat_and_delete(drive):
    client = DriveClient(drive)
    client.put("docs/x.txt", b"hello", "text/plain")

    info, data = client.get("docs/x.txt")
    assert (data, info.name, info.size) == (b"hello", "x.txt", 5)
    assert client.stat("docs/x.txt").content_type == "text/plain"

    assert client.delete("docs/x.txt") is True
    assert client.delete("docs/x.txt") is False
    assert client.stat("docs/x.txt") is None
    with pytest.raises(FileNotFoundError):
        client.get("docs/x.txt")


def test_lookup_of_missing_folder_does_not_create_it(drive):
    client = DriveClient(drive)

    assert client.stat("nothing/here.txt") is None
    assert _folders(drive) == ["Softwareify"]


def test_configured_root_folder_is_used(drive):
    drive.items["root-1"] = {
        "id": "root-1",
        "name": "Shared",
        "parents": ["root"],
        "mimeType": FOLDER,
    }
    client = DriveClient(drive, root_folder_id="root-1")

    client.put("a.txt", b"x", "text/plain")

    created = next(f for f in drive.items.values() if f["name"] == "a.txt")
    assert created["parents"] == ["root-1"]
    assert "Softwareify" not in _folders(drive)


def test_names_with_quotes_are_escaped(drive):
    client = DriveClient(drive)
    client.put("O'Brien/smlouva.pdf", b"x", "application/pdf")

    assert client.stat("O'Brien/smlouva.pdf") is not None
    assert any("O\\'Brien" in q for kind, q in drive.calls if kind == "list")


class _Response:
    def __init__(self, status, location=None):
        self.status_code = status
        self.headers = {"Location": location} if location else {}


class _Session:
    def __init__(self, response):
        self.response = response
        self.calls = []

    def post(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("post", url, json, headers))
        return self.response

    def patch(self, url, json=None, headers=None, timeout=None):
        self.calls.append(("patch", url, json, headers))
        return self.response


def test_start_upload_returns_session_url_with_cors_origin(drive):
    session = _Session(_Response(200, "https://upload.example/session-1"))
    client = DriveClient(drive, session=session)

    url, expires = client.start_upload(
        "video/big.mp4",
        "video/mp4",
        size=10_000_000,
        origin="http://localhost:5173",
        now=NOW,
    )

    assert url == "https://upload.example/session-1"
    assert expires == datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    kind, target, body, headers = session.calls[0]
    assert kind == "post"
    assert target.endswith("uploadType=resumable")
    assert body["name"] == "big.mp4"
    assert headers["Origin"] == "http://localhost:5173"
    assert headers["X-Upload-Content-Type"] == "video/mp4"
    assert headers["X-Upload-Content-Length"] == "10000000"


def test_start_upload_over_existing_file_patches_it(drive):
    client = DriveClient(
        drive, session=_Session(_Response(200, "https://upload.example/s"))
    )
    existing = client.put("a.txt", b"x", "text/plain")

    client.start_upload("a.txt", "text/plain")

    kind, target, _, _ = client._session.calls[0]
    assert kind == "patch"
    assert f"/{existing.file_id}?uploadType=resumable" in target


def test_start_upload_failure_raises(drive):
    client = DriveClient(drive, session=_Session(_Response(403)))

    with pytest.raises(DriveError) as err:
        client.start_upload("a.txt", "text/plain")
    assert err.value.status == 403


def test_account(drive):
    assert DriveClient(drive).account() == "owner@firma.cz"
