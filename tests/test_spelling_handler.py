from services.spelling_reviewer import SpellingReviewError, SpellingReviewResult
from handlers.spelling_handler import handle_webhook_payload

GROUP_JID = "120363429440515454@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"
SENDER_JID = "573001112233@s.whatsapp.net"


class FakeRoster:
    def __init__(self, known_jids):
        self._known = known_jids

    def is_known_sender(self, jid):
        return jid in self._known


class FakeLidResolver:
    def __init__(self, mapping=None):
        self._mapping = mapping or {}

    def resolve(self, jid):
        return self._mapping.get(jid, jid)


def _payload(caption, sender_jid=SENDER_JID, group_jid=GROUP_JID, from_me=False, base64="aGk="):
    return {
        "data": {
            "key": {"remoteJid": group_jid, "participant": sender_jid, "fromMe": from_me},
            "message": {"imageMessage": {"caption": caption}, "base64": base64},
        }
    }


def test_ignores_image_from_unknown_sender(monkeypatch):
    roster = FakeRoster({})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not review")),
    )

    handle_webhook_payload(_payload("revisar ortografia"), roster, lid_resolver, GROUP_JID)


def test_ignores_image_from_other_group(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not review")),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    handle_webhook_payload(
        _payload("revisar ortografia", group_jid=OTHER_GROUP_JID),
        roster,
        lid_resolver,
        GROUP_JID,
    )

    assert sent == []


def test_ignores_own_images(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not review")),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    handle_webhook_payload(
        _payload("revisar ortografia", from_me=True), roster, lid_resolver, GROUP_JID
    )

    assert sent == []


def test_ignores_image_without_keyword_in_caption(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not review")),
    )

    handle_webhook_payload(
        _payload("aqui esta el diseño final"), roster, lid_resolver, GROUP_JID
    )


def test_keyword_matching_ignores_case_and_accents(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details="Sin errores"),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    handle_webhook_payload(
        _payload("Porfa ORTOGRAFÍA de esto"), roster, lid_resolver, GROUP_JID
    )

    assert len(sent) == 1


def test_resolves_lid_sender_before_matching_roster(monkeypatch):
    sender_lid = "151556578083034@lid"
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver({sender_lid: SENDER_JID})
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details="Sin errores"),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    handle_webhook_payload(
        _payload("revisar ortografia", sender_jid=sender_lid), roster, lid_resolver, GROUP_JID
    )

    assert len(sent) == 1


def test_replies_with_errors_when_found(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(
            has_errors=True, details="'campana' deberia ser 'campaña'"
        ),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message",
        lambda g, t: sent.append((g, t)),
    )

    handle_webhook_payload(_payload("revisar ortografia"), roster, lid_resolver, GROUP_JID)

    assert len(sent) == 1
    group_jid, text = sent[0]
    assert group_jid == GROUP_JID
    assert "posibles errores" in text.lower()
    assert "campana" in text


def test_replies_confirming_no_errors(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details="Sin errores"),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    handle_webhook_payload(_payload("revisar ortografia"), roster, lid_resolver, GROUP_JID)

    assert len(sent) == 1
    assert "no encontré errores" in sent[0].lower()


def test_ignores_review_errors_without_replying(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()

    def raise_error(*a, **kw):
        raise SpellingReviewError("timeout")

    monkeypatch.setattr("handlers.spelling_handler.review_spelling", raise_error)
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    handle_webhook_payload(_payload("revisar ortografia"), roster, lid_resolver, GROUP_JID)

    assert sent == []


def test_truncates_long_error_messages_in_logs(monkeypatch, caplog):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()

    def raise_error(*a, **kw):
        raise SpellingReviewError("x" * 1000)

    monkeypatch.setattr("handlers.spelling_handler.review_spelling", raise_error)
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    with caplog.at_level("ERROR"):
        handle_webhook_payload(_payload("revisar ortografia"), roster, lid_resolver, GROUP_JID)

    assert sent == []
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert len(error_records[0].message) < 500
