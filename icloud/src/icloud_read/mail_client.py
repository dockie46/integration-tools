"""iCloud Mail via IMAP."""

from __future__ import annotations

import email
import imaplib
from email.header import decode_header, make_header
from email.utils import parsedate_to_datetime
from pathlib import Path

from .auth import ICloudAuthError, ICloudCredentials, load_credentials
from .models import MailMessage

IMAP_HOST = "imap.mail.me.com"
IMAP_PORT = 993


def _decode_header(raw: str | None) -> str:
    if not raw:
        return ""
    try:
        return str(make_header(decode_header(raw)))
    except Exception:
        return raw


class ICloudMailClient:
    """Thin IMAP wrapper for reading iCloud Mail."""

    def __init__(self, credentials: ICloudCredentials):
        self._credentials = credentials

    @classmethod
    def from_file(cls, path: Path) -> ICloudMailClient:
        return cls(load_credentials(path))

    def list_messages(self, max_messages: int = 10, *, mailbox: str = "INBOX") -> list[MailMessage]:
        if max_messages <= 0:
            return []

        try:
            client = imaplib.IMAP4_SSL(IMAP_HOST, IMAP_PORT)
            client.login(self._credentials.email, self._credentials.password)
        except imaplib.IMAP4.error as exc:
            raise ICloudAuthError(
                "iCloud Mail login failed. Check email and app-specific password."
            ) from exc

        try:
            status, _ = client.select(mailbox, readonly=True)
            if status != "OK":
                raise ICloudAuthError(f"Could not open mailbox {mailbox!r}")

            status, data = client.search(None, "ALL")
            if status != "OK" or not data or not data[0]:
                return []

            uids = data[0].split()
            selected = list(reversed(uids[-max_messages:]))
            messages: list[MailMessage] = []

            for uid in selected:
                status, fetched = client.fetch(
                    uid,
                    "(BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE)])",
                )
                if status != "OK" or not fetched or not fetched[0]:
                    continue
                raw = fetched[0][1]
                if not isinstance(raw, (bytes, bytearray)):
                    continue
                msg = email.message_from_bytes(raw)
                date_raw = msg.get("Date", "")
                try:
                    date = parsedate_to_datetime(date_raw).isoformat() if date_raw else ""
                except (TypeError, ValueError, IndexError):
                    date = date_raw
                messages.append(
                    MailMessage(
                        uid=uid.decode() if isinstance(uid, bytes) else str(uid),
                        subject=_decode_header(msg.get("Subject")),
                        sender=_decode_header(msg.get("From")),
                        date=date,
                    )
                )
            return messages
        except imaplib.IMAP4.error as exc:
            raise ICloudAuthError(f"iCloud Mail read failed: {exc}") from exc
        finally:
            try:
                client.logout()
            except Exception:
                pass
