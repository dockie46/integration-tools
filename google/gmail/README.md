# gmail-read

Read Gmail with a **local client first**, then the same client on **AWS Lambda**.

```
Local client                         AWS Lambda
-------------                        ----------
gmail-read auth  (browser OAuth)
       │
       ▼
token.json  ─────────────────────►  GMAIL_TOKEN_JSON
gmail-read list / get               lambda_handler list / get
       │                                    │
       └──────── GmailClient ───────────────┘
```

Version 0.3 does **not** send email content to any third-party AI/OCR service.
Console and Lambda output only include headers, snippets, and the message body
you asked to read.

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

From the **repo root** (`integration-tools/`):

```sh
make init
source .venv/bin/activate
```

Or with uv directly:

```sh
uv sync
source .venv/bin/activate
```

## 4. Local client — read mail

Lambda cannot open a browser. Sign in once locally; `token.json` is what
Lambda will reuse (refresh only).

```sh
gmail-read auth
gmail-read list
gmail-read list --query 'newer_than:7d' --max 10
gmail-read get MESSAGE_ID
gmail-read get MESSAGE_ID --json
```

On first `auth` (or first `list`/`get` with no token) a browser window
opens and requests **read-only** Gmail access (`gmail.readonly`). The
token is cached in `token.json` and refreshed automatically later.

Example `list` output:

```
Query: in:inbox
Matching messages: 3
18abc123  Wed, 16 Sep 2026 10:00:00 +0000  shop@example.com  Invoice 2026-123
18abc124  Tue, 15 Sep 2026 09:12:00 +0000  alerts@example.com  Your receipt
```

## 5. AWS Lambda — same client, no browser

1. Run `gmail-read auth` locally so `token.json` contains a `refresh_token`.
2. Store that file's contents as a Lambda environment variable (or secret)
   named `GMAIL_TOKEN_JSON`. Optionally set `GMAIL_TOKEN_PATH` to a writable
   file if you want refreshed tokens persisted.
3. Set the handler to `gmail_read.handler.lambda_handler`.

Direct invoke event:

```json
{ "action": "list", "query": "in:inbox", "max_messages": 10 }
```

```json
{ "action": "get", "message_id": "18abc123" }
```

API Gateway proxy events work too — the JSON can live in `body`.

Minimal deploy from this package directory (Python 3.11):

```sh
python3.11 -m venv .venv
source .venv/bin/activate
pip install -e .
pip install -t dist/lambda .
cd dist/lambda
zip -r ../gmail-read-lambda.zip .
```

Upload the zip, runtime Python 3.11, handler
`gmail_read.handler.lambda_handler`. Timeout 30–60s is enough for small
`max_messages` values.

Do **not** put `credentials.json` / `token.json` in the zip. Put the token
in an env var or Secrets Manager, not in source control.

## Privacy

This tool processes **real personal email**. Keep in mind:

- Repo-root `credentials/credentials.json` and `token.json` grant read-only
  access to your Gmail account — both are git-ignored and must never be committed.
- `GMAIL_TOKEN_JSON` on Lambda is the same secret. Use env vars or Secrets
  Manager, never the deployment zip.
- No email content or metadata is ever logged in full, sent to any external
  service, or uploaded automatically. Console output only ever shows the
  subject/sender already visible in your own inbox.

## Running tests

From the repo root (no Gmail credentials needed — API is mocked):

```sh
make test
```

## Architecture

- `auth.py` — desktop OAuth (local) and refresh-token env auth (Lambda).
- `client.py` — `GmailClient` shared by CLI and Lambda (`list` / `get` /
  `download_attachment`).
- `read_cli.py` — `gmail-read auth|list|get`.
- `handler.py` — AWS Lambda entry (`lambda_handler`).
- `gmail.py` — Gmail API helpers, MIME traversal, body/attachment parse.
- `models.py` — typed dataclasses (`GmailMessage`, `AttachmentRef`, …).

Not included yet (by design): sending mail, write scopes, Calendar, Drive,
OCR, a database, or a web UI.
