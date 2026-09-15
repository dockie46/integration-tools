"""Typed data models used across the pipeline, instead of passing raw dicts."""

from __future__ import annotations

from dataclasses import asdict, dataclass


@dataclass(frozen=True, slots=True)
class PdfAttachment:
    """A PDF attachment found inside a Gmail message's MIME payload."""

    filename: str
    mime_type: str
    attachment_id: str | None
    data: bytes | None
    part_path: str


@dataclass(frozen=True, slots=True)
class GmailMessageSummary:
    """Headers pulled from a Gmail message, used for display and manifest metadata."""

    message_id: str
    subject: str
    sender: str
    date_header: str
    message_id_header: str


@dataclass(slots=True)
class ManifestEntry:
    """One row of dataset/manifest.json describing a downloaded PDF."""

    id: str
    filename: str
    sha256: str
    size_bytes: int
    gmail_message_id: str
    attachment_id: str | None
    subject: str
    sender: str
    received_at: str
    message_id_header: str
    mime_type: str
    original_filename: str
    attachment_path: str
    downloaded_at: str

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> ManifestEntry:
        return cls(**data)
