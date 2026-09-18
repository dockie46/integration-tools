"""Shared Gmail client used by the local CLI and the AWS Lambda handler."""

from __future__ import annotations

from pathlib import Path

from googleapiclient.discovery import Resource

from . import gmail as gmail_mod
from .auth import load_credentials, load_credentials_from_env
from .models import GmailMessage

METADATA_HEADERS = ["Subject", "From", "To", "Date", "Message-ID"]


class GmailClient:
    """Thin wrapper around the Gmail API for reading mail."""

    def __init__(self, service: Resource):
        self.service = service

    @classmethod
    def from_files(
        cls,
        credentials_path: Path,
        token_path: Path,
        *,
        allow_browser: bool = True,
    ) -> GmailClient:
        creds = load_credentials(credentials_path, token_path, allow_browser=allow_browser)
        return cls(gmail_mod.build_service(creds))

    @classmethod
    def from_env(cls) -> GmailClient:
        """Headless auth for Lambda: refresh token from GMAIL_TOKEN_JSON."""
        creds = load_credentials_from_env()
        return cls(gmail_mod.build_service(creds))

    def search(self, query: str, max_messages: int | None = None) -> list[str]:
        return gmail_mod.search_messages(self.service, query, max_messages)

    def get(self, message_id: str, *, include_body: bool = True) -> GmailMessage:
        fmt = "full" if include_body else "metadata"
        raw = gmail_mod.get_message(
            self.service,
            message_id,
            fmt=fmt,
            metadata_headers=METADATA_HEADERS if fmt == "metadata" else None,
        )
        return gmail_mod.parse_message(raw, include_body=include_body)

    def list_messages(
        self,
        query: str,
        max_messages: int | None = 20,
        *,
        include_body: bool = False,
    ) -> list[GmailMessage]:
        message_ids = self.search(query, max_messages)
        return [self.get(message_id, include_body=include_body) for message_id in message_ids]

    def download_attachment(self, message_id: str, attachment_id: str) -> bytes:
        return gmail_mod.download_attachment(self.service, message_id, attachment_id)
