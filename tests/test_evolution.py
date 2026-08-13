import logging

import pytest
import requests

from services.evolution import (
    IncomingImageMessage,
    parse_image_messages,
    parse_webhook_payload,
    send_text_message,
)
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
    messages = parse_webhook_payload(payload)
    assert len(messages) == 1
    message = messages[0]
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
    messages = parse_webhook_payload(payload)
    assert len(messages) == 1
    assert messages[0].text == "revisa el stand mañana @Cristian"
    assert messages[0].mentioned_jids == ["573004445566@s.whatsapp.net"]


def test_extracts_mention_from_plain_conversation_text_as_fallback():
    """WhatsApp/Evolution sometimes sends a plain 'conversation' message with
    the mention embedded as literal '@<number>' text and no structured
    contextInfo.mentionedJid at all -- this must still resolve as a mention."""
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "@203744859922485 porfa revisar las horas"},
        }
    }
    messages = parse_webhook_payload(payload)
    assert len(messages) == 1
    assert messages[0].mentioned_jids == ["203744859922485@lid"]


def test_does_not_extract_a_mention_from_text_with_no_at_sign():
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {"conversation": "hay que revisar el stand mañana"},
        }
    }
    messages = parse_webhook_payload(payload)
    assert messages[0].mentioned_jids == []


def test_prefers_structured_mentions_over_text_fallback():
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "extendedTextMessage": {
                    "text": "revisa el stand @Cristian",
                    "contextInfo": {"mentionedJid": ["573004445566@s.whatsapp.net"]},
                }
            },
        }
    }
    messages = parse_webhook_payload(payload)
    assert messages[0].mentioned_jids == ["573004445566@s.whatsapp.net"]


def test_parses_data_as_a_list_of_messages():
    """Evolution API sometimes sends 'data' as a list of message objects
    (e.g. several messages in one MESSAGES_UPSERT call) instead of a single
    object -- both messages in the list should be parsed."""
    payload = {
        "data": [
            {
                "key": {
                    "remoteJid": "120363429440515454@g.us",
                    "participant": "573001112233@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {"conversation": "primer mensaje"},
            },
            {
                "key": {
                    "remoteJid": "120363429440515454@g.us",
                    "participant": "573004445566@s.whatsapp.net",
                    "fromMe": False,
                },
                "message": {"conversation": "segundo mensaje"},
            },
        ]
    }
    messages = parse_webhook_payload(payload)
    assert len(messages) == 2
    assert messages[0].text == "primer mensaje"
    assert messages[0].sender_jid == "573001112233@s.whatsapp.net"
    assert messages[1].text == "segundo mensaje"
    assert messages[1].sender_jid == "573004445566@s.whatsapp.net"


def test_skips_unparseable_items_in_a_list_but_keeps_the_rest():
    payload = {
        "data": [
            {"key": {}, "message": {"conversation": "sin remoteJid"}},
            {
                "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
                "message": {"conversation": "este si sirve"},
            },
        ]
    }
    messages = parse_webhook_payload(payload)
    assert len(messages) == 1
    assert messages[0].text == "este si sirve"


def test_returns_empty_list_when_data_missing():
    assert parse_webhook_payload({"event": "connection.update"}) == []


def test_returns_empty_list_when_remote_jid_missing():
    payload = {"data": {"key": {}, "message": {"conversation": "hola"}}}
    assert parse_webhook_payload(payload) == []


def test_returns_empty_list_when_no_text_present():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {"caption": "sin texto"}},
        }
    }
    assert parse_webhook_payload(payload) == []


def test_from_me_flag_is_read():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": True},
            "message": {"conversation": "aviso del propio bot"},
        }
    }
    messages = parse_webhook_payload(payload)
    assert messages[0].from_me is True


def test_handles_explicit_null_key():
    """Handles explicit null value in key field without raising AttributeError."""
    payload = {
        "data": {
            "key": None,
            "message": {"conversation": "texto"},
        }
    }
    assert parse_webhook_payload(payload) == []


def test_handles_explicit_null_message():
    """Handles explicit null value in message field without raising AttributeError."""
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": None,
        }
    }
    assert parse_webhook_payload(payload) == []


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
    messages = parse_webhook_payload(payload)
    assert len(messages) == 1
    assert messages[0].text == "revisa el stand mañana"
    assert messages[0].mentioned_jids == []


def test_logs_info_when_data_missing(caplog):
    caplog.set_level(logging.INFO)
    assert parse_webhook_payload({"event": "connection.update"}) == []
    assert any("data" in record.message.lower() for record in caplog.records)


def test_logs_info_when_remote_jid_missing(caplog):
    caplog.set_level(logging.INFO)
    payload = {"data": {"key": {}, "message": {"conversation": "hola"}}}
    assert parse_webhook_payload(payload) == []
    assert any("remotejid" in record.message.lower() for record in caplog.records)


def test_logs_info_when_text_missing(caplog):
    caplog.set_level(logging.INFO)
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {"caption": "sin texto"}},
        }
    }
    assert parse_webhook_payload(payload) == []
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


def test_send_text_message_includes_mentioned_when_given(monkeypatch):
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
        calls.append({"json": json})
        return FakeResponse()

    monkeypatch.setattr("services.evolution.requests.post", fake_post)

    send_text_message(
        "120363429440515454@g.us", "@573001112233 hola", mentioned=["573001112233@s.whatsapp.net"]
    )

    assert calls[0]["json"] == {
        "number": "120363429440515454@g.us",
        "text": "@573001112233 hola",
        "mentioned": ["573001112233@s.whatsapp.net"],
    }


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


def test_parses_image_message_with_caption_and_base64():
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "imageMessage": {"caption": "revisar ortografía porfa", "mimetype": "image/png"},
                "base64": "aGVsbG8=",
            },
        }
    }
    messages = parse_image_messages(payload)
    assert len(messages) == 1
    message = messages[0]
    assert message.group_jid == "120363429440515454@g.us"
    assert message.sender_jid == "573001112233@s.whatsapp.net"
    assert message.caption == "revisar ortografía porfa"
    assert message.image_base64 == "aGVsbG8="
    assert message.mimetype == "image/png"
    assert message.from_me is False


def test_defaults_mimetype_when_missing():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {"caption": "ortografia"}, "base64": "aGVsbG8="},
        }
    }
    messages = parse_image_messages(payload)
    assert messages[0].mimetype == "image/jpeg"


def test_defaults_caption_to_empty_string_when_missing():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {}, "base64": "aGVsbG8="},
        }
    }
    messages = parse_image_messages(payload)
    assert messages[0].caption == ""


def test_returns_empty_list_when_no_base64_content():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {"caption": "ortografia"}},
        }
    }
    assert parse_image_messages(payload) == []


def test_returns_empty_list_when_no_image_message():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"conversation": "hola", "base64": "aGVsbG8="},
        }
    }
    assert parse_image_messages(payload) == []


def test_returns_empty_list_when_no_remote_jid():
    payload = {
        "data": {
            "key": {},
            "message": {"imageMessage": {"caption": "ortografia"}, "base64": "aGVsbG8="},
        }
    }
    assert parse_image_messages(payload) == []


def test_parses_image_data_as_a_list():
    payload = {
        "data": [
            {
                "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
                "message": {"imageMessage": {"caption": "ortografia 1"}, "base64": "aGVsbG8="},
            },
            {
                "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
                "message": {"imageMessage": {"caption": "ortografia 2"}, "base64": "d29ybGQ="},
            },
        ]
    }
    messages = parse_image_messages(payload)
    assert len(messages) == 2
    assert messages[0].caption == "ortografia 1"
    assert messages[1].caption == "ortografia 2"


def test_handles_explicit_null_key_for_images():
    payload = {
        "data": {
            "key": None,
            "message": {"imageMessage": {"caption": "ortografia"}, "base64": "aGVsbG8="},
        }
    }
    assert parse_image_messages(payload) == []


def test_handles_explicit_null_message_for_images():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": None,
        }
    }
    assert parse_image_messages(payload) == []


def test_skips_unparseable_image_items_in_a_list_but_keeps_the_rest():
    payload = {
        "data": [
            {"key": {}, "message": {"imageMessage": {"caption": "sin remoteJid"}, "base64": "aGk="}},
            {
                "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
                "message": {"imageMessage": {"caption": "este si sirve"}, "base64": "aGk="},
            },
        ]
    }
    messages = parse_image_messages(payload)
    assert len(messages) == 1
    assert messages[0].caption == "este si sirve"
