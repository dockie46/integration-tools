"""Gmail access: OAuth, search, MIME traversal, and attachment download.

Everything here is local-first: attachment bytes are returned to the caller
(dataset.py writes them to disk) and are never logged or sent anywhere else.
"""

from __future__ import annotations

import base64
import binascii
import random
import time
from pathlib import Path
from typing import Any, Iterator

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import Resource, build
from googleapiclient.errors import HttpError

from .models import GmailMessageSummary, PdfAttachment

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


class CredentialsMissingError(RuntimeError):
    """Raised when credentials/credentials.json is not present."""


class GmailAuthError(RuntimeError):
    """Raised when authentication or a Gmail API call fails."""


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


def load_credentials(credentials_path: Path, token_path: Path) -> Credentials:
    """Load a cached OAuth token, refreshing or re-authenticating as needed.

    Never logs token contents. Raises CredentialsMissingError with a precise
    remediation message when credentials.json is absent.
    """
    creds: Credentials | None = None
    if token_path.exists():
        try:
            creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
        except ValueError as exc:
            raise GmailAuthError(f"Stored token at {token_path} is invalid: {exc}") from exc

    if creds and creds.valid:
        return creds

    if creds and creds.expired and creds.refresh_token:
        try:
            creds.refresh(Request())
        except Exception as exc:
            raise GmailAuthError(f"Failed to refresh Gmail token: {exc}") from exc
        token_path.write_text(creds.to_json())
        return creds

    if not credentials_path.exists():
        raise CredentialsMissingError(
            "Gmail OAuth credentials not found.\n"
            f"Expected file: {credentials_path}\n\n"
            "To fix this:\n"
            "  1. Go to https://console.cloud.google.com/apis/credentials\n"
            "  2. Create an OAuth client ID of type 'Desktop app'\n"
            "  3. Download the JSON file\n"
            f"  4. Save it as: {credentials_path}"
        )

    try:
        flow = InstalledAppFlow.from_client_secrets_file(str(credentials_path), SCOPES)
        creds = flow.run_local_server(port=0)
    except Exception as exc:
        raise GmailAuthError(f"Gmail authentication failed: {exc}") from exc

    token_path.parent.mkdir(parents=True, exist_ok=True)
    token_path.write_text(creds.to_json())
    return creds


def build_service(creds: Credentials) -> Resource:
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


def get_message(service: Resource, message_id: str) -> dict:
    try:
        return _execute_with_retry(
            service.users().messages().get(userId="me", id=message_id, format="full")
        )
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


def _is_pdf_part(part: dict) -> bool:
    mime_type = part.get("mimeType", "")
    filename = part.get("filename") or ""
    return mime_type == "application/pdf" or filename.lower().endswith(".pdf")


def iter_pdf_parts(payload: dict, path_prefix: str = "0") -> Iterator[tuple[dict, str]]:
    """Recursively walk a Gmail MIME payload, yielding (part, part_path) for each PDF part.

    Gmail MIME structures can nest multipart containers arbitrarily deep
    (multipart/mixed containing multipart/alternative containing multipart/related,
    etc.) — this does not assume a PDF is ever at the top level.
    """
    if _is_pdf_part(payload):
        yield payload, path_prefix
    for index, sub_part in enumerate(payload.get("parts") or []):
        yield from iter_pdf_parts(sub_part, f"{path_prefix}.{index}")


def _decode_inline_data(data: str) -> bytes:
    try:
        return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))
    except (binascii.Error, ValueError) as exc:
        raise ValueError(f"Malformed base64 attachment data: {exc}") from exc


def find_pdf_attachments(message: dict) -> list[PdfAttachment]:
    payload = message.get("payload", {})
    attachments: list[PdfAttachment] = []
    for part, part_path in iter_pdf_parts(payload):
        filename = (part.get("filename") or "").strip() or "attachment.pdf"
        body = part.get("body") or {}
        raw_data = body.get("data")
        attachments.append(
            PdfAttachment(
                filename=filename,
                mime_type=part.get("mimeType", "application/pdf"),
                attachment_id=body.get("attachmentId"),
                data=_decode_inline_data(raw_data) if raw_data else None,
                part_path=part_path,
            )
        )
    return attachments


def download_attachment(service: Resource | None, message_id: str, attachment: PdfAttachment) -> bytes:
    """Return the raw PDF bytes for `attachment`, fetching from the API if not inline."""
    if attachment.data is not None:
        return attachment.data
    if not attachment.attachment_id:
        raise ValueError(f"Attachment '{attachment.filename}' has no attachmentId or inline data")
    try:
        response = _execute_with_retry(
            service.users()
            .messages()
            .attachments()
            .get(userId="me", messageId=message_id, id=attachment.attachment_id)
        )
    except HttpError as exc:
        raise GmailAuthError(f"Failed to download attachment {attachment.attachment_id}: {exc}") from exc
    return _decode_inline_data(response["data"])
