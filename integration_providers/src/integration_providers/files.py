"""One way to store files, whichever service holds them.

A file has the app's own ``key`` (unique and never derived from what people type, e.g. ``<company>/<file id>``),
a ``name`` people see (may repeat, can change) and a ``folder`` for people browsing the store. ``put`` returns a
``FileInfo`` whose ``ref`` is the stable reference the app keeps; get / stat / delete / rename / download_url take
that ref. Renaming in the app changes its database; ``rename`` only mirrors the name where people can see it (Drive).

The connection's secret says where credentials come from; ``location`` (from the app's storage settings: bucket,
region, prefix, folderId, rootFolderName) says where files go and wins over the same keys in the secret::

    store = open_file_store(secret, location={"bucket": "docs", "prefix": "prod"})
    info = store.put("c1/f9", data, "application/pdf", name="smlouva.pdf", folder="Smlouvy")
    store.get(info.ref)

Missing files raise ``FileNotFoundError``; anything the service refuses raises ``FileStoreError``.
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
    ref: str
    size: int
    content_type: str
    name: str = ""
    modified: datetime | None = None

    def to_dict(self) -> dict:
        data = asdict(self)
        data["modified"] = self.modified.isoformat() if self.modified else None
        return data


@dataclass(frozen=True, slots=True)
class UploadTarget:
    """Where the browser sends a large file itself: ``method`` to ``url`` with ``headers``, before ``expires_at``.
    ``ref`` is known up front on S3; on Drive it is empty and ``locate(key)`` finds the file afterwards."""

    provider: str
    key: str
    url: str
    method: str
    expires_at: datetime
    headers: dict[str, str] = field(default_factory=dict)
    ref: str = ""

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
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        name: str | None = None,
        folder: str | None = None,
    ) -> FileInfo: ...

    def locate(self, key: str, *, folder: str | None = None) -> FileInfo | None: ...

    def stat(self, ref: str) -> FileInfo | None: ...

    def get(self, ref: str) -> tuple[FileInfo, bytes]: ...

    def delete(self, ref: str) -> bool: ...

    def rename(self, ref: str, name: str) -> None: ...

    def upload_target(
        self,
        key: str,
        content_type: str,
        *,
        name: str | None = None,
        folder: str | None = None,
        size: int | None = None,
        origin: str | None = None,
    ) -> UploadTarget: ...

    def download_url(self, ref: str, *, filename: str | None = None) -> str | None:
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

    def _info(self, raw: Any) -> FileInfo:
        return FileInfo(
            self.name, raw.file_id, raw.size, raw.content_type, raw.name, raw.modified
        )

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        name: str | None = None,
        folder: str | None = None,
    ) -> FileInfo:
        return self._info(
            self._guard(
                lambda: self._client.put(
                    key, data, content_type, name=name, folder=folder
                )
            )
        )

    def locate(self, key: str, *, folder: str | None = None) -> FileInfo | None:  # noqa: ARG002 - found by key
        raw = self._guard(lambda: self._client.locate(key))
        return self._info(raw) if raw else None

    def stat(self, ref: str) -> FileInfo | None:
        raw = self._guard(lambda: self._client.stat(ref))
        return self._info(raw) if raw else None

    def get(self, ref: str) -> tuple[FileInfo, bytes]:
        raw, data = self._guard(lambda: self._client.get(ref))
        return self._info(raw), data

    def delete(self, ref: str) -> bool:
        return bool(self._guard(lambda: self._client.delete(ref)))

    def rename(self, ref: str, name: str) -> None:
        self._guard(lambda: self._client.rename(ref, name))

    def upload_target(
        self,
        key: str,
        content_type: str,
        *,
        name: str | None = None,
        folder: str | None = None,
        size: int | None = None,
        origin: str | None = None,
    ) -> UploadTarget:
        url, expires = self._guard(
            lambda: self._client.start_upload(
                key, content_type, name=name, folder=folder, size=size, origin=origin
            )
        )
        return UploadTarget(
            self.name, key, url, "PUT", expires, {"Content-Type": content_type}
        )

    def download_url(self, ref: str, *, filename: str | None = None) -> str | None:  # noqa: ARG002 - FileStore shape
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

    def _info(self, raw: Any, name: str = "") -> FileInfo:
        return FileInfo(
            self.name, raw.key, raw.size, raw.content_type, name, raw.modified
        )

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        name: str | None = None,
        folder: str | None = None,
    ) -> FileInfo:
        raw = self._guard(
            lambda: self._client.put(key, data, content_type, name=name, folder=folder)
        )
        return self._info(raw, name or "")

    def locate(self, key: str, *, folder: str | None = None) -> FileInfo | None:
        raw = self._guard(lambda: self._client.locate(key, folder=folder))
        return self._info(raw) if raw else None

    def stat(self, ref: str) -> FileInfo | None:
        raw = self._guard(lambda: self._client.stat(ref))
        return self._info(raw) if raw else None

    def get(self, ref: str) -> tuple[FileInfo, bytes]:
        raw, data = self._guard(lambda: self._client.get(ref))
        return self._info(raw), data

    def delete(self, ref: str) -> bool:
        return bool(self._guard(lambda: self._client.delete(ref)))

    def rename(self, ref: str, name: str) -> None:
        """Nothing to do: the name people see lives in the app and in the download link."""

    def upload_target(
        self,
        key: str,
        content_type: str,
        *,
        name: str | None = None,  # noqa: ARG002 - the app keeps the name
        folder: str | None = None,
        size: int | None = None,  # noqa: ARG002 - a presigned PUT needs no size
        origin: str | None = None,  # noqa: ARG002 - S3 CORS is set on the bucket
    ) -> UploadTarget:
        url, expires, ref = self._guard(
            lambda: self._client.upload_url(key, content_type, folder=folder)
        )
        return UploadTarget(
            self.name, key, url, "PUT", expires, {"Content-Type": content_type}, ref
        )

    def download_url(self, ref: str, *, filename: str | None = None) -> str | None:
        url, _ = self._guard(lambda: self._client.download_url(ref, filename=filename))
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

LOCATION_KEYS = (
    "bucket",
    "region",
    "prefix",
    "endpointUrl",
    "folderId",
    "rootFolderName",
)


def open_file_store(
    secret: Mapping[str, Any],
    *,
    provider: str | None = None,
    location: Mapping[str, Any] | None = None,
) -> FileStore:
    """The file store for a connection. ``provider`` overrides the secret's ``provider``; ``location`` (non-secret
    storage settings) overrides the same keys in the secret. Credentials are never taken from ``location``."""
    merged = {str(k): v for k, v in secret.items()}
    for key, value in (location or {}).items():
        if key not in LOCATION_KEYS:
            raise FileStoreError(
                f"Unknown storage setting {key!r}. Known: {', '.join(LOCATION_KEYS)}"
            )
        if value is None or str(value).strip() == "":
            continue
        for existing in [k for k in merged if k.lower() == key.lower()]:
            del merged[existing]
        merged[key] = value
    lower = {k.lower(): v for k, v in merged.items()}
    name = (provider or str(lower.get("provider") or "")).strip().lower()
    factory = FILE_STORES.get(name)
    if factory is None:
        known = ", ".join(sorted(FILE_STORES))
        raise FileStoreError(
            f"No file storage for provider {name or '(none)'!r}. Known: {known}"
        )
    return factory(merged)
