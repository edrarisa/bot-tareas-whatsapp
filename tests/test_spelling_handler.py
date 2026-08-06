import threading

from services.image_batch import ImageBatchBuffer
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


def _run(payload, roster, lid_resolver, group_jid=GROUP_JID, batch_buffer=None):
    """Runs the handler for a single image with no real waiting -- used by
    tests that don't care about batching multiple images together."""
    handle_webhook_payload(
        payload,
        roster,
        lid_resolver,
        group_jid,
        batch_buffer or ImageBatchBuffer(),
        sleep=lambda seconds: None,
    )


def test_ignores_image_from_unknown_sender(monkeypatch):
    roster = FakeRoster({})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not review")),
    )

    _run(_payload("revisar ortografia"), roster, lid_resolver)


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

    _run(
        _payload("revisar ortografia", group_jid=OTHER_GROUP_JID),
        roster,
        lid_resolver,
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

    _run(_payload("revisar ortografia", from_me=True), roster, lid_resolver)

    assert sent == []


def test_ignores_image_without_keyword_in_caption(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("should not review")),
    )

    _run(_payload("aqui esta el diseño final"), roster, lid_resolver)


def test_u56_code_also_triggers_review(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details=["Sin errores"]),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    _run(_payload("u56"), roster, lid_resolver)

    assert len(sent) == 1


def test_keyword_matching_ignores_case_and_accents(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details=["Sin errores"]),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    _run(_payload("Porfa ORTOGRAFÍA de esto"), roster, lid_resolver)

    assert len(sent) == 1


def test_resolves_lid_sender_before_matching_roster(monkeypatch):
    sender_lid = "151556578083034@lid"
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver({sender_lid: SENDER_JID})
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details=["Sin errores"]),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    _run(_payload("revisar ortografia", sender_jid=sender_lid), roster, lid_resolver)

    assert len(sent) == 1


def test_replies_with_errors_when_found(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(
            has_errors=True,
            details=[
                "'campana' deberia ser 'campaña'",
                "Falta el signo de apertura '¡'",
            ],
        ),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message",
        lambda g, t: sent.append((g, t)),
    )

    _run(_payload("revisar ortografia"), roster, lid_resolver)

    assert len(sent) == 1
    group_jid, text = sent[0]
    assert group_jid == GROUP_JID
    assert "posibles errores" in text.lower()
    assert "• 'campana' deberia ser 'campaña'" in text
    assert "• Falta el signo de apertura '¡'" in text


def test_replies_confirming_no_errors(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details=["Sin errores"]),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    _run(_payload("revisar ortografia"), roster, lid_resolver)

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

    _run(_payload("revisar ortografia"), roster, lid_resolver)

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
        _run(_payload("revisar ortografia"), roster, lid_resolver)

    assert sent == []
    error_records = [r for r in caplog.records if r.levelname == "ERROR"]
    assert len(error_records) == 1
    assert len(error_records[0].message) < 500


def test_waits_before_deciding_whether_to_process(monkeypatch):
    """The handler must debounce -- wait a beat before acting -- so a
    sibling image sent milliseconds later has a chance to join the batch."""
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details=["Sin errores"]),
    )
    monkeypatch.setattr("handlers.spelling_handler.send_text_message", lambda g, t: None)

    sleep_calls = []

    handle_webhook_payload(
        _payload("revisar ortografia"),
        roster,
        lid_resolver,
        GROUP_JID,
        ImageBatchBuffer(),
        sleep=lambda seconds: sleep_calls.append(seconds),
    )

    assert sleep_calls == [4.0]


def test_multiple_images_from_same_sender_are_batched_and_all_reviewed(monkeypatch):
    """WhatsApp sends a multi-image send as separate messages, usually with
    only one of them carrying the caption. If any image in the batch has
    the keyword, every image in the batch must be reviewed and replied to
    -- including the ones with no caption at all."""
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()

    reviewed_images = []

    def fake_review(image_base64, mimetype, **kw):
        reviewed_images.append(image_base64)
        return SpellingReviewResult(has_errors=False, details=["Sin errores"])

    monkeypatch.setattr("handlers.spelling_handler.review_spelling", fake_review)
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    batch_buffer = ImageBatchBuffer()
    added_first_image = threading.Event()
    release_first_image = threading.Event()

    def sleep_and_wait_for_sibling(seconds):
        added_first_image.set()
        release_first_image.wait(timeout=2)

    # Image 1 carries the keyword; image 2 (sent right after, same sender,
    # no caption) does not -- mirrors a real WhatsApp multi-image send.
    payload_1 = _payload("revisar ortografia", base64="aW1hZ2Ux")
    payload_2 = _payload("", base64="aW1hZ2Uy")

    first_call = threading.Thread(
        target=handle_webhook_payload,
        args=(
            payload_1,
            roster,
            lid_resolver,
            GROUP_JID,
            batch_buffer,
            sleep_and_wait_for_sibling,
        ),
    )
    first_call.start()
    assert added_first_image.wait(timeout=2)

    # Simulate the sibling image arriving as a separate webhook call while
    # the first image is still inside its debounce window.
    handle_webhook_payload(
        payload_2,
        roster,
        lid_resolver,
        GROUP_JID,
        batch_buffer,
        sleep=lambda seconds: None,
    )

    release_first_image.set()
    first_call.join(timeout=2)

    assert sorted(reviewed_images) == ["aW1hZ2Ux", "aW1hZ2Uy"]
    assert len(sent) == 2
    assert any(text.startswith("Imagen 1 de 2:") for text in sent)
    assert any(text.startswith("Imagen 2 de 2:") for text in sent)


def test_single_image_reply_has_no_numbering_prefix(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    monkeypatch.setattr(
        "handlers.spelling_handler.review_spelling",
        lambda *a, **kw: SpellingReviewResult(has_errors=False, details=["Sin errores"]),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append(t)
    )

    _run(_payload("revisar ortografia"), roster, lid_resolver)

    assert len(sent) == 1
    assert not sent[0].startswith("Imagen")


def test_batch_without_keyword_in_any_image_is_ignored(monkeypatch):
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

    batch_buffer = ImageBatchBuffer()
    added_first_image = threading.Event()
    release_first_image = threading.Event()

    def sleep_and_wait_for_sibling(seconds):
        added_first_image.set()
        release_first_image.wait(timeout=2)

    payload_1 = _payload("", base64="aW1hZ2Ux")
    payload_2 = _payload("aqui esta el diseño final", base64="aW1hZ2Uy")

    first_call = threading.Thread(
        target=handle_webhook_payload,
        args=(
            payload_1,
            roster,
            lid_resolver,
            GROUP_JID,
            batch_buffer,
            sleep_and_wait_for_sibling,
        ),
    )
    first_call.start()
    assert added_first_image.wait(timeout=2)

    handle_webhook_payload(
        payload_2,
        roster,
        lid_resolver,
        GROUP_JID,
        batch_buffer,
        sleep=lambda seconds: None,
    )

    release_first_image.set()
    first_call.join(timeout=2)

    assert sent == []
