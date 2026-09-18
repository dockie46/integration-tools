# iCloud Mail + Calendar

Uses an **Apple ID email** + **app-specific password** (not the normal Apple ID password).

## Setup

1. [appleid.apple.com](https://appleid.apple.com) → Sign-In and Security → App-Specific Passwords
2. Create a password (e.g. label `integration-tools`)
3. Save as `credentials/icloud.json` (never commit):

```json
{
  "email": "you@icloud.com",
  "password": "xxxx-xxxx-xxxx-xxxx",
  "calendars": ["Home", "Work"]
}
```

`calendars` is optional — display names (case-insensitive). Omit it to read **all** calendars.

List names first:

```python
from integration_providers import Providers
print(Providers.discover().list_calendars("icloud"))
```

## Usage

```sh
uv run python main.py
```

Mail: IMAP `imap.mail.me.com`  
Calendar: CalDAV `https://caldav.icloud.com/`
