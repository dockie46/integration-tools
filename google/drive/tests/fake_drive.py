"""In-memory stand-in for the googleapiclient Drive v3 resource (only what gdrive uses)."""

from __future__ import annotations

import re
from typing import Any

FOLDER = "application/vnd.google-apps.folder"


class _Req:
    def __init__(self, fn):
        self._fn = fn

    def execute(self):
        return self._fn()


class _Files:
    def __init__(self, drive: FakeDrive) -> None:
        self._d = drive

    def list(self, q: str, **_: Any) -> _Req:
        self._d.calls.append(("list", q))
        name = (
            re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
            .group(1)
            .replace("\\'", "'")
            .replace("\\\\", "\\")
        )
        parent = re.search(r"'((?:[^'\\]|\\.)*)' in parents", q).group(1)
        want_folder = "mimeType = " in q
        want_file = "mimeType != " in q

        def run():
            found = [
                f
                for f in self._d.items.values()
                if f["name"] == name
                and parent in f["parents"]
                and (not want_folder or f["mimeType"] == FOLDER)
                and (not want_file or f["mimeType"] != FOLDER)
            ]
            return {"files": found[:2]}

        return _Req(run)

    def create(self, body: dict, media_body: Any = None, fields: str = "") -> _Req:  # noqa: ARG002
        def run():
            self._d.next_id += 1
            file_id = f"id{self._d.next_id}"
            size = len(media_body._fd.getvalue()) if media_body is not None else 0
            mime = body.get("mimeType") or (
                media_body.mimetype() if media_body is not None else ""
            )
            self._d.items[file_id] = {
                "id": file_id,
                "name": body["name"],
                "parents": body["parents"],
                "mimeType": mime,
                "size": str(size),
            }
            self._d.contents[file_id] = (
                media_body._fd.getvalue() if media_body is not None else b""
            )
            self._d.calls.append(("create", body["name"]))
            return dict(self._d.items[file_id])

        return _Req(run)

    def update(self, fileId: str, media_body: Any, fields: str = "") -> _Req:  # noqa: ARG002, N803 - Google API names
        def run():
            data = media_body._fd.getvalue()
            self._d.contents[fileId] = data
            self._d.items[fileId]["size"] = str(len(data))
            self._d.calls.append(("update", fileId))
            return dict(self._d.items[fileId])

        return _Req(run)

    def delete(self, fileId: str) -> _Req:  # noqa: N803 - Google's name
        def run():
            self._d.items.pop(fileId, None)
            self._d.calls.append(("delete", fileId))

        return _Req(run)

    def get_media(self, fileId: str) -> Any:  # noqa: N803 - Google's name
        return ("media", fileId)


class _About:
    def get(self, fields: str) -> _Req:  # noqa: ARG002
        return _Req(lambda: {"user": {"emailAddress": "owner@firma.cz"}})


class FakeDrive:
    def __init__(self) -> None:
        self.items: dict[str, dict] = {}
        self.contents: dict[str, bytes] = {}
        self.calls: list[tuple[str, str]] = []
        self.next_id = 0

    def files(self) -> _Files:
        return _Files(self)

    def about(self) -> _About:
        return _About()
