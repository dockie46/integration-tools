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


def test_factory_provider_override(monkeypatch):
    monkeypatch.setitem(files_module.FILE_STORES, "s3", lambda _secret: "s3-store")

    assert open_file_store({"provider": "google"}, provider="s3") == "s3-store"


class _Drive:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail

    def _maybe_fail(self):
        if self.fail:
            raise self.fail

    def put(self, key, data, content_type):
        self._maybe_fail()
        return DriveFile("f1", key.split("/")[-1], len(data), content_type, NOW)

    def get(self, key):
        return DriveFile("f1", "a.txt", 2, "text/plain"), b"hi"

    def stat(self, key):
        return None

    def delete(self, key):
        return True

    def start_upload(self, key, content_type, *, size=None, origin=None):
        return f"https://upload/{key}", NOW

    def account(self):
        self._maybe_fail()
        return "owner@firma.cz"

    def root_id(self):
        return "root"


def test_drive_store_maps_results():
    store = DriveFileStore(_Drive())

    info = store.put("a/b.pdf", b"123", "application/pdf")
    assert info.to_dict() == {
        "provider": "gdrive",
        "key": "a/b.pdf",
        "size": 3,
        "content_type": "application/pdf",
        "modified": NOW.isoformat(),
    }
    assert store.get("a.txt")[1] == b"hi"
    assert store.stat("x") is None
    assert store.delete("x") is True
    target = store.upload_target(
        "big.mp4", "video/mp4", size=5, origin="http://localhost:5173"
    )
    assert (target.url, target.method, target.headers) == (
        "https://upload/big.mp4",
        "PUT",
        {"Content-Type": "video/mp4"},
    )
    assert store.download_url("a.txt") is None
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
        store.put("a.txt", b"x")
    assert store.check().ok is False


class _S3:
    def __init__(self, fail: Exception | None = None):
        self.fail = fail

    def put(self, key, data, content_type):
        if self.fail:
            raise self.fail
        return S3File(key, len(data), content_type)

    def download_url(self, key, *, filename=None):
        return f"https://s3/{key}?dl={filename}", NOW

    def upload_url(self, key, content_type):
        return f"https://s3/{key}?put", NOW

    def check(self):
        if self.fail:
            raise self.fail
        return "docs"


def test_s3_store_maps_results_and_errors():
    store = S3FileStore(_S3())

    assert store.put("a.txt", b"xy", "text/plain").size == 2
    assert store.download_url("a.txt", filename="a.txt") == "https://s3/a.txt?dl=a.txt"
    assert store.upload_target("a.txt", "text/plain").url == "https://s3/a.txt?put"
    assert store.check().detail == "docs"

    failing = S3FileStore(_S3(fail=S3Error("S3 check failed: bucket not found", "404")))
    assert failing.check().to_dict() == {
        "provider": "s3",
        "ok": False,
        "detail": "S3 check failed: bucket not found",
    }
    with pytest.raises(FileStoreError, match="bucket not found"):
        failing.put("a.txt", b"x")
