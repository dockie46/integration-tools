"""Typed data models used across the Gmail reader."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass(frozen=True, slots=True)
class AttachmentRef:
    """An attachment on a message, without downloading its bytes."""

    filename: str
    mime_type: str
    attachment_id: str | None
    size: int | None
    part_path: str

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class GmailMessageSummary:
    """Headers pulled from a Gmail message."""

    message_id: str
    subject: str
    sender: str
    date_header: str
    message_id_header: str


@dataclass(slots=True)
class GmailMessage:
    """A Gmail message suitable for a local client or a Lambda response."""

    message_id: str
    thread_id: str
    subject: str
    sender: str
    to: str
    date: str
    snippet: str
    label_ids: list[str] = field(default_factory=list)
    message_id_header: str = ""
    text_body: str | None = None
    html_body: str | None = None
    attachments: list[AttachmentRef] = field(default_factory=list)

    def to_dict(self) -> dict:
        return asdict(self)
