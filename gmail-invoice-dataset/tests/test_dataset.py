from pathlib import Path

import pytest

from gmail_invoice_dataset.dataset import Dataset, ManifestError, sha256_of


def _add(ds: Dataset, data: bytes, *, msg_id: str, att_id: str | None = "att1"):
    return ds.add_pdf(
        data,
        gmail_message_id=msg_id,
        attachment_id=att_id,
        subject="Invoice",
        sender="shop@example.com",
        received_at="2026-01-01T00:00:00Z",
        message_id_header="<abc@example.com>",
        mime_type="application/pdf",
        original_filename="invoice.pdf",
        attachment_path="0.1",
    )


def test_missing_manifest_starts_empty(tmp_path: Path):
    ds = Dataset(tmp_path)
    assert ds.entries == []


def test_next_id_starts_at_one(tmp_path: Path):
    ds = Dataset(tmp_path)
    assert ds.next_id() == "000001"


def test_next_id_increments_after_add(tmp_path: Path):
    ds = Dataset(tmp_path)
    _add(ds, b"a", msg_id="m1")
    assert ds.next_id() == "000002"


def test_save_and_reload_manifest(tmp_path: Path):
    ds = Dataset(tmp_path)
    _add(ds, b"%PDF-1.4 fake", msg_id="m1")
    ds.save_manifest()

    reloaded = Dataset(tmp_path)
    assert len(reloaded.entries) == 1
    entry = reloaded.entries[0]
    assert entry.id == "000001"
    assert entry.filename == "000001.pdf"
    assert entry.sha256 == sha256_of(b"%PDF-1.4 fake")
    assert entry.attachment_path == "0.1"
    assert (tmp_path / "raw" / "000001.pdf").read_bytes() == b"%PDF-1.4 fake"


def test_duplicate_by_source_identity(tmp_path: Path):
    ds = Dataset(tmp_path)
    _add(ds, b"a", msg_id="m1", att_id="att1")

    result = ds.check_duplicate("m1", "att1", sha256_of(b"a"))
    assert result.is_duplicate
    assert result.reason == "already in manifest"


def test_duplicate_by_sha256_from_different_message(tmp_path: Path):
    ds = Dataset(tmp_path)
    _add(ds, b"same-bytes", msg_id="m1", att_id="att1")

    result = ds.check_duplicate("m2", "att2", sha256_of(b"same-bytes"))
    assert result.is_duplicate
    assert result.reason == "duplicate SHA-256"


def test_no_duplicate_for_new_content(tmp_path: Path):
    ds = Dataset(tmp_path)
    _add(ds, b"a", msg_id="m1", att_id="att1")

    result = ds.check_duplicate("m2", "att2", sha256_of(b"different"))
    assert not result.is_duplicate
    assert result.reason is None


def test_malformed_manifest_raises(tmp_path: Path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "manifest.json").write_text("not json")

    with pytest.raises(ManifestError):
        Dataset(tmp_path)


def test_manifest_must_be_a_list(tmp_path: Path):
    tmp_path.mkdir(exist_ok=True)
    (tmp_path / "manifest.json").write_text('{"not": "a list"}')

    with pytest.raises(ManifestError):
        Dataset(tmp_path)
