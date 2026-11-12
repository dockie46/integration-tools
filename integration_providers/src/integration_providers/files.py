"""One way to store files, whichever service holds them.

The caller says "put this file at this key"; the connection's secret decides where it goes::

    store = open_file_store(secret)          # secret["provider"]: "google" / "gdrive" -> Drive, "s3" / "aws" -> S3
    store.put("smlouvy/2026/najemni.pdf", data, "application/pdf")
    target = store.upload_target("video/velke.mp4", "video/mp4", size=…, origin="https://app.example.com")

Keys are relative paths (``a/b/c.pdf``): no leading slash, no ``..``. Missing files raise ``FileNotFoundError``,
anything the service refuses raises ``FileStoreError``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Protocol


class FileStoreError(RuntimeError):
    """The storage service refused a request or the connection is not usable."""


@dataclass(frozen=True, slots=True)
class FileInfo:
    provider: str
    key: str
    size: int
    content_type: str
    modified: datetime | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["modified"] = self.modified.isoformat() if self.modified else None
        return data


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Where the browser sends a large file itself: ``method`` to ``url`` with ``headers``, before ``expires_at``."""

    provider: str
    key: str
    url: str
    method: str
    expires_at: datetime
    headers: dict[str, str] = field(default_factory=dict)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["expires_at"] = self.expires_at.isoformat()
        return data


@dataclass(frozen=True, slots=True)
class StoreCheck:
    provider: str
    ok: bool
    detail: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


class FileStore(Protocol):
    @property
    def name(self) -> str: ...

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> FileInfo: ...

    def get(self, key: str) -> tuple[FileInfo, bytes]: ...

    def stat(self, key: str) -> FileInfo | None: ...

    def delete(self, key: str) -> bool: ...

    def upload_target(
        self,
        key: str,
        content_type: str,
        *,
        size: int | None = None,
        origin: str | None = None,
    ) -> UploadTarget: ...

    def download_url(self, key: str, *, filename: str | None = None) -> str | None:
        """A link the browser can fetch directly, or None when the service has none (Drive): stream via get()."""
        ...

    def check(self) -> StoreCheck: ...


class DriveFileStore:
    name = "gdrive"

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_secret(cls, secret: Mapping[str, Any]) -> DriveFileStore:
        from gdrive import DriveClient

        return cls(DriveClient.from_secret(secret))

    def _info(self, key: str, raw: Any) -> FileInfo:
        return FileInfo(self.name, key, raw.size, raw.content_type, raw.modified)

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> FileInfo:
        return self._info(
            key, self._guard(lambda: self._client.put(key, data, content_type))
        )

    def get(self, key: str) -> tuple[FileInfo, bytes]:
        raw, data = self._guard(lambda: self._client.get(key))
        return self._info(key, raw), data

    def stat(self, key: str) -> FileInfo | None:
        raw = self._guard(lambda: self._client.stat(key))
        return self._info(key, raw) if raw else None

    def delete(self, key: str) -> bool:
        return bool(self._guard(lambda: self._client.delete(key)))

    def upload_target(
        self,
        key: str,
        content_type: str,
        *,
        size: int | None = None,
        origin: str | None = None,
    ) -> UploadTarget:
        url, expires = self._guard(
            lambda: self._client.start_upload(
                key, content_type, size=size, origin=origin
            )
        )
        return UploadTarget(
            self.name, key, url, "PUT", expires, {"Content-Type": content_type}
        )

    def download_url(self, key: str, *, filename: str | None = None) -> str | None:  # noqa: ARG002 - FileStore shape
        return None

    def check(self) -> StoreCheck:
        try:
            account = self._client.account()
            self._client.root_id()
        except Exception as exc:  # - reported to the user, not raised
            return StoreCheck(self.name, False, str(exc))
        return StoreCheck(self.name, True, account)

    @staticmethod
    def _guard(call: Callable[[], Any]) -> Any:
        from gdrive import DriveError

        try:
            return call()
        except DriveError as exc:
            raise FileStoreError(str(exc)) from exc


class S3FileStore:
    name = "s3"

    def __init__(self, client: Any) -> None:
        self._client = client

    @classmethod
    def from_secret(cls, secret: Mapping[str, Any]) -> S3FileStore:
        from s3files import S3Files

        return cls(S3Files.from_secret(secret))

    def _info(self, raw: Any) -> FileInfo:
        return FileInfo(self.name, raw.key, raw.size, raw.content_type, raw.modified)

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> FileInfo:
        return self._info(
            self._guard(lambda: self._client.put(key, data, content_type))
        )

    def get(self, key: str) -> tuple[FileInfo, bytes]:
        raw, data = self._guard(lambda: self._client.get(key))
        return self._info(raw), data

    def stat(self, key: str) -> FileInfo | None:
        raw = self._guard(lambda: self._client.stat(key))
        return self._info(raw) if raw else None

    def delete(self, key: str) -> bool:
        return bool(self._guard(lambda: self._client.delete(key)))

    def upload_target(
        self,
        key: str,
        content_type: str,
        *,
        size: int | None = None,  # noqa: ARG002 - presigned PUT needs no size
        origin: str | None = None,  # noqa: ARG002 - S3 CORS is set on the bucket
    ) -> UploadTarget:
        url, expires = self._guard(lambda: self._client.upload_url(key, content_type))
        return UploadTarget(
            self.name, key, url, "PUT", expires, {"Content-Type": content_type}
        )

    def download_url(self, key: str, *, filename: str | None = None) -> str | None:
        url, _ = self._guard(lambda: self._client.download_url(key, filename=filename))
        return url

    def check(self) -> StoreCheck:
        from s3files import S3Error

        try:
            bucket = self._client.check()
        except S3Error as exc:
            return StoreCheck(self.name, False, str(exc))
        return StoreCheck(self.name, True, bucket)

    @staticmethod
    def _guard(call: Callable[[], Any]) -> Any:
        from s3files import S3Error

        try:
            return call()
        except S3Error as exc:
            raise FileStoreError(str(exc)) from exc


FILE_STORES: dict[str, Callable[[Mapping[str, Any]], FileStore]] = {
    "gdrive": DriveFileStore.from_secret,
    "google": DriveFileStore.from_secret,
    "s3": S3FileStore.from_secret,
    "aws": S3FileStore.from_secret,
}


def open_file_store(
    secret: Mapping[str, Any], *, provider: str | None = None
) -> FileStore:
    """The file store for a connection. ``provider`` overrides the secret's ``provider`` field."""
    lower = {str(k).lower(): v for k, v in secret.items()}
    name = (provider or str(lower.get("provider") or "")).strip().lower()
    factory = FILE_STORES.get(name)
    if factory is None:
        known = ", ".join(sorted(FILE_STORES))
        raise FileStoreError(
            f"No file storage for provider {name or '(none)'!r}. Known: {known}"
        )
    return factory(secret)
