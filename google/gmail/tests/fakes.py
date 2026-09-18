class GetRequest:
    def __init__(self, payload):
        self.payload = payload

    def execute(self):
        return self.payload


class FakeService:
    def __init__(self, messages: dict[str, dict]):
        self._messages = messages
        self.gets: list[dict] = []

    def users(self):
        return self

    def messages(self):
        return self

    def list(self, **kwargs):
        ids = [{"id": message_id} for message_id in self._messages]
        max_results = kwargs.get("maxResults")
        if max_results is not None:
            ids = ids[:max_results]
        return GetRequest({"messages": ids})

    def get(self, **kwargs):
        self.gets.append(kwargs)
        return GetRequest(self._messages[kwargs["id"]])


def fake_gmail_message(message_id: str, subject: str) -> dict:
    return {
        "id": message_id,
        "threadId": f"t-{message_id}",
        "snippet": subject,
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": subject},
                {"name": "From", "value": "shop@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Wed, 16 Sep 2026 10:00:00 +0000"},
            ],
            "mimeType": "text/plain",
            "body": {},
        },
    }
