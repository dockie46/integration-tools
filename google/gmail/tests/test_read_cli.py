from gmail_read.client import GmailClient
from gmail_read.read_cli import run

from fakes import FakeService, fake_gmail_message


def test_read_cli_list(monkeypatch, capsys, tmp_path):
    service = FakeService({"m1": fake_gmail_message("m1", "Invoice 123")})
    monkeypatch.setattr(
        "gmail_read.read_cli.GmailClient.from_files",
        lambda *args, **kwargs: GmailClient(service),
    )
    token = tmp_path / "token.json"
    creds = tmp_path / "credentials.json"
    assert run(["--credentials", str(creds), "--token", str(token), "list", "--max", "1"]) == 0
    out = capsys.readouterr().out
    assert "Invoice 123" in out
    assert "m1" in out


def test_read_cli_get_json(monkeypatch, capsys, tmp_path):
    service = FakeService({"m1": fake_gmail_message("m1", "Hello")})
    monkeypatch.setattr(
        "gmail_read.read_cli.GmailClient.from_files",
        lambda *args, **kwargs: GmailClient(service),
    )
    token = tmp_path / "token.json"
    creds = tmp_path / "credentials.json"
    assert run(["--credentials", str(creds), "--token", str(token), "get", "m1", "--json"]) == 0
    payload = capsys.readouterr().out
    assert '"subject": "Hello"' in payload
