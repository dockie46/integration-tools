"""Drive as a file store: a key like ``smlouvy/2026/x.pdf`` is a file in nested folders under one root folder.

With the ``drive.file`` scope the app sees only what it created (or what the user picked for it), so the root
folder is the app's own: ``folderId`` from the secret, otherwise a folder named ``rootFolderName`` (default
"Softwareify") at the top of the user's Drive, created on first use.
"""

from __future__ import annotations

import io
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from google_oauth.scopes import SERVICE_SCOPES
from google_oauth.secret import credentials_from_secret
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload, MediaIoBaseUpload

from google.auth.transport.requests import AuthorizedSession

FOLDER_MIME = "application/vnd.google-apps.folder"
UPLOAD_URI = "https://www.googleapis.com/upload/drive/v3/files"
DEFAULT_ROOT_NAME = "Softwareify"
RESUMABLE_THRESHOLD = 5 * 1024 * 1024
# Google keeps a resumable upload session for a week.
SESSION_LIFETIME = timedelta(days=7)
_FIELDS = "id,name,mimeType,size,modifiedTime"


class DriveError(RuntimeError):
    """Drive refused a request. ``status`` is the HTTP status (403 no access, 404 not found, …)."""

    def __init__(self, message: str, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True, slots=True)
class DriveFile:
    file_id: str
    name: str
    size: int
    content_type: str
    modified: datetime | None = None


def split_key(key: str) -> list[str]:
    """``a/b/c.pdf`` -> ``["a", "b", "c.pdf"]``; rejects empty, absolute and ``..`` keys."""
    parts = [p for p in str(key).replace("\\", "/").split("/") if p]
    if not parts or str(key).startswith("/") or any(p in (".", "..") for p in parts):
        raise ValueError(f"Invalid file key {key!r}.")
    return parts


def _q(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "\\'")


def _status(exc: HttpError) -> int | None:
    return getattr(getattr(exc, "resp", None), "status", None)


def _error(action: str, exc: HttpError) -> DriveError:
    status = _status(exc)
    reason = {403: "no permission", 404: "not found"}.get(status or 0, str(exc))
    return DriveError(f"Drive {action} failed: {reason}", status)


def _file(raw: Mapping[str, Any]) -> DriveFile:
    modified = raw.get("modifiedTime")
    return DriveFile(
        file_id=str(raw.get("id") or ""),
        name=str(raw.get("name") or ""),
        size=int(raw.get("size") or 0),
        content_type=str(raw.get("mimeType") or "application/octet-stream"),
        modified=datetime.fromisoformat(str(modified).replace("Z", "+00:00"))
        if modified
        else None,
    )


class DriveClient:
    def __init__(
        self,
        service: Resource,
        *,
        session: Any = None,
        root_folder_id: str | None = None,
        root_folder_name: str = DEFAULT_ROOT_NAME,
    ) -> None:
        self.service = service
        self._session = session
        self._root_id = root_folder_id or None
        self._root_name = root_folder_name or DEFAULT_ROOT_NAME

    @classmethod
    def from_secret(cls, secret: Mapping[str, Any]) -> DriveClient:
        creds = credentials_from_secret(secret, required_scopes=SERVICE_SCOPES["drive"])
        lower = {str(k).lower(): v for k, v in secret.items()}
        return cls(
            build("drive", "v3", credentials=creds, cache_discovery=False),
            session=AuthorizedSession(creds),
            root_folder_id=str(lower.get("folderid") or "") or None,
            root_folder_name=str(lower.get("rootfoldername") or DEFAULT_ROOT_NAME),
        )

    # --- folders ---------------------------------------------------------------------------

    def _child(
        self, parent_id: str, name: str, *, folder: bool | None = None
    ) -> dict[str, Any] | None:
        query = (
            f"name = '{_q(name)}' and '{_q(parent_id)}' in parents and trashed = false"
        )
        if folder is True:
            query += f" and mimeType = '{FOLDER_MIME}'"
        elif folder is False:
            query += f" and mimeType != '{FOLDER_MIME}'"
        try:
            response = (
                self.service.files()
                .list(q=query, fields=f"files({_FIELDS})", pageSize=2, spaces="drive")
                .execute()
            )
        except HttpError as exc:
            raise _error("lookup", exc) from exc
        files = response.get("files") or []
        return files[0] if files else None

    def _create_folder(self, parent_id: str, name: str) -> str:
        body = {"name": name, "mimeType": FOLDER_MIME, "parents": [parent_id]}
        try:
            return str(
                self.service.files().create(body=body, fields="id").execute()["id"]
            )
        except HttpError as exc:
            raise _error("create folder", exc) from exc

    def root_id(self) -> str:
        if self._root_id is None:
            found = self._child("root", self._root_name, folder=True)
            self._root_id = (
                str(found["id"])
                if found
                else self._create_folder("root", self._root_name)
            )
        return self._root_id

    def _folder_for(self, folders: list[str], *, create: bool) -> str | None:
        parent = self.root_id()
        for name in folders:
            found = self._child(parent, name, folder=True)
            if found:
                parent = str(found["id"])
            elif create:
                parent = self._create_folder(parent, name)
            else:
                return None
        return parent

    def _find(self, key: str) -> tuple[str | None, dict[str, Any] | None, str]:
        parts = split_key(key)
        folder = self._folder_for(parts[:-1], create=False)
        if folder is None:
            return None, None, parts[-1]
        return folder, self._child(folder, parts[-1], folder=False), parts[-1]

    # --- files -----------------------------------------------------------------------------

    def put(
        self, key: str, data: bytes, content_type: str = "application/octet-stream"
    ) -> DriveFile:
        """Create or replace the file at ``key`` (folders are created as needed)."""
        parts = split_key(key)
        folder = self._folder_for(parts[:-1], create=True)
        assert folder is not None
        existing = self._child(folder, parts[-1], folder=False)
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype=content_type,
            resumable=len(data) > RESUMABLE_THRESHOLD,
        )
        try:
            if existing:
                raw = (
                    self.service.files()
                    .update(fileId=existing["id"], media_body=media, fields=_FIELDS)
                    .execute()
                )
            else:
                body = {"name": parts[-1], "parents": [folder]}
                raw = (
                    self.service.files()
                    .create(body=body, media_body=media, fields=_FIELDS)
                    .execute()
                )
        except HttpError as exc:
            raise _error("upload", exc) from exc
        return _file(raw)

    def stat(self, key: str) -> DriveFile | None:
        _, found, _ = self._find(key)
        return _file(found) if found else None

    def get(self, key: str) -> tuple[DriveFile, bytes]:
        _, found, _ = self._find(key)
        if not found:
            raise FileNotFoundError(f"No Drive file at '{key}'.")
        buffer = io.BytesIO()
        try:
            downloader = MediaIoBaseDownload(
                buffer, self.service.files().get_media(fileId=found["id"])
            )
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except HttpError as exc:
            raise _error("download", exc) from exc
        return _file(found), buffer.getvalue()

    def delete(self, key: str) -> bool:
        _, found, _ = self._find(key)
        if not found:
            return False
        try:
            self.service.files().delete(fileId=found["id"]).execute()
        except HttpError as exc:
            if _status(exc) == 404:
                return False
            raise _error("delete", exc) from exc
        return True

    def start_upload(
        self,
        key: str,
        content_type: str,
        *,
        size: int | None = None,
        origin: str | None = None,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        """A resumable upload session the browser PUTs the bytes to directly. ``origin`` (the app's web origin)
        makes Google answer the browser's CORS requests. Returns (session_url, expires_at)."""
        if self._session is None:
            raise DriveError(
                "Resumable uploads need an authorized session (use DriveClient.from_secret)."
            )
        parts = split_key(key)
        folder = self._folder_for(parts[:-1], create=True)
        assert folder is not None
        existing = self._child(folder, parts[-1], folder=False)
        headers = {
            "X-Upload-Content-Type": content_type,
            "Content-Type": "application/json; charset=UTF-8",
        }
        if size is not None:
            headers["X-Upload-Content-Length"] = str(size)
        if origin:
            headers["Origin"] = origin
        if existing:
            response = self._session.patch(
                f"{UPLOAD_URI}/{existing['id']}?uploadType=resumable",
                json={},
                headers=headers,
                timeout=30,
            )
        else:
            response = self._session.post(
                f"{UPLOAD_URI}?uploadType=resumable",
                json={"name": parts[-1], "parents": [folder]},
                headers=headers,
                timeout=30,
            )
        location = response.headers.get("Location") or response.headers.get("location")
        if response.status_code != 200 or not location:
            raise DriveError(
                f"Drive upload session failed: HTTP {response.status_code}",
                response.status_code,
            )
        return location, (now or datetime.now(UTC)) + SESSION_LIFETIME

    def account(self) -> str:
        """Email of the connected account (to show and to check the connection)."""
        try:
            about = self.service.about().get(fields="user(emailAddress)").execute()
        except HttpError as exc:
            raise _error("check", exc) from exc
        return str((about.get("user") or {}).get("emailAddress") or "")
