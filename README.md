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
