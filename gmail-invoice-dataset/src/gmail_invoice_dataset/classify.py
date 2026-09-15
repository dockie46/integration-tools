"""Heuristic sort of downloaded PDFs into likely-invoice vs. likely-not.

Looks only at the Gmail subject and original filename already recorded in
the manifest (no PDF content is opened or sent anywhere) and copies files
into dataset/sanitized/ (looks like an invoice/receipt) or
dataset/excluded/ (clearly something else — T&Cs, payslips, insurance,
GDPR notices, ...). Originals in dataset/raw/ are never modified or moved.

This is a coarse first pass, not a classifier: unfamiliar text defaults to
"keep" so real invoices are never silently dropped, and exclusion requires
a specific negative-keyword match.
"""

from __future__ import annotations

import argparse
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

from .dataset import Dataset

EXCLUDE_KEYWORDS = [
    "obchodni podminky",
    "obchodní podmínky",
    "vseobecne obchodni podminky",
    "všeobecné obchodní podmínky",
    "vop",
    "vyplatni listek",
    "výplatní lístek",
    "vyplatna paska",
    "výplatná páska",
    "pojisteni",
    "pojištění",
    "poistenie",
    "zelena karta",
    "zelená karta",
    "reklamace",
    "reklamácia",
    "vraceni zbozi",
    "vrácení zboží",
    "odvolani",
    "odvolání",
    "odstoupeni",
    "odstoupení",
    "storno",
    "gdpr",
    "zakonik prace",
    "zákoník práce",
    "zadost",
    "žádost",
    "dphdp",
    "dpfdp",
    "danove priznani",
    "daňové přiznání",
    "okamzita vymena",
    "okamžitá výměna",
    "informace k doruceni",
    "informace k doručení",
    "cenik",
    "ceník",
]

INVOICE_KEYWORDS = [
    "faktura",
    "invoice",
    "receipt",
    "uctenka",
    "účtenka",
    "doklad",
    "dodaci list",
    "dodací list",
]


def _normalize(text: str) -> str:
    return text.casefold().replace("_", " ").replace("-", " ")


def looks_like_invoice(subject: str, original_filename: str) -> bool:
    """True unless a negative keyword clearly identifies this as not an invoice."""
    haystack = _normalize(f"{subject} {original_filename}")
    if any(keyword in haystack for keyword in EXCLUDE_KEYWORDS):
        return False
    return True


@dataclass(frozen=True, slots=True)
class SortResult:
    kept: int = 0
    excluded: int = 0
    missing: int = 0


def sort_dataset(dataset_root: Path, *, dry_run: bool = False) -> SortResult:
    dataset = Dataset(dataset_root)
    sanitized_dir = dataset_root / "sanitized"
    excluded_dir = dataset_root / "excluded"

    kept = 0
    excluded = 0
    missing = 0

    for entry in dataset.entries:
        source = dataset.raw_dir / entry.filename
        if not source.exists():
            missing += 1
            continue

        is_invoice = looks_like_invoice(entry.subject, entry.original_filename)
        destination_dir = sanitized_dir if is_invoice else excluded_dir
        if is_invoice:
            kept += 1
        else:
            excluded += 1

        if dry_run:
            continue

        destination_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination_dir / entry.filename)

    return SortResult(kept=kept, excluded=excluded, missing=missing)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail-invoice-dataset-sort",
        description="Heuristically sort dataset/raw into dataset/sanitized (likely invoices) "
        "and dataset/excluded (likely not), based on subject/filename keywords.",
    )
    parser.add_argument("--dataset", default="dataset", help="Dataset root directory (default: ./dataset)")
    parser.add_argument("--dry-run", action="store_true", help="Only print counts, copy nothing")
    return parser


def main() -> None:
    sys.stdout.reconfigure(line_buffering=True)

    parser = build_parser()
    args = parser.parse_args()

    dataset_root = Path(args.dataset).resolve()
    result = sort_dataset(dataset_root, dry_run=args.dry_run)

    print(f"Likely invoices{'  (dry run)' if args.dry_run else ' -> dataset/sanitized'}: {result.kept}")
    print(f"Likely not{'      (dry run)' if args.dry_run else ' -> dataset/excluded'}: {result.excluded}")
    if result.missing:
        print(f"In manifest but missing from dataset/raw: {result.missing}", file=sys.stderr)


if __name__ == "__main__":
    main()
