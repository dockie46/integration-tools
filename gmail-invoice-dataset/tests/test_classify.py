from pathlib import Path

from gmail_invoice_dataset.classify import looks_like_invoice, sort_dataset
from gmail_invoice_dataset.dataset import Dataset


def test_invoice_subject_is_kept():
    assert looks_like_invoice("Faktura 04/2026", "Urban_2601167.pdf")


def test_receipt_filename_is_kept():
    assert looks_like_invoice("Your receipt", "Receipt-2062-5616-5646.pdf")


def test_unfamiliar_text_defaults_to_kept():
    assert looks_like_invoice("Ahoj, posielam prilohu", "dokument.pdf")


def test_terms_and_conditions_excluded():
    assert not looks_like_invoice("Objednávka", "Obchodni_podminky.pdf")


def test_payslip_excluded():
    assert not looks_like_invoice("Výplatní lístek za období 06.2026", "VýplatníLístek_2026.06.pdf")


def test_gdpr_notice_excluded():
    assert not looks_like_invoice("GDPR", "Zásady zpracování osobních údajů.pdf")


def test_insurance_confirmation_excluded():
    assert not looks_like_invoice("Dokumentace ke smlouvě", "potvrzeni_o_pojisteni_hav.pdf")


def test_vat_tax_payment_filing_excluded():
    assert not looks_like_invoice("DPH", "DPHDP3-0683589105-20260322-221952-platba.pdf")


def test_income_tax_filing_excluded():
    assert not looks_like_invoice("Daně", "DPFDP6-0683589105-20220313-180002-platba.pdf")


def test_withdrawal_form_excluded():
    assert not looks_like_invoice("Děkujeme za objednávku", "Ombre_Odvolani.pdf")


def test_right_of_withdrawal_notice_excluded():
    assert not looks_like_invoice(
        "Informace o stavu objednávky", "Poučení o právu na odstoupení od smlouvy.pdf"
    )


def test_price_list_excluded():
    assert not looks_like_invoice("Fwd: Ceník", "Ceník 2022 - velkoobchod.pdf")


def _add(dataset: Dataset, *, msg_id: str, subject: str, original_filename: str):
    return dataset.add_pdf(
        b"%PDF-1.4 " + msg_id.encode(),
        gmail_message_id=msg_id,
        attachment_id="att1",
        subject=subject,
        sender="someone@example.com",
        received_at="2026-01-01T00:00:00Z",
        message_id_header="<abc@example.com>",
        mime_type="application/pdf",
        original_filename=original_filename,
        attachment_path="0",
    )


def test_sort_dataset_copies_into_sanitized_and_excluded(tmp_path: Path):
    dataset = Dataset(tmp_path)
    _add(dataset, msg_id="m1", subject="Faktura 04/2026", original_filename="invoice.pdf")
    _add(dataset, msg_id="m2", subject="GDPR", original_filename="gdpr.pdf")
    dataset.save_manifest()

    result = sort_dataset(tmp_path)

    assert result.kept == 1
    assert result.excluded == 1
    assert result.missing == 0
    assert (tmp_path / "sanitized" / "000001.pdf").exists()
    assert (tmp_path / "excluded" / "000002.pdf").exists()


def test_sort_dataset_dry_run_copies_nothing(tmp_path: Path):
    dataset = Dataset(tmp_path)
    _add(dataset, msg_id="m1", subject="Faktura 04/2026", original_filename="invoice.pdf")
    dataset.save_manifest()

    result = sort_dataset(tmp_path, dry_run=True)

    assert result.kept == 1
    assert not (tmp_path / "sanitized").exists()


def test_sort_dataset_reports_missing_raw_files(tmp_path: Path):
    dataset = Dataset(tmp_path)
    _add(dataset, msg_id="m1", subject="Faktura", original_filename="invoice.pdf")
    dataset.save_manifest()
    (tmp_path / "raw" / "000001.pdf").unlink()

    result = sort_dataset(tmp_path)

    assert result.missing == 1
    assert result.kept == 0
