import base64

from gmail_read.gmail import extract_bodies, find_attachments, parse_message


def _b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


def test_extract_bodies_plain_and_html():
    payload = {
        "mimeType": "multipart/alternative",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"data": _b64("Hello plain")}},
            {"mimeType": "text/html", "filename": "", "body": {"data": _b64("<p>Hello html</p>")}},
        ],
    }
    text, html = extract_bodies(payload)
    assert text == "Hello plain"
    assert html == "<p>Hello html</p>"


def test_extract_bodies_skips_named_attachments():
    payload = {
        "mimeType": "multipart/mixed",
        "parts": [
            {"mimeType": "text/plain", "filename": "", "body": {"data": _b64("body")}},
            {"mimeType": "text/plain", "filename": "notes.txt", "body": {"data": _b64("attached")}},
        ],
    }
    text, html = extract_bodies(payload)
    assert text == "body"
    assert html is None


def test_find_attachments_named_parts_only():
    message = {
        "id": "m1",
        "payload": {
            "mimeType": "multipart/mixed",
            "parts": [
                {"mimeType": "text/plain", "filename": "", "body": {"data": _b64("hi")}},
                {
                    "mimeType": "application/pdf",
                    "filename": "invoice.pdf",
                    "body": {"attachmentId": "att1", "size": 12},
                },
            ],
        },
    }
    attachments = find_attachments(message)
    assert len(attachments) == 1
    assert attachments[0].filename == "invoice.pdf"
    assert attachments[0].attachment_id == "att1"
    assert attachments[0].size == 12


def test_parse_message_with_body():
    message = {
        "id": "m1",
        "threadId": "t1",
        "snippet": "Hello…",
        "labelIds": ["INBOX"],
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello"},
                {"name": "From", "value": "a@example.com"},
                {"name": "To", "value": "me@example.com"},
                {"name": "Date", "value": "Wed, 16 Sep 2026 10:00:00 +0000"},
                {"name": "Message-ID", "value": "<id@example.com>"},
            ],
            "mimeType": "text/plain",
            "body": {"data": _b64("Hello body")},
        },
    }
    parsed = parse_message(message, include_body=True)
    assert parsed.message_id == "m1"
    assert parsed.thread_id == "t1"
    assert parsed.subject == "Hello"
    assert parsed.sender == "a@example.com"
    assert parsed.to == "me@example.com"
    assert parsed.text_body == "Hello body"
    assert parsed.to_dict()["snippet"] == "Hello…"


def test_parse_message_without_body_skips_decode():
    message = {
        "id": "m1",
        "payload": {
            "headers": [{"name": "Subject", "value": "Hi"}],
            "mimeType": "text/plain",
            "body": {"data": _b64("secret")},
        },
    }
    parsed = parse_message(message, include_body=False)
    assert parsed.text_body is None
    assert parsed.html_body is None
    assert parsed.subject == "Hi"
