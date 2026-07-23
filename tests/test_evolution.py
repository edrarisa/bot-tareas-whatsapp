from services.evolution import parse_webhook_payload


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
