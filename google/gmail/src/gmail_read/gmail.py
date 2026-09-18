"""Gmail API helpers: search, MIME traversal, message parsing, attachment download.

Auth lives in auth.py. Attachment bytes are returned to the caller and are
never logged or sent anywhere else.
"""

from __future__ import annotations

import base64
import binascii
import random
import time
from typing import Any, Iterator

from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from .auth import GmailAuthError
from .models import AttachmentRef, GmailMessage, GmailMessageSummary


_RATE_LIMIT_REASONS = {"rateLimitExceeded", "userRateLimitExceeded", "quotaExceeded"}


def _is_rate_limit_error(exc: HttpError) -> bool:
    if getattr(exc.resp, "status", None) not in (403, 429):
        return False
    reasons = {detail.get("reason") for detail in (getattr(exc, "error_details", None) or [])}
    if reasons & _RATE_LIMIT_REASONS:
        return True
    return any(reason in str(exc) for reason in _RATE_LIMIT_REASONS)


def _execute_with_retry(request: Any, max_retries: int = 8):
    """Run a Gmail API request, retrying with exponential backoff on rate-limit errors.

    Gmail's per-user quota is easy to exceed on a large mailbox since requests
    are made one message at a time with no batching; backing off and retrying
    is far more reliable than surfacing a failure for most of the mailbox.
    """
    delay = 1.0
    for attempt in range(max_retries + 1):
        try:
            return request.execute()
        except HttpError as exc:
            if attempt >= max_retries or not _is_rate_limit_error(exc):
                raise
            time.sleep(delay + random.uniform(0, delay))
            delay = min(delay * 2, 60.0)


def build_service(creds) -> Resource:
    return build("gmail", "v1", credentials=creds, cache_discovery=False)


def search_messages(service: Resource, query: str, max_messages: int | None = None) -> list[str]:
    """Return Gmail message ids matching `query`, paging until exhausted or max_messages is hit."""
    message_ids: list[str] = []
    page_token: str | None = None
    try:
        while True:
            request_kwargs: dict[str, Any] = {"userId": "me", "q": query}
            if page_token:
                request_kwargs["pageToken"] = page_token
            if max_messages is not None:
                remaining = max_messages - len(message_ids)
                if remaining <= 0:
                    break
                request_kwargs["maxResults"] = min(500, remaining)
            response = _execute_with_retry(service.users().messages().list(**request_kwargs))
            message_ids.extend(m["id"] for m in response.get("messages", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break
    except HttpError as exc:
        raise GmailAuthError(f"Gmail search failed: {exc}") from exc

    if max_messages is not None:
        message_ids = message_ids[:max_messages]
    return message_ids


def get_message(
    service: Resource,
    message_id: str,
    fmt: str = "full",
    metadata_headers: list[str] | None = None,
) -> dict:
    request_kwargs: dict[str, Any] = {"userId": "me", "id": message_id, "format": fmt}
    if fmt == "metadata" and metadata_headers:
        request_kwargs["metadataHeaders"] = metadata_headers
    try:
        return _execute_with_retry(service.users().messages().get(**request_kwargs))
    except HttpError as exc:
        raise GmailAuthError(f"Failed to fetch message {message_id}: {exc}") from exc


def _header(headers: list[dict], name: str) -> str:
    for header in headers:
        if header.get("name", "").lower() == name.lower():
            return header.get("value", "")
    return ""


def summarize_message(message: dict) -> GmailMessageSummary:
    headers = message.get("payload", {}).get("headers", [])
    return GmailMessageSummary(
        message_id=message["id"],
        subject=_header(headers, "Subject") or "(no subject)",
        sender=_header(headers, "From") or "(unknown sender)",
        date_header=_header(headers, "Date"),
        message_id_header=_header(headers, "Message-ID"),
    )


def _decode_inline_data(data: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Malformed base64 attachment data: {exc}") from exc


def _decode_part_text(data: str) -> str:
    return _decode_inline_data(data).decode("utf-8", errors="replace")


def extract_bodies(payload: dict) -> tuple[str | None, str | None]:
    """Return (text/plain, text/html) decoded from a MIME payload.

    Named attachment parts are skipped so attached .txt/.html files are not
    treated as the message body.
    """
    plain_parts: list[str] = []
    html_parts: list[str] = []

    def walk(part: dict) -> None:
        filename = (part.get("filename") or "").strip()
        mime_type = part.get("mimeType") or ""
        body = part.get("body") or {}
        data = body.get("data")
        if not filename and data:
            if mime_type == "text/plain":
                plain_parts.append(_decode_part_text(data))
            elif mime_type == "text/html":
                html_parts.append(_decode_part_text(data))
        for sub_part in part.get("parts") or []:
            walk(sub_part)

    walk(payload)
    return (
        "\n".join(plain_parts) if plain_parts else None,
        "\n".join(html_parts) if html_parts else None,
    )


def iter_named_parts(payload: dict, path_prefix: str = "0") -> Iterator[tuple[dict, str]]:
    """Yield MIME parts that have a filename (typical Gmail attachments)."""
    if (payload.get("filename") or "").strip():
        yield payload, path_prefix
    for index, sub_part in enumerate(payload.get("parts") or []):
        yield from iter_named_parts(sub_part, f"{path_prefix}.{index}")


def find_attachments(message: dict) -> list[AttachmentRef]:
    payload = message.get("payload", {})
    attachments: list[AttachmentRef] = []
    for part, part_path in iter_named_parts(payload):
        body = part.get("body") or {}
        size = body.get("size")
        attachments.append(
            AttachmentRef(
                filename=(part.get("filename") or "").strip(),
                mime_type=part.get("mimeType") or "application/octet-stream",
                attachment_id=body.get("attachmentId"),
                size=int(size) if size is not None else None,
                part_path=part_path,
            )
        )
    return attachments


def parse_message(message: dict, *, include_body: bool = True) -> GmailMessage:
    headers = message.get("payload", {}).get("headers", [])
    text_body, html_body = (None, None)
    if include_body:
        text_body, html_body = extract_bodies(message.get("payload") or {})
    return GmailMessage(
        message_id=message["id"],
        thread_id=message.get("threadId") or "",
        subject=_header(headers, "Subject") or "(no subject)",
        sender=_header(headers, "From") or "(unknown sender)",
        to=_header(headers, "To"),
        date=_header(headers, "Date"),
        snippet=message.get("snippet") or "",
        label_ids=list(message.get("labelIds") or []),
        message_id_header=_header(headers, "Message-ID"),
        text_body=text_body,
        html_body=html_body,
        attachments=find_attachments(message),
    )


def download_attachment(service: Resource, message_id: str, attachment_id: str) -> bytes:
    """Return raw attachment bytes fetched from the Gmail API."""
    if not attachment_id:
        raise ValueError("attachment_id is required")
    try:
        response = _execute_with_retry(
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment_id)
        )
    except HttpError as exc:
        raise GmailAuthError(f"Failed to download attachment {attachment_id}: {exc}") from exc
    return _decode_inline_data(response["data"])
