import logging

import pytest
import requests

from services.evolution import parse_webhook_payload, send_text_message
from config import Config


def test_parses_plain_conversation_message():
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "Cristian revisa el stand mañana"},
        }
    }
    message = parse_webhook_payload(payload)
    assert message is not None
    assert message.group_jid == "120363429440515454@g.us"
    assert message.sender_jid == "573001112233@s.whatsapp.net"
    assert message.text == "Cristian revisa el stand mañana"
    assert message.mentioned_jids == []
    assert message.from_me is False


def test_parses_extended_text_message_with_mention():
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "extendedTextMessage": {
                    "text": "revisa el stand mañana @Cristian",
                    "contextInfo": {"mentionedJid": ["573004445566@s.whatsapp.net"]},
                }
            },
        }
    }
    message = parse_webhook_payload(payload)
    assert message is not None
    assert message.text == "revisa el stand mañana @Cristian"
    assert message.mentioned_jids == ["573004445566@s.whatsapp.net"]


def test_returns_none_when_data_missing():
    assert parse_webhook_payload({"event": "connection.update"}) is None


def test_returns_none_when_remote_jid_missing():
    payload = {"data": {"key": {}, "message": {"conversation": "hola"}}}
    assert parse_webhook_payload(payload) is None


def test_returns_none_when_no_text_present():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {"caption": "sin texto"}},
        }
    }
    assert parse_webhook_payload(payload) is None


def test_from_me_flag_is_read():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": True},
            "message": {"conversation": "aviso del propio bot"},
        }
    }
    message = parse_webhook_payload(payload)
    assert message.from_me is True


def test_handles_explicit_null_key():
    """Handles explicit null value in key field without raising AttributeError."""
    payload = {
        "data": {
            "key": None,
            "message": {"conversation": "texto"},
        }
    }
    assert parse_webhook_payload(payload) is None


def test_handles_explicit_null_message():
    """Handles explicit null value in message field without raising AttributeError."""
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": None,
        }
    }
    assert parse_webhook_payload(payload) is None


def test_handles_explicit_null_context_info():
    """Handles explicit null value in contextInfo field without raising AttributeError."""
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "extendedTextMessage": {
                    "text": "revisa el stand mañana",
                    "contextInfo": None,
                }
            },
        }
    }
    message = parse_webhook_payload(payload)
    assert message is not None
    assert message.text == "revisa el stand mañana"
    assert message.mentioned_jids == []


def test_logs_info_when_data_missing(caplog):
    caplog.set_level(logging.INFO)
    assert parse_webhook_payload({"event": "connection.update"}) is None
    assert any("data" in record.message.lower() for record in caplog.records)


def test_logs_info_when_remote_jid_missing(caplog):
    caplog.set_level(logging.INFO)
    payload = {"data": {"key": {}, "message": {"conversation": "hola"}}}
    assert parse_webhook_payload(payload) is None
    assert any("remotejid" in record.message.lower() for record in caplog.records)


def test_logs_info_when_text_missing(caplog):
    caplog.set_level(logging.INFO)
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {"caption": "sin texto"}},
        }
    }
    assert parse_webhook_payload(payload) is None
    assert any("text" in record.message.lower() for record in caplog.records)


def test_send_text_message_posts_to_evolution_api(monkeypatch):
    monkeypatch.setattr(Config, "EVOLUTION_API_URL", "https://evo.example.com")
    monkeypatch.setattr(Config, "EVOLUTION_API_KEY", "test-key")
    monkeypatch.setattr(Config, "EVOLUTION_INSTANCE", "my-instance")

    calls = []

    class FakeResponse:
        ok = True
        status_code = 200
        text = ""

        def raise_for_status(self):
            pass

    def fake_post(url, headers=None, json=None, timeout=None):
        calls.append({"url": url, "headers": headers, "json": json, "timeout": timeout})
        return FakeResponse()

    monkeypatch.setattr("services.evolution.requests.post", fake_post)

    send_text_message("120363429440515454@g.us", "hola")

    assert len(calls) == 1
    assert calls[0]["url"] == "https://evo.example.com/message/sendText/my-instance"
    assert calls[0]["json"] == {"number": "120363429440515454@g.us", "text": "hola"}
    assert calls[0]["headers"]["apikey"] == "test-key"


def test_send_text_message_raises_on_http_error(monkeypatch):
    monkeypatch.setattr(Config, "EVOLUTION_API_URL", "https://evo.example.com")
    monkeypatch.setattr(Config, "EVOLUTION_API_KEY", "test-key")
    monkeypatch.setattr(Config, "EVOLUTION_INSTANCE", "my-instance")

    class FakeResponse:
        ok = False
        status_code = 500
        text = "server error"

        def raise_for_status(self):
            raise requests.HTTPError("500 error")

    def fake_post(url, headers=None, json=None, timeout=None):
        return FakeResponse()

    monkeypatch.setattr("services.evolution.requests.post", fake_post)

    with pytest.raises(requests.HTTPError):
        send_text_message("120363429440515454@g.us", "hola")
