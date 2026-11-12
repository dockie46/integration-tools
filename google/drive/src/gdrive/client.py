"""Drive as a file store for apps.

A file has three things: the app's ``key`` (unique, stored on the file as an app property), the ``name`` people
see (may repeat, can be renamed) and the ``folder`` it sits in (a path under the root, for people browsing).
Drive's own file id is the stable reference the app keeps; get / stat / delete / rename take it.

With the ``drive.file`` scope the app sees only what it created (or what the user picked for it), so the root
folder is the app's own: ``folderId`` from the secret, otherwise a folder named ``rootFolderName`` (default
"Softwareify") at the top of the user's Drive, created on first use.
"""

from __future__ import annotations

import hashlib
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
# Private app property holding the app's own key for a file (Drive's id is the reference the app stores).
KEY_PROPERTY = "sourceKey"


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

    # --- files: a stable key (appProperties) and Drive's own id as the reference -------------

    @staticmethod
    def _key_value(key: str) -> str:
        """The app's key as stored on the file. Drive caps one property at 124 bytes, so long keys are hashed."""
        normalized = "/".join(split_key(key))
        if len((KEY_PROPERTY + normalized).encode("utf-8")) <= 124:
            return normalized
        return "sha256:" + hashlib.sha256(normalized.encode("utf-8")).hexdigest()

    def locate(self, key: str) -> DriveFile | None:
        """The file the app wrote under ``key`` (wherever it sits now), or None."""
        value = self._key_value(key)
        query = (
            f"appProperties has {{ key='{KEY_PROPERTY}' and value='{_q(value)}' }} "
            f"and trashed = false and mimeType != '{FOLDER_MIME}'"
        )
        try:
            response = (
                self.service.files()
                .list(q=query, fields=f"files({_FIELDS})", pageSize=2, spaces="drive")
                .execute()
            )
        except HttpError as exc:
            raise _error("lookup", exc) from exc
        files = response.get("files") or []
        return _file(files[0]) if files else None

    def put(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        *,
        name: str | None = None,
        folder: str | None = None,
    ) -> DriveFile:
        """Write the file the app knows as ``key``: shown as ``name`` (default: the key's last part) in
        ``folder`` (a path under the root, created as needed). The same key again replaces the content."""
        display = (name or split_key(key)[-1]).strip() or split_key(key)[-1]
        media = MediaIoBaseUpload(
            io.BytesIO(data),
            mimetype=content_type,
            resumable=len(data) > RESUMABLE_THRESHOLD,
        )
        existing = self.locate(key)
        try:
            if existing:
                raw = (
                    self.service.files()
                    .update(
                        fileId=existing.file_id,
                        body={"name": display},
                        media_body=media,
                        fields=_FIELDS,
                    )
                    .execute()
                )
            else:
                parent = self._folder_for(
                    split_key(folder) if folder else [], create=True
                )
                body = {
                    "name": display,
                    "parents": [parent],
                    "appProperties": {KEY_PROPERTY: self._key_value(key)},
                }
                raw = (
                    self.service.files()
                    .create(body=body, media_body=media, fields=_FIELDS)
                    .execute()
                )
        except HttpError as exc:
            raise _error("upload", exc) from exc
        return _file(raw)

    def stat(self, file_id: str) -> DriveFile | None:
        try:
            raw = (
                self.service.files()
                .get(fileId=file_id, fields=_FIELDS + ",trashed")
                .execute()
            )
        except HttpError as exc:
            if _status(exc) == 404:
                return None
            raise _error("lookup", exc) from exc
        return None if raw.get("trashed") else _file(raw)

    def get(self, file_id: str) -> tuple[DriveFile, bytes]:
        info = self.stat(file_id)
        if info is None:
            raise FileNotFoundError(f"No Drive file with id '{file_id}'.")
        buffer = io.BytesIO()
        try:
            downloader = MediaIoBaseDownload(
                buffer, self.service.files().get_media(fileId=file_id)
            )
            done = False
            while not done:
                _, done = downloader.next_chunk()
        except HttpError as exc:
            raise _error("download", exc) from exc
        return info, buffer.getvalue()

    def delete(self, file_id: str) -> bool:
        try:
            self.service.files().delete(fileId=file_id).execute()
        except HttpError as exc:
            if _status(exc) == 404:
                return False
            raise _error("delete", exc) from exc
        return True

    def rename(self, file_id: str, name: str) -> DriveFile:
        if not name.strip():
            raise ValueError("A file needs a name.")
        try:
            raw = (
                self.service.files()
                .update(fileId=file_id, body={"name": name.strip()}, fields=_FIELDS)
                .execute()
            )
        except HttpError as exc:
            raise _error("rename", exc) from exc
        return _file(raw)

    def start_upload(
        self,
        key: str,
        content_type: str,
        *,
        name: str | None = None,
        folder: str | None = None,
        size: int | None = None,
        origin: str | None = None,
        now: datetime | None = None,
    ) -> tuple[str, datetime]:
        """A resumable upload session the browser PUTs the bytes to directly. ``origin`` (the app's web origin)
        makes Google answer the browser's CORS requests. Afterwards ``locate(key)`` finds the file.
        Returns (session_url, expires_at)."""
        if self._session is None:
            raise DriveError(
                "Resumable uploads need an authorized session (use DriveClient.from_secret)."
            )
        display = (name or split_key(key)[-1]).strip() or split_key(key)[-1]
        headers = {
            "X-Upload-Content-Type": content_type,
            "Content-Type": "application/json; charset=UTF-8",
        }
        if size is not None:
            headers["X-Upload-Content-Length"] = str(size)
        if origin:
            headers["Origin"] = origin
        existing = self.locate(key)
        if existing:
            response = self._session.patch(
                f"{UPLOAD_URI}/{existing.file_id}?uploadType=resumable",
                json={"name": display},
                headers=headers,
                timeout=30,
            )
        else:
            parent = self._folder_for(split_key(folder) if folder else [], create=True)
            response = self._session.post(
                f"{UPLOAD_URI}?uploadType=resumable",
                json={
                    "name": display,
                    "parents": [parent],
                    "appProperties": {KEY_PROPERTY: self._key_value(key)},
                },
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
