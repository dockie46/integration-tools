"""In-memory stand-in for the googleapiclient Drive v3 resource (only what gdrive uses)."""

from __future__ import annotations

import re
from typing import Any

import httplib2
from googleapiclient.errors import HttpError

FOLDER = "application/vnd.google-apps.folder"


def _unescape(value: str) -> str:
    return value.replace("\\'", "'").replace("\\\\", "\\")


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
        prop = re.search(
            r"appProperties has \{ key='(\w+)' and value='((?:[^'\\]|\\.)*)' \}", q
        )
        name = re.search(r"name = '((?:[^'\\]|\\.)*)'", q)
        parent = re.search(r"'((?:[^'\\]|\\.)*)' in parents", q)
        want_folder = "mimeType = " in q
        want_file = "mimeType != " in q

        def run():
            found = []
            for f in self._d.items.values():
                if f.get("trashed"):
                    continue
                if prop and (f.get("appProperties") or {}).get(
                    prop.group(1)
                ) != _unescape(prop.group(2)):
                    continue
                if name and f["name"] != _unescape(name.group(1)):
                    continue
                if parent and _unescape(parent.group(1)) not in f["parents"]:
                    continue
                if want_folder and f["mimeType"] != FOLDER:
                    continue
                if want_file and f["mimeType"] == FOLDER:
                    continue
                found.append(dict(f))
            return {"files": found[:2]}

        return _Req(run)

    def get(self, fileId: str, fields: str = "") -> _Req:  # noqa: ARG002, N803 - Google API names
        def run():
            if fileId not in self._d.items:
                raise HttpError(httplib2.Response({"status": 404}), b"{}")
            return dict(self._d.items[fileId])

        return _Req(run)

    def create(self, body: dict, media_body: Any = None, fields: str = "") -> _Req:  # noqa: ARG002
        def run():
            self._d.next_id += 1
            file_id = f"id{self._d.next_id}"
            data = media_body._fd.getvalue() if media_body is not None else b""
            self._d.items[file_id] = {
                "id": file_id,
                "name": body["name"],
                "parents": body["parents"],
                "mimeType": body.get("mimeType")
                or (media_body.mimetype() if media_body is not None else ""),
                "size": str(len(data)),
                "appProperties": dict(body.get("appProperties") or {}),
            }
            self._d.contents[file_id] = data
            self._d.calls.append(("create", body["name"]))
            return dict(self._d.items[file_id])

        return _Req(run)

    def update(
        self,
        fileId: str,  # noqa: N803 - Google API name
        body: dict | None = None,
        media_body: Any = None,
        fields: str = "",  # noqa: ARG002
    ) -> _Req:
        def run():
            item = self._d.items[fileId]
            if body and "name" in body:
                item["name"] = body["name"]
            if media_body is not None:
                data = media_body._fd.getvalue()
                self._d.contents[fileId] = data
                item["size"] = str(len(data))
            self._d.calls.append(("update", fileId))
            return dict(item)

        return _Req(run)

    def delete(self, fileId: str) -> _Req:  # noqa: N803 - Google API name
        def run():
            if fileId not in self._d.items:
                raise HttpError(httplib2.Response({"status": 404}), b"{}")
            self._d.items.pop(fileId)
            self._d.calls.append(("delete", fileId))

        return _Req(run)

    def get_media(self, fileId: str) -> Any:  # noqa: N803 - Google API name
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
