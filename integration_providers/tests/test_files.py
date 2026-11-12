"""File store factory and adapters (no network)."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from gdrive import DriveError, DriveFile
from s3files import S3Error, S3File

from integration_providers import files as files_module
from integration_providers.files import (
    DriveFileStore,
    FileStoreError,
    S3FileStore,
    open_file_store,
)

NOW = datetime(2026, 11, 12, tzinfo=UTC)


@pytest.mark.parametrize(
    ("provider", "expected"),
    [("google", "gdrive"), ("GDrive", "gdrive"), ("s3", "s3"), ("aws", "s3")],
)
def test_factory_picks_store_from_secret(monkeypatch, provider, expected):
    monkeypatch.setitem(
        files_module.FILE_STORES, provider.lower(), lambda _secret: expected
    )

    assert open_file_store({"Provider": provider}) == expected


def test_factory_unknown_provider():
    with pytest.raises(FileStoreError, match="No file storage for provider 'dropbox'"):
        open_file_store({"provider": "dropbox"})


def test_location_overrides_secret_but_not_credentials(monkeypatch):
    seen = {}
    monkeypatch.setitem(
        files_module.FILE_STORES, "s3", lambda secret: seen.update(secret) or "store"
    )

    open_file_store(
        {
            "provider": "s3",
            "Bucket": "from-secret",
            "accessKeyId": "AK",
            "secretAccessKey": "SK",
        },
        location={"bucket": "from-settings", "prefix": "prod", "region": ""},
    )

    assert seen == {
        "provider": "s3",
        "bucket": "from-settings",
        "prefix": "prod",
        "accessKeyId": "AK",
        "secretAccessKey": "SK",
    }


def test_location_rejects_credentials():
    with pytest.raises(FileStoreError, match="Unknown storage setting 'accessKeyId'"):
        open_file_store({"provider": "s3"}, location={"accessKeyId": "AK"})


class _Drive:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail
        self.calls = []

    def _maybe_fail(self):
        if self.fail:
            raise self.fail

    def put(self, key, data, content_type, *, name=None, folder=None):
        self._maybe_fail()
        self.calls.append(("put", key, name, folder))
        return DriveFile("drive-1", name or key, len(data), content_type, NOW)

    def locate(self, key):
        return (
            DriveFile("drive-1", "a.txt", 2, "text/plain") if key == "c1/f1" else None
        )

    def stat(self, file_id):
        return None

    def get(self, file_id):
        return DriveFile(file_id, "a.txt", 2, "text/plain"), b"hi"

    def delete(self, file_id):
        return True

    def rename(self, file_id, name):
        self.calls.append(("rename", file_id, name))

    def start_upload(
        self, key, content_type, *, name=None, folder=None, size=None, origin=None
    ):
        self.calls.append(("upload", key, name, folder, size, origin))
        return f"https://upload/{key}", NOW

    def account(self):
        self._maybe_fail()
        return "owner@firma.cz"

    def root_id(self):
        return "root"


def test_drive_store_uses_drive_id_as_ref():
    drive = _Drive()
    store = DriveFileStore(drive)

    info = store.put(
        "c1/f1", b"123", "application/pdf", name="smlouva.pdf", folder="Smlouvy"
    )
    assert info.to_dict() == {
        "provider": "gdrive",
        "ref": "drive-1",
        "size": 3,
        "content_type": "application/pdf",
        "name": "smlouva.pdf",
        "modified": NOW.isoformat(),
    }
    assert drive.calls[0] == ("put", "c1/f1", "smlouva.pdf", "Smlouvy")
    assert store.locate("c1/f1").ref == "drive-1"
    assert store.locate("other") is None
    assert store.get("drive-1")[1] == b"hi"
    store.rename("drive-1", "nova.pdf")
    assert ("rename", "drive-1", "nova.pdf") in drive.calls
    target = store.upload_target(
        "c1/f2",
        "video/mp4",
        name="v.mp4",
        folder="Videa",
        size=5,
        origin="http://localhost:5173",
    )
    assert (target.url, target.ref, target.headers) == (
        "https://upload/c1/f2",
        "",
        {"Content-Type": "video/mp4"},
    )
    assert drive.calls[-1] == (
        "upload",
        "c1/f2",
        "v.mp4",
        "Videa",
        5,
        "http://localhost:5173",
    )
    assert store.download_url("drive-1") is None
    assert store.check().to_dict() == {
        "provider": "gdrive",
        "ok": True,
        "detail": "owner@firma.cz",
    }


def test_drive_errors_become_file_store_errors():
    store = DriveFileStore(
        _Drive(fail=DriveError("Drive upload failed: no permission", 403))
    )

    with pytest.raises(FileStoreError, match="no permission"):
        store.put("c1/f1", b"x")
    assert store.check().ok is False


class _S3:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail

    def put(self, key, data, content_type, *, name=None, folder=None):
        if self.fail:
            raise self.fail
        return S3File(
            f"p/{folder}/{key}" if folder else f"p/{key}", len(data), content_type
        )

    def download_url(self, ref, *, filename=None):
        return f"https://s3/{ref}?dl={filename}", NOW

    def upload_url(self, key, content_type, *, folder=None):
        return f"https://s3/{key}?put", NOW, f"p/{folder}/{key}"

    def check(self):
        if self.fail:
            raise self.fail
        return "docs"


def test_s3_store_uses_object_key_as_ref():
    store = S3FileStore(_S3())

    info = store.put("c1/f1", b"xy", "text/plain", name="a.txt", folder="Docs")
    assert (info.ref, info.size, info.name) == ("p/Docs/c1/f1", 2, "a.txt")
    assert (
        store.download_url(info.ref, filename="a.txt")
        == "https://s3/p/Docs/c1/f1?dl=a.txt"
    )
    target = store.upload_target("c1/f2", "text/plain", folder="Docs")
    assert (target.url, target.ref) == ("https://s3/c1/f2?put", "p/Docs/c1/f2")
    store.rename(info.ref, "b.txt")  # nothing to do on S3
    assert store.check().detail == "docs"

    failing = S3FileStore(_S3(fail=S3Error("S3 check failed: bucket not found", "404")))
    assert failing.check().to_dict() == {
        "provider": "s3",
        "ok": False,
        "detail": "S3 check failed: bucket not found",
    }
    with pytest.raises(FileStoreError, match="bucket not found"):
        failing.put("c1/f1", b"x")
