import json

from gmail_read.client import GmailClient
from gmail_read.handler import lambda_handler

from fakes import FakeService, fake_gmail_message


def test_client_list_and_get():
    service = FakeService(
        {
            "m1": fake_gmail_message("m1", "First"),
            "m2": fake_gmail_message("m2", "Second"),
        }
    )
    client = GmailClient(service)
    listed = client.list_messages("in:inbox", max_messages=2, include_body=False)
    assert [m.subject for m in listed] == ["First", "Second"]
    assert service.gets[0]["format"] == "metadata"

    got = client.get("m1", include_body=True)
    assert got.subject == "First"
    assert service.gets[-1]["format"] == "full"


def test_handler_list(monkeypatch):
    service = FakeService({"m1": fake_gmail_message("m1", "Invoice")})
    monkeypatch.setattr(
        "gmail_read.handler.GmailClient.from_env",
        lambda *args, **kwargs: GmailClient(service),
    )
    response = lambda_handler({"action": "list", "query": "in:inbox", "max_messages": 1}, None)
    assert response["statusCode"] == 200
    body = json.loads(response["body"])
    assert body["ok"] is True
    assert body["messages"][0]["subject"] == "Invoice"


def test_handler_get(monkeypatch):
    service = FakeService({"m1": fake_gmail_message("m1", "Hello")})
    monkeypatch.setattr(
        "gmail_read.handler.GmailClient.from_env",
        lambda *args, **kwargs: GmailClient(service),
    )
    response = lambda_handler({"action": "get", "message_id": "m1"}, None)
    body = json.loads(response["body"])
    assert body["ok"] is True
    assert body["message"]["subject"] == "Hello"


def test_handler_get_requires_id(monkeypatch):
    monkeypatch.setattr(
        "gmail_read.handler.GmailClient.from_env",
        lambda *args, **kwargs: GmailClient(FakeService({})),
    )
    response = lambda_handler({"action": "get"}, None)
    assert response["statusCode"] == 400


def test_handler_api_gateway_body(monkeypatch):
    service = FakeService({"m1": fake_gmail_message("m1", "Hello")})
    monkeypatch.setattr(
        "gmail_read.handler.GmailClient.from_env",
        lambda *args, **kwargs: GmailClient(service),
    )
    response = lambda_handler(
        {"body": json.dumps({"action": "list", "max_messages": 1})},
        None,
    )
    body = json.loads(response["body"])
    assert body["ok"] is True
    assert len(body["messages"]) == 1
