# gmail-invoice-dataset

Connects to a Gmail account, finds real invoice/receipt emails with PDF
attachments, downloads those PDFs locally, deduplicates them, and builds a
structured `manifest.json` describing the dataset.

This is a local-first tool for building a real-world PDF dataset used to
test and improve document/invoice extraction (for the
[Keepr](../keepr-my-valuables-ios) project). **Version 0.1 does not send any
document or email content anywhere** — no OCR, no AI extraction, no upload.
Everything happens on your machine.

```
Gmail → OAuth 2.0 → Gmail API → search → find PDF attachments →
download → deduplicate → dataset/raw/*.pdf → dataset/manifest.json
```

## 1. Google Cloud setup

1. Go to the [Google Cloud Console](https://console.cloud.google.com/) and
   create a project (or reuse an existing personal one).
2. Enable the **Gmail API**:
   [APIs & Services → Library → Gmail API → Enable](https://console.cloud.google.com/apis/library/gmail.googleapis.com).
3. Configure the **OAuth consent screen** (External is fine for personal
   use; add your own Gmail address as a test user).
4. Create OAuth credentials:
   [APIs & Services → Credentials → Create Credentials → OAuth client ID](https://console.cloud.google.com/apis/credentials).
   - Application type: **Desktop app**.
5. Download the resulting JSON file.

## 2. Place your credentials

Save the downloaded file as:

```
credentials/credentials.json
```

This file and the OAuth token generated on first login are **never
committed** — see [Privacy](#privacy) below.

## 3. Installation

```sh
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
```

For running the test suite too:

```sh
pip install -e ".[dev]"
```

## 4. Running the application

```sh
gmail-invoice-dataset
```

On first run this opens a browser window to authenticate with your Google
account and requests **read-only** Gmail access
(`gmail.readonly`). The resulting token is cached in `token.json` and
reused (and refreshed automatically) on later runs — you won't need to log
in again unless the token is revoked.

Example output:

```
Authenticating with Gmail...
Query: has:attachment filename:pdf
Matching messages: 37
[1/37] Invoice 2026-123
  From: shop@example.com
  PDF: invoice.pdf
    downloaded -> dataset/raw/000001.pdf
[2/37] Order confirmation
  From: another-shop@example.com
  PDF: receipt.pdf
    skipped: already in manifest
Done.
Downloaded: 1
Skipped: 1
Dataset: /absolute/path/dataset
```

## 5. Dry run

Before downloading anything, preview what would be found:

```sh
gmail-invoice-dataset --dry-run
```

This authenticates, runs the search, and lists matching messages and their
PDF attachments — it does **not** download or write anything to `dataset/`.

```
Authenticating with Gmail...
Query: has:attachment filename:pdf
Matching messages: 37
abc123:
  Subject: Invoice 2026-123
  From: shop@example.com
  PDFs:
    - invoice.pdf
def456:
  Subject: Order confirmation
  From: store@example.com
  PDFs:
    - receipt.pdf
```

## 6. Custom Gmail queries

The default query is `has:attachment filename:pdf` — intentionally broad,
to build a real-world dataset. Override it with any
[Gmail search operator](https://support.google.com/mail/answer/7190):

```sh
gmail-invoice-dataset --query 'has:attachment filename:pdf newer_than:2y'
gmail-invoice-dataset --query 'has:attachment filename:pdf (invoice OR faktura)'
```

## CLI options

| Flag | Default | Description |
| --- | --- | --- |
| `--query` | `has:attachment filename:pdf` | Gmail search query |
| `--max-messages` | (no limit) | Maximum number of messages to process |
| `--output` | `dataset` | Dataset output directory |
| `--credentials` | `credentials/credentials.json` | Path to OAuth client credentials |
| `--token` | `token.json` | Path to store/read the OAuth token |
| `--dry-run` | off | List matches without downloading anything |

## Dataset structure

```
dataset/
├── manifest.json
├── raw/          # every downloaded PDF, untouched — the source of truth
├── sanitized/    # copies of PDFs the sorter thinks are real invoices/receipts
└── excluded/     # copies of PDFs the sorter thinks are something else
```

Downloaded PDFs are stored under a **generated sequential id**
(`000001.pdf`, `000002.pdf`, ...), never under their original filename —
the original filename is preserved in the manifest instead.

### Sorting out non-invoice PDFs

`has:attachment filename:pdf` also picks up plenty of things that aren't
invoices — payslips, insurance letters, T&Cs, GDPR notices, scanned personal
documents. Rather than triage that by hand, a keyword heuristic over each
PDF's Gmail subject and original filename (never the PDF content — nothing
is opened or sent anywhere) sorts `dataset/raw` into two **copies**:

```sh
gmail-invoice-dataset-sort            # copies into dataset/sanitized/ and dataset/excluded/
gmail-invoice-dataset-sort --dry-run  # just prints the counts
```

This never touches or deletes anything in `dataset/raw` — it only copies.
It's a coarse first pass, not a classifier: unfamiliar text defaults to
"keep", and a PDF only lands in `dataset/excluded` on a specific negative
keyword match (payslip, insurance, T&Cs, GDPR, ...). Expect to skim
`dataset/excluded` occasionally for anything that shouldn't have been
filtered out.

## Manifest structure

Each entry in `dataset/manifest.json` looks like:

```json
{
  "id": "000001",
  "filename": "000001.pdf",
  "sha256": "…",
  "size_bytes": 123456,
  "gmail_message_id": "…",
  "attachment_id": "…",
  "subject": "Invoice 2026-123",
  "sender": "shop@example.com",
  "received_at": "…",
  "message_id_header": "…",
  "mime_type": "application/pdf",
  "original_filename": "invoice.pdf",
  "attachment_path": "0.1",
  "downloaded_at": "…"
}
```

`attachment_path` is the dot-separated index path of the MIME part inside
the message (e.g. `"0.1"` = the second part of the top-level payload),
useful for tracing back into oddly nested emails.

## Deduplication

The tool is safe to run repeatedly:

- **Source identity** — if the same `gmail_message_id` + `attachment_id`
  was already downloaded, it's skipped (`already in manifest`).
- **Content identity** — if the PDF bytes match a SHA-256 already in the
  manifest (e.g. forwarded or re-sent invoices), it's skipped
  (`duplicate SHA-256`).

No duplicate files are ever written to `dataset/raw/`.

## Privacy

This tool processes **real personal invoices and receipts**. Keep in mind:

- `credentials/credentials.json` and `token.json` grant read-only access to
  your Gmail account — both are git-ignored and must never be committed.
- `dataset/raw/` and `dataset/sanitized/` contain real personal documents
  and are git-ignored.
- `dataset/manifest.json` contains email subjects and sender addresses
  (real personal metadata). It is **not** git-ignored by default so you can
  version dataset structure/tooling changes, but you should add it to your
  own `.gitignore` (or scrub it) before sharing this project or its history
  with anyone else.
- No PDF content, email content, or metadata is ever logged in full, sent
  to any external service, or uploaded automatically. Console output only
  ever shows the subject/sender/filename already visible in your own
  inbox.

## Running tests

The test suite requires no Gmail credentials — the Gmail API is mocked.

```sh
pytest
```

## Architecture

- `cli.py` — argument parsing and orchestration only.
- `gmail.py` — Gmail OAuth, search, MIME traversal, attachment download.
- `dataset.py` — local persistence: manifest load/save, id generation,
  deduplication.
- `models.py` — typed dataclasses shared across the above (`PdfAttachment`,
  `GmailMessageSummary`, `ManifestEntry`).

This is intentionally the whole feature set for v0.1. Deliberately **not**
included yet (by design, not oversight): OCR, AI/model-based extraction,
anonymization, cloud storage, a database, a web UI, or background workers.
The `dataset/raw/` → analyzer → extractor → golden-dataset pipeline this
will eventually feed is a separate, later project.
