import base64
import json

import pytest
from googleapiclient.errors import HttpError

from gmail_read.gmail import (
    _decode_inline_data,
    _execute_with_retry,
    download_attachment,
    summarize_message,
)


class _FakeResp:
    def __init__(self, status: int, reason: str = ""):
        self.status = status
        self.reason = reason


def _rate_limit_error() -> HttpError:
    content = json.dumps(
        {
            "error": {
                "message": "Quota exceeded",
                "errors": [{"message": "Quota exceeded", "domain": "usageLimits", "reason": "rateLimitExceeded"}],
            }
        }
    ).encode("utf-8")
    return HttpError(_FakeResp(403), content)


def _not_found_error() -> HttpError:
    content = json.dumps(
        {"error": {"message": "Not Found", "errors": [{"message": "Not Found", "reason": "notFound"}]}}
    ).encode("utf-8")
    return HttpError(_FakeResp(404), content)


class _FakeRequest:
    def __init__(self, side_effects):
        self._side_effects = list(side_effects)
        self.calls = 0

    def execute(self):
        self.calls += 1
        effect = self._side_effects.pop(0)
        if isinstance(effect, Exception):
            raise effect
        return effect


def test_execute_with_retry_succeeds_first_try():
    request = _FakeRequest(["ok"])
    assert _execute_with_retry(request) == "ok"
    assert request.calls == 1


def test_execute_with_retry_retries_on_rate_limit_then_succeeds(monkeypatch):
    monkeypatch.setattr("gmail_read.gmail.time.sleep", lambda _seconds: None)
    request = _FakeRequest([_rate_limit_error(), _rate_limit_error(), "ok"])
    assert _execute_with_retry(request) == "ok"
    assert request.calls == 3


def test_execute_with_retry_reraises_non_rate_limit_error():
    request = _FakeRequest([_not_found_error()])
    with pytest.raises(HttpError):
        _execute_with_retry(request)
    assert request.calls == 1


def test_execute_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("gmail_read.gmail.time.sleep", lambda _seconds: None)
    request = _FakeRequest([_rate_limit_error()] * 4)
    with pytest.raises(HttpError):
        _execute_with_retry(request, max_retries=3)
    assert request.calls == 4


def test_decode_inline_data_invalid_base64_raises():
    with pytest.raises(ValueError):
        _decode_inline_data("not valid base64 !!!")


def test_summarize_message_extracts_headers():
    message = {
        "id": "m1",
        "payload": {
            "headers": [
                {"name": "Subject", "value": "Hello 123"},
                {"name": "From", "value": "shop@example.com"},
                {"name": "Date", "value": "Mon, 1 Jan 2026 00:00:00 +0000"},
                {"name": "Message-ID", "value": "<abc@example.com>"},
            ]
        },
    }
    summary = summarize_message(message)
    assert summary.subject == "Hello 123"
    assert summary.sender == "shop@example.com"
    assert summary.message_id_header == "<abc@example.com>"


def test_summarize_message_missing_headers_uses_defaults():
    message = {"id": "m1", "payload": {"headers": []}}
    summary = summarize_message(message)
    assert summary.subject == "(no subject)"
    assert summary.sender == "(unknown sender)"


def test_download_attachment_fetches_by_attachment_id():
    raw = b"downloaded-bytes"
    encoded = base64.urlsafe_b64encode(raw).decode()

    class FakeAttachments:
        def get(self, userId, messageId, id):
            assert messageId == "m1"
            assert id == "att1"
            return self

        def execute(self):
            return {"data": encoded}

    class FakeMessages:
        def attachments(self):
            return FakeAttachments()

    class FakeUsers:
        def messages(self):
            return FakeMessages()

    class FakeService:
        def users(self):
            return FakeUsers()

    result = download_attachment(FakeService(), "m1", "att1")
    assert result == raw


def test_download_attachment_without_id_raises():
    class FakeService:
        def users(self):
            raise AssertionError("should not call API")

    with pytest.raises(ValueError):
        download_attachment(FakeService(), "m1", "")
