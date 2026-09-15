"""Local persistence: the dataset directory, its manifest, and deduplication."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .models import ManifestEntry

MANIFEST_FILENAME = "manifest.json"
RAW_SUBDIR = "raw"


class ManifestError(RuntimeError):
    """Raised when dataset/manifest.json exists but cannot be parsed."""


@dataclass(frozen=True, slots=True)
class DedupeResult:
    """Result of checking whether a downloaded PDF is already in the dataset."""

    is_duplicate: bool
    reason: str | None = None


def sha256_of(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


class Dataset:
    """Owns dataset/manifest.json and dataset/raw/*.pdf under a root directory."""

    def __init__(self, root: Path):
        self.root = root
        self.raw_dir = root / RAW_SUBDIR
        self.manifest_path = root / MANIFEST_FILENAME
        self.entries: list[ManifestEntry] = self._load_manifest()

    def _load_manifest(self) -> list[ManifestEntry]:
        if not self.manifest_path.exists():
            return []
        try:
            raw = json.loads(self.manifest_path.read_text())
        except json.JSONDecodeError as exc:
            raise ManifestError(f"Manifest at {self.manifest_path} is not valid JSON: {exc}") from exc
        if not isinstance(raw, list):
            raise ManifestError(f"Manifest at {self.manifest_path} must contain a JSON list")
        try:
            return [ManifestEntry.from_dict(item) for item in raw]
        except TypeError as exc:
            raise ManifestError(f"Manifest at {self.manifest_path} has malformed entries: {exc}") from exc

    def save_manifest(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        payload = [entry.to_dict() for entry in self.entries]
        self.manifest_path.write_text(json.dumps(payload, indent=2) + "\n")

    def next_id(self) -> str:
        existing_numbers = [int(entry.id) for entry in self.entries if entry.id.isdigit()]
        next_number = max(existing_numbers, default=0) + 1
        return f"{next_number:06d}"

    def find_by_source(self, gmail_message_id: str, attachment_id: str | None) -> ManifestEntry | None:
        for entry in self.entries:
            if entry.gmail_message_id == gmail_message_id and entry.attachment_id == attachment_id:
                return entry
        return None

    def find_by_sha256(self, sha256: str) -> ManifestEntry | None:
        for entry in self.entries:
            if entry.sha256 == sha256:
                return entry
        return None

    def check_duplicate(self, gmail_message_id: str, attachment_id: str | None, sha256: str) -> DedupeResult:
        if self.find_by_source(gmail_message_id, attachment_id) is not None:
            return DedupeResult(True, "already in manifest")
        if self.find_by_sha256(sha256) is not None:
            return DedupeResult(True, "duplicate SHA-256")
        return DedupeResult(False)

    def add_pdf(
        self,
        data: bytes,
        *,
        gmail_message_id: str,
        attachment_id: str | None,
        subject: str,
        sender: str,
        received_at: str,
        message_id_header: str,
        mime_type: str,
        original_filename: str,
        attachment_path: str,
    ) -> ManifestEntry:
        """Write `data` to dataset/raw under a generated id and record it in the manifest.

        Callers are responsible for calling check_duplicate() first — this method
        always writes a new file.
        """
        entry_id = self.next_id()
        filename = f"{entry_id}.pdf"
        self.raw_dir.mkdir(parents=True, exist_ok=True)
        (self.raw_dir / filename).write_bytes(data)

        entry = ManifestEntry(
            id=entry_id,
            filename=filename,
            sha256=sha256_of(data),
            size_bytes=len(data),
            gmail_message_id=gmail_message_id,
            attachment_id=attachment_id,
            subject=subject,
            sender=sender,
            received_at=received_at,
            message_id_header=message_id_header,
            mime_type=mime_type,
            original_filename=original_filename,
            attachment_path=attachment_path,
            downloaded_at=datetime.now(timezone.utc).isoformat(),
        )
        self.entries.append(entry)
        return entry
