# integration-tools

Personal integration tooling — Google, iCloud, and more via a shared **Providers** factory.

```sh
make init && source .envrc
uv run python main.py
make test
```

```
integration-tools/
  google/                  # OAuth, Gmail, Calendar
  icloud/                  # IMAP + CalDAV
  integration_providers/   # factory package (import: integration_providers)
  credentials/             # secrets — never commit
  main.py
```

## Providers API

```python
from integration_providers import Providers

p = Providers.discover()
emails = p.read_emails("google", "icloud", limit=5)
events = p.read_calendar(limit=10)

# Which calendars exist?
for cal in p.list_calendars("google", "icloud"):
    print(cal.provider, cal.id, cal.name)
```

## Multi-tenant / web apps (Softwareify Company Platform)

No files, no browser on the server: the app redirects the user to Google, stores the grant as a secret
(e.g. AWS Secrets Manager) and every client is built from that secret.

```python
from google_oauth import OAuthClient, authorization_url, exchange_code, new_pkce, new_state, scopes_for

client = OAuthClient(client_id, client_secret, "https://app.example.com/oauth/google/callback")
verifier, challenge = new_pkce()
url = authorization_url(client, scopes_for("calendar", "drive"), state=new_state(), code_challenge=challenge)
# ... redirect back with ?code=...
secret = exchange_code(client, code, code_verifier=verifier).to_secret(client)  # store this

from integration_providers.google_provider import GoogleProvider
events = GoogleProvider.from_secret(secret).read_calendar(limit=10)
```

Calendar sync (bookings → calendar, availability, meeting-room displays):

```python
from datetime import UTC, datetime, timedelta
from integration_providers import EventWrite

google = GoogleProvider.from_secret(secret, calendar_ids=["primary", "room@group.calendar.google.com"])
start = datetime.now(UTC); end = start + timedelta(days=1)

google.list_events_between(start, end)   # CalendarEventItem, UTC, recurring expanded, busy flag
google.free_busy(start, end)             # FreeBusyResult(items=[BusyItem], errors={calendar: reason})
google.upsert_event("primary", EventWrite("Rental: Box 1", start, end, external_key="booking-42",
                                          time_zone="Europe/Prague"))  # same key -> same event
google.delete_event("primary", "booking-42")
```

The key is stored in a private extended property (`sourceKey`), so the app never needs Google's event id.
Writing needs the `calendar` service scopes; reading works with `calendar_readonly`.

Calendars of the app's own and syncing changes back:

```python
room = google.create_calendar("Zasedačka 1", time_zone="Europe/Prague")   # needs calendar_manage
google.share_calendar(room.id, "recepce@firma.cz", role="writer")

step = google.sync_events(room.id, token=stored_token, since=start)       # CalendarSyncResult
# step.changed / step.deleted_ids; store step.next_token. step.full: replace, don't merge.
# Events the app wrote carry external_key, events people made in Google do not.
```

Errors to act on: `GoogleTokenRevokedError` and `GoogleScopesMissingError` mean "connect the account
again"; `CredentialsMissingError` means the stored secret is incomplete. The OAuth client must be of type
**Web application** with the app's redirect URI registered.

## Credentials

**Google**

- OAuth: `credentials/credentials.json` + `token.json`
- Optional calendar filter: `credentials/google.json`

```json
{ "calendars": ["primary", "xyz@group.calendar.google.com"] }
```

Use calendar **ids** from `list_calendars("google")`. Default without the file: `primary` only.

**iCloud**

- `credentials/icloud.json` — `email`, app-specific `password`, optional `calendars` (display **names**)

```json
{
  "email": "you@icloud.com",
  "password": "xxxx-xxxx-xxxx-xxxx",
  "calendars": ["Home", "Work"]
}
```

See [google/gmail/README.md](google/gmail/README.md) and [icloud/README.md](icloud/README.md).
