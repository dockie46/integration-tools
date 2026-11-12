from datetime import UTC, datetime

import gdrive.client as drive_module
import pytest
from fake_drive import FOLDER, FakeDrive
from gdrive import DriveClient, DriveError, split_key
from gdrive.client import KEY_PROPERTY

NOW = datetime(2026, 11, 12, 10, 0, tzinfo=UTC)
KEY = "f30e0f64-893e-48df-bfbd-8500ad7ecb8b/5b1c2c47-9a1f-4c55-8f0a-0d2a1f0c1b11"

DRIVE: FakeDrive


class _FakeDownload:
    def __init__(self, buffer, request):
        self._buffer = buffer
        self._file_id = request[1]

    def next_chunk(self):
        self._buffer.write(DRIVE.contents[self._file_id])
        return None, True


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


def test_put_shows_the_name_in_the_folder_and_keeps_the_key_on_the_file(drive):
    client = DriveClient(drive)

    info = client.put(
        KEY, b"%PDF", "application/pdf", name="smlouva.pdf", folder="Smlouvy/2026"
    )

    item = drive.items[info.file_id]
    assert item["name"] == "smlouva.pdf"
    assert item["appProperties"] == {KEY_PROPERTY: KEY}
    assert _folders(drive) == ["2026", "Smlouvy", "Softwareify"]
    assert client.locate(KEY).file_id == info.file_id


def test_same_name_twice_makes_two_files(drive):
    client = DriveClient(drive)

    a = client.put(
        "c1/f1", b"a", "application/pdf", name="smlouva.pdf", folder="Smlouvy"
    )
    b = client.put(
        "c1/f2", b"b", "application/pdf", name="smlouva.pdf", folder="Smlouvy"
    )

    assert a.file_id != b.file_id
    assert sorted(
        f["name"] for f in drive.items.values() if f["mimeType"] != FOLDER
    ) == ["smlouva.pdf", "smlouva.pdf"]


def test_same_key_again_replaces_content(drive):
    client = DriveClient(drive)
    first = client.put("c1/f1", b"v1", "text/plain", name="a.txt")

    second = client.put("c1/f1", b"version 2", "text/plain", name="a.txt")

    assert second.file_id == first.file_id
    assert second.size == 9


def test_get_stat_rename_delete_by_id(drive):
    client = DriveClient(drive)
    ref = client.put("c1/f1", b"hello", "text/plain", name="a.txt").file_id

    info, data = client.get(ref)
    assert (data, info.name) == (b"hello", "a.txt")
    assert client.rename(ref, " b.txt ").name == "b.txt"
    assert client.stat(ref).name == "b.txt"
    assert client.locate("c1/f1").file_id == ref

    assert client.delete(ref) is True
    assert client.delete(ref) is False
    assert client.stat(ref) is None
    with pytest.raises(FileNotFoundError):
        client.get(ref)


def test_rename_needs_a_name(drive):
    with pytest.raises(ValueError, match="needs a name"):
        DriveClient(drive).rename("id1", " ")


def test_long_keys_are_hashed_into_the_property(drive):
    client = DriveClient(drive)
    long_key = "c1/" + "x" * 200

    ref = client.put(long_key, b"x", "text/plain").file_id

    stored = drive.items[ref]["appProperties"][KEY_PROPERTY]
    assert stored.startswith("sha256:")
    assert client.locate(long_key).file_id == ref


def test_configured_root_folder_is_used(drive):
    drive.items["root-1"] = {
        "id": "root-1",
        "name": "Shared",
        "parents": ["root"],
        "mimeType": FOLDER,
    }
    client = DriveClient(drive, root_folder_id="root-1")

    ref = client.put("c1/f1", b"x", "text/plain", name="a.txt").file_id

    assert drive.items[ref]["parents"] == ["root-1"]
    assert "Softwareify" not in _folders(drive)


def test_folder_names_with_quotes_are_escaped(drive):
    client = DriveClient(drive)

    client.put("c1/f1", b"x", "application/pdf", name="x.pdf", folder="O'Brien")
    client.put("c1/f2", b"x", "application/pdf", name="y.pdf", folder="O'Brien")

    assert _folders(drive).count("O'Brien") == 1
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


def test_start_upload_sets_name_folder_key_and_origin(drive):
    session = _Session(_Response(200, "https://upload.example/session-1"))
    client = DriveClient(drive, session=session)

    url, expires = client.start_upload(
        "c1/f9",
        "video/mp4",
        name="prezentace.mp4",
        folder="Videa",
        size=10_000_000,
        origin="http://localhost:5173",
        now=NOW,
    )

    assert url == "https://upload.example/session-1"
    assert expires == datetime(2026, 11, 19, 10, 0, tzinfo=UTC)
    kind, target, body, headers = session.calls[0]
    assert kind == "post"
    assert target.endswith("uploadType=resumable")
    assert body["name"] == "prezentace.mp4"
    assert body["appProperties"] == {KEY_PROPERTY: "c1/f9"}
    assert headers["Origin"] == "http://localhost:5173"
    assert headers["X-Upload-Content-Length"] == "10000000"
    assert "Videa" in _folders(drive)


def test_start_upload_for_a_known_key_patches_that_file(drive):
    client = DriveClient(
        drive, session=_Session(_Response(200, "https://upload.example/s"))
    )
    ref = client.put("c1/f1", b"x", "text/plain", name="a.txt").file_id

    client.start_upload("c1/f1", "text/plain")

    kind, target, _, _ = client._session.calls[0]
    assert kind == "patch"
    assert f"/{ref}?uploadType=resumable" in target


def test_start_upload_failure_raises(drive):
    client = DriveClient(drive, session=_Session(_Response(403)))

    with pytest.raises(DriveError) as err:
        client.start_upload("c1/f1", "text/plain")
    assert err.value.status == 403


def test_account(drive):
    assert DriveClient(drive).account() == "owner@firma.cz"
