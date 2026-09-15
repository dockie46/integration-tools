"""Command-line entry point: orchestrates gmail.py (search/download) and dataset.py (storage)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import dataset as dataset_mod
from . import gmail as gmail_mod

DEFAULT_QUERY = "has:attachment filename:pdf"


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="gmail-invoice-dataset",
        description="Download PDF invoice/receipt attachments from Gmail into a local dataset.",
    )
    parser.add_argument(
        "--query", default=DEFAULT_QUERY, help=f"Gmail search query (default: {DEFAULT_QUERY!r})"
    )
    parser.add_argument(
        "--max-messages", type=int, default=None, help="Maximum number of messages to process"
    )
    parser.add_argument("--output", default="dataset", help="Dataset output directory (default: ./dataset)")
    parser.add_argument(
        "--credentials",
        default="credentials/credentials.json",
        help="Path to OAuth Desktop app credentials.json",
    )
    parser.add_argument("--token", default="token.json", help="Path to store/read the OAuth token")
    parser.add_argument(
        "--dry-run", action="store_true", help="List matching messages and PDFs without downloading"
    )
    return parser


def run(argv: list[str] | None = None) -> int:
    # Keep stdout progress output and stderr error output interleaved in order
    # even when redirected to a file/pipe (stdout is block-buffered there).
    sys.stdout.reconfigure(line_buffering=True)

    parser = build_parser()
    args = parser.parse_args(argv)

    output_dir = Path(args.output).resolve()
    credentials_path = Path(args.credentials).resolve()
    token_path = Path(args.token).resolve()

    print("Authenticating with Gmail...")
    try:
        creds = gmail_mod.load_credentials(credentials_path, token_path)
    except (gmail_mod.CredentialsMissingError, gmail_mod.GmailAuthError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    service = gmail_mod.build_service(creds)

    print(f"Query: {args.query}")
    try:
        message_ids = gmail_mod.search_messages(service, args.query, args.max_messages)
    except gmail_mod.GmailAuthError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(f"Matching messages: {len(message_ids)}")

    if args.dry_run:
        return _run_dry(service, message_ids)
    return _run_download(service, message_ids, output_dir)


def _run_dry(service, message_ids: list[str]) -> int:
    for message_id in message_ids:
        try:
            message = gmail_mod.get_message(service, message_id)
        except gmail_mod.GmailAuthError as exc:
            print(f"  error fetching {message_id}: {exc}", file=sys.stderr)
            continue
        summary = gmail_mod.summarize_message(message)
        attachments = gmail_mod.find_pdf_attachments(message)
        print(f"{message_id}:")
        print(f"  Subject: {summary.subject}")
        print(f"  From: {summary.sender}")
        if attachments:
            print("  PDFs:")
            for attachment in attachments:
                print(f"    - {attachment.filename}")
        else:
            print("  PDFs: (none found)")
    return 0


def _run_download(service, message_ids: list[str], output_dir: Path) -> int:
    ds = dataset_mod.Dataset(output_dir)

    downloaded = 0
    skipped = 0
    failures: list[str] = []
    total = len(message_ids)

    for index, message_id in enumerate(message_ids, start=1):
        try:
            message = gmail_mod.get_message(service, message_id)
        except gmail_mod.GmailAuthError as exc:
            failures.append(f"{message_id}: {exc}")
            continue

        summary = gmail_mod.summarize_message(message)
        attachments = gmail_mod.find_pdf_attachments(message)

        print(f"[{index}/{total}] {summary.subject}")
        print(f"  From: {summary.sender}")

        if not attachments:
            print("  PDF: (none found)")
            continue

        for attachment in attachments:
            print(f"  PDF: {attachment.filename}")
            try:
                data = gmail_mod.download_attachment(service, message_id, attachment)
            except (gmail_mod.GmailAuthError, ValueError) as exc:
                print(f"    failed: {exc}", file=sys.stderr)
                failures.append(f"{message_id}/{attachment.filename}: {exc}")
                continue

            sha256 = dataset_mod.sha256_of(data)
            dedupe = ds.check_duplicate(message_id, attachment.attachment_id, sha256)
            if dedupe.is_duplicate:
                print(f"    skipped: {dedupe.reason}")
                skipped += 1
                continue

            entry = ds.add_pdf(
                data,
                gmail_message_id=message_id,
                attachment_id=attachment.attachment_id,
                subject=summary.subject,
                sender=summary.sender,
                received_at=summary.date_header,
                message_id_header=summary.message_id_header,
                mime_type=attachment.mime_type,
                original_filename=attachment.filename,
                attachment_path=attachment.part_path,
            )
            print(f"    downloaded -> {ds.raw_dir / entry.filename}")
            downloaded += 1

    ds.save_manifest()

    print("Done.")
    print(f"Downloaded: {downloaded}")
    print(f"Skipped: {skipped}")
    print(f"Dataset: {ds.root}")
    if failures:
        print(f"Failures: {len(failures)}", file=sys.stderr)
        for failure in failures:
            print(f"  - {failure}", file=sys.stderr)

    return 0


def main() -> None:
    sys.exit(run())


if __name__ == "__main__":
    main()
