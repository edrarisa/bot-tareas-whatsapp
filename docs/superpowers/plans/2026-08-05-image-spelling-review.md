# Revisión de Ortografía en Imágenes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a second, independent capability to the bot: when someone from the "Equipo" roster sends an image captioned with the word "ortografía", review the image's Spanish spelling with OpenAI's vision model and always reply in the group with the result.

**Architecture:** Runs in parallel to the existing task-tracking flow, sharing the same webhook, roster, and LID resolver, but with its own parsing (`parse_image_messages`), its own OpenAI call (`review_spelling`), and its own orchestration (`handlers/spelling_handler.py`). `main.py`'s webhook route calls both handlers independently, each wrapped in its own try/except so a failure in one never blocks the other.

**Tech Stack:** Same as the rest of the bot — Python 3.13, FastAPI, `openai` SDK (GPT-4o mini vision), `requests`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-05-image-spelling-review-design.md`

---

## File Structure

```
bot-tareas-whatsapp/
├── main.py                          MODIFY: call both task and spelling handlers, isolated
├── services/
│   ├── evolution.py                 MODIFY: add parse_image_messages + IncomingImageMessage
│   └── spelling_reviewer.py         CREATE: review_spelling() via OpenAI vision
├── handlers/
│   └── spelling_handler.py          CREATE: filter (group/sender/keyword) -> review -> reply
└── tests/
    ├── test_evolution.py            MODIFY: tests for parse_image_messages
    ├── test_spelling_reviewer.py    CREATE
    ├── test_spelling_handler.py     CREATE
    └── test_main.py                 REWRITE: both handlers wired + isolated failures
```

---

## Task 1: Evolution API — parsing incoming image messages

**Files:**
- Modify: `services/evolution.py`
- Modify: `tests/test_evolution.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_evolution.py`:

```python
from services.evolution import IncomingImageMessage, parse_image_messages


def test_parses_image_message_with_caption_and_base64():
    payload = {
        "data": {
            "key": {
                "remoteJid": "120363429440515454@g.us",
                "participant": "573001112233@s.whatsapp.net",
                "fromMe": False,
            },
            "message": {
                "imageMessage": {"caption": "revisar ortografía porfa", "mimetype": "image/png"}
            },
            "base64": "aGVsbG8=",
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
            "message": {"imageMessage": {"caption": "ortografia"}},
            "base64": "aGVsbG8=",
        }
    }
    messages = parse_image_messages(payload)
    assert messages[0].mimetype == "image/jpeg"


def test_defaults_caption_to_empty_string_when_missing():
    payload = {
        "data": {
            "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
            "message": {"imageMessage": {}},
            "base64": "aGVsbG8=",
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
            "message": {"conversation": "hola"},
            "base64": "aGVsbG8=",
        }
    }
    assert parse_image_messages(payload) == []


def test_returns_empty_list_when_no_remote_jid():
    payload = {
        "data": {
            "key": {},
            "message": {"imageMessage": {"caption": "ortografia"}},
            "base64": "aGVsbG8=",
        }
    }
    assert parse_image_messages(payload) == []


def test_parses_image_data_as_a_list():
    payload = {
        "data": [
            {
                "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
                "message": {"imageMessage": {"caption": "ortografia 1"}},
                "base64": "aGVsbG8=",
            },
            {
                "key": {"remoteJid": "120363429440515454@g.us", "fromMe": False},
                "message": {"imageMessage": {"caption": "ortografia 2"}},
                "base64": "d29ybGQ=",
            },
        ]
    }
    messages = parse_image_messages(payload)
    assert len(messages) == 2
    assert messages[0].caption == "ortografia 1"
    assert messages[1].caption == "ortografia 2"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evolution.py -v`
Expected: FAIL with `ImportError: cannot import name 'IncomingImageMessage'`

- [ ] **Step 3: Add `IncomingImageMessage` and `parse_image_messages` to `services/evolution.py`**

Append to `services/evolution.py` (after the existing `IncomingMessage` dataclass and before
`send_text_message`):

```python
@dataclass
class IncomingImageMessage:
    group_jid: str
    sender_jid: str
    caption: str
    image_base64: str
    mimetype: str
    from_me: bool


def parse_image_messages(payload: dict) -> list[IncomingImageMessage]:
    """Returns the parseable image messages found in the payload (possibly empty).

    Requires the Evolution API instance to have "Webhook Base64" enabled, so
    the image content arrives directly in the payload as a "base64" field --
    without it, there is nothing here to send to the spelling reviewer.
    """
    data = payload.get("data")
    if not data:
        return []

    items = data if isinstance(data, list) else [data]

    messages = []
    for item in items:
        message = _parse_image_item(item)
        if message is not None:
            messages.append(message)
    return messages


def _parse_image_item(item: dict) -> IncomingImageMessage | None:
    key = item.get("key") or {}
    group_jid = key.get("remoteJid")
    if not group_jid:
        return None

    message = item.get("message") or {}
    image_message = message.get("imageMessage")
    if not image_message:
        return None

    image_base64 = item.get("base64")
    if not image_base64:
        logger.info(
            "Ignoring image message with no base64 content -- check that "
            "'Webhook Base64' is enabled on the Evolution API instance. Raw item: %s",
            repr(item)[:800],
        )
        return None

    sender_jid = key.get("participant") or group_jid
    from_me = bool(key.get("fromMe", False))
    caption = image_message.get("caption") or ""
    mimetype = image_message.get("mimetype") or "image/jpeg"

    return IncomingImageMessage(
        group_jid=group_jid,
        sender_jid=sender_jid,
        caption=caption,
        image_base64=image_base64,
        mimetype=mimetype,
        from_me=from_me,
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evolution.py -v`
Expected: PASS (all tests in the file, including the 7 new ones)

- [ ] **Step 5: Commit**

```bash
git add services/evolution.py tests/test_evolution.py
git commit -m "Add image message parsing to Evolution API integration"
```

---

## Task 2: Spelling reviewer — OpenAI vision call

**Files:**
- Create: `services/spelling_reviewer.py`
- Test: `tests/test_spelling_reviewer.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_spelling_reviewer.py
import json

import pytest

from services.spelling_reviewer import (
    SpellingReviewError,
    SpellingReviewResult,
    review_spelling,
)


class FakeCompletions:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise_exc = raise_exc
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        if self._raise_exc:
            raise self._raise_exc
        return FakeResponse(self._content)


class FakeChat:
    def __init__(self, **kwargs):
        self.completions = FakeCompletions(**kwargs)


class FakeClient:
    def __init__(self, **kwargs):
        self.chat = FakeChat(**kwargs)


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


def test_detects_spelling_errors():
    content = json.dumps(
        {"has_errors": True, "details": "'campana' deberia ser 'campaña'"}
    )
    client = FakeClient(content=content)

    result = review_spelling("aGVsbG8=", "image/png", client=client)

    assert result == SpellingReviewResult(
        has_errors=True, details="'campana' deberia ser 'campaña'"
    )


def test_confirms_no_errors():
    content = json.dumps({"has_errors": False, "details": "Sin errores detectados"})
    client = FakeClient(content=content)

    result = review_spelling("aGVsbG8=", "image/png", client=client)

    assert result.has_errors is False


def test_sends_image_as_data_url_to_openai():
    content = json.dumps({"has_errors": False, "details": "Sin errores"})
    client = FakeClient(content=content)

    review_spelling("aGVsbG8=", "image/png", client=client)

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["model"] == "gpt-4o-mini"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["timeout"] == 30
    user_message = kwargs["messages"][1]
    assert user_message["role"] == "user"
    image_url = user_message["content"][0]["image_url"]["url"]
    assert image_url == "data:image/png;base64,aGVsbG8="


def test_raises_error_on_invalid_json():
    client = FakeClient(content="not json")

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_on_missing_key():
    client = FakeClient(content=json.dumps({"details": "x"}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_api_call_fails():
    client = FakeClient(raise_exc=RuntimeError("timeout"))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_has_errors_is_not_a_bool():
    client = FakeClient(content=json.dumps({"has_errors": "yes", "details": "x"}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_details_is_missing_or_empty():
    client = FakeClient(content=json.dumps({"has_errors": False, "details": ""}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spelling_reviewer.py -v`
Expected: FAIL with `ImportError: cannot import name 'SpellingReviewError'`

- [ ] **Step 3: Write `services/spelling_reviewer.py`**

```python
"""
Reviews the Spanish spelling of text visible in an image, using OpenAI's
vision-capable chat completions API.
"""
import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from config import Config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


class SpellingReviewError(Exception):
    pass


@dataclass
class SpellingReviewResult:
    has_errors: bool
    details: str


SYSTEM_PROMPT = """Eres un corrector ortográfico en español. Analiza el texto visible en la \
imagen y revisa si tiene errores de ortografía.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "has_errors": true si encontraste al menos un error de ortografía, false si no.
- "details": si has_errors es true, describe cada error encontrado (la palabra mal escrita y \
cuál sería la forma correcta), separados por punto y coma si hay más de uno. Si has_errors es \
false, un mensaje corto confirmando que no hay errores."""


def review_spelling(
    image_base64: str, mimetype: str, client: OpenAI | None = None
) -> SpellingReviewResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mimetype};base64,{image_base64}"},
                        }
                    ],
                },
            ],
        )
        data = json.loads(response.choices[0].message.content)
        has_errors = data["has_errors"]
        details = data["details"]
        if not isinstance(has_errors, bool):
            raise ValueError(f"has_errors must be a bool, got {type(has_errors).__name__}")
        if not isinstance(details, str) or not details:
            raise ValueError("details must be a non-empty string")
        return SpellingReviewResult(has_errors=has_errors, details=details)
    except Exception as exc:
        logger.warning(f"Spelling reviewer failed: {exc}")
        raise SpellingReviewError(str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spelling_reviewer.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add services/spelling_reviewer.py tests/test_spelling_reviewer.py
git commit -m "Add OpenAI vision-based spelling reviewer"
```

---

## Task 3: Spelling handler — filter, review, reply

**Files:**
- Create: `handlers/spelling_handler.py`
- Test: `tests/test_spelling_handler.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_spelling_handler.py
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
            "message": {"imageMessage": {"caption": caption}},
            "base64": base64,
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spelling_handler.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_webhook_payload'`

- [ ] **Step 3: Write `handlers/spelling_handler.py`**

```python
"""
Orchestrates a single incoming image message: parse -> filter (group, known
sender, keyword in caption) -> review spelling with OpenAI -> always reply
in the group with the result.
"""
import logging
import unicodedata

from services.evolution import parse_image_messages, send_text_message
from services.spelling_reviewer import SpellingReviewError, review_spelling

logger = logging.getLogger(__name__)

_KEYWORD = "ortografia"


def handle_webhook_payload(payload: dict, roster, lid_resolver, group_jid: str) -> None:
    for message in parse_image_messages(payload):
        _handle_image_message(message, roster, lid_resolver, group_jid)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _handle_image_message(message, roster, lid_resolver, group_jid: str) -> None:
    if message.from_me or message.group_jid != group_jid:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid)

    if not roster.is_known_sender(sender_jid):
        return

    if _KEYWORD not in _normalize(message.caption):
        return

    try:
        result = review_spelling(message.image_base64, message.mimetype)
    except SpellingReviewError:
        logger.exception("Spelling review failed for message from %s", sender_jid)
        return

    if result.has_errors:
        reply = f"⚠️ Encontré posibles errores de ortografía: {result.details}"
    else:
        reply = "✅ Ortografía revisada, no encontré errores."

    send_text_message(group_jid, reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spelling_handler.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add handlers/spelling_handler.py tests/test_spelling_handler.py
git commit -m "Add spelling handler orchestration"
```

---

## Task 4: Wire both handlers into the FastAPI webhook route

**Files:**
- Modify: `main.py`
- Modify: `tests/test_main.py` (full rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the entire contents of `tests/test_main.py` with:

```python
from fastapi.testclient import TestClient

import main


def test_webhook_delegates_to_both_handlers(monkeypatch):
    task_calls = []
    spelling_calls = []

    def fake_task_handler(payload, roster, lid_resolver, sheets_client, group_jid):
        task_calls.append((payload, roster, lid_resolver, sheets_client, group_jid))

    def fake_spelling_handler(payload, roster, lid_resolver, group_jid):
        spelling_calls.append((payload, roster, lid_resolver, group_jid))

    monkeypatch.setattr(main, "handle_task_payload", fake_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert task_calls == [
        (body, "fake-roster", "fake-lid-resolver", "fake-sheets-client", "120363429440515454@g.us")
    ]
    assert spelling_calls == [
        (body, "fake-roster", "fake-lid-resolver", "120363429440515454@g.us")
    ]


def test_webhook_returns_200_even_if_task_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, sheets_client, group_jid):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", raising_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: None)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_webhook_returns_200_even_if_spelling_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, group_jid):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", lambda *a: None)
    monkeypatch.setattr(main, "handle_spelling_payload", raising_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_spelling_handler_still_runs_when_task_handler_raises(monkeypatch):
    """The two handlers are independent -- one failing must not block the other."""
    spelling_calls = []

    def raising_task_handler(payload, roster, lid_resolver, sheets_client, group_jid):
        raise RuntimeError("boom")

    def fake_spelling_handler(payload, roster, lid_resolver, group_jid):
        spelling_calls.append(payload)

    monkeypatch.setattr(main, "handle_task_payload", raising_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert spelling_calls == [body]


def test_webhook_returns_200_on_malformed_json_body(monkeypatch):
    task_calls = []
    spelling_calls = []
    monkeypatch.setattr(main, "handle_task_payload", lambda *a: task_calls.append(a))
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: spelling_calls.append(a))
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    response = client.post(
        "/webhook", content=b"not-json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200
    assert task_calls == []
    assert spelling_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `AttributeError: module 'main' has no attribute 'handle_task_payload'`

- [ ] **Step 3: Replace `main.py` with the version below**

```python
"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler and the spelling-review handler. Google Sheets / roster clients
are created lazily on startup so importing this module has no side effects
(needed for testing).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from config import Config
from handlers.spelling_handler import handle_webhook_payload as handle_spelling_payload
from handlers.task_handler import handle_webhook_payload as handle_task_payload
from services.lid_resolver import LidResolver
from services.roster import Roster
from services.sheets_client import create_sheets_client

logging.basicConfig(level=Config.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.validate()
    sheets_client = create_sheets_client(Config.GOOGLE_SHEETS_ID, Config.GOOGLE_CREDENTIALS_PATH)
    app.state.sheets_client = sheets_client
    app.state.roster = Roster(sheets_client)
    app.state.lid_resolver = LidResolver(Config.WHATSAPP_GROUP_JID)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        logger.exception("Failed to parse webhook JSON body")
        return {"status": "ok"}

    try:
        handle_task_payload(
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            request.app.state.sheets_client,
            Config.WHATSAPP_GROUP_JID,
        )
    except Exception:
        logger.exception("Failed to process task webhook payload")

    try:
        handle_spelling_payload(
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            Config.WHATSAPP_GROUP_JID,
        )
    except Exception:
        logger.exception("Failed to process spelling webhook payload")

    return {"status": "ok"}
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS (all tests across every file — 0 failures)

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Wire spelling handler into the webhook route alongside the task handler"
```

---

## Task 5: README — document the new setup step

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

Replace the current contents of `README.md` with:

```markdown
# bot-tareas-whatsapp

Bot de WhatsApp con dos funciones:
1. Vigila un grupo, detecta cuándo alguien agenda una tarea (mencionando a alguien con `@`), y la
   registra en un Google Sheet con responsable, fecha límite y estado. Ver
   `docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md`.
2. Cuando alguien del equipo manda una imagen con la palabra "ortografía" en el texto, revisa la
   ortografía en español de la imagen con OpenAI y responde en el grupo. Ver
   `docs/superpowers/specs/2026-08-05-image-spelling-review-design.md`.

## Setup

1. `pip install -r requirements.txt`
2. Copiar `.env.example` a `.env` y completar las credenciales (Evolution API, Google Sheets,
   OpenAI).
3. Colocar el JSON de la service account de Google en la ruta indicada por
   `GOOGLE_CREDENTIALS_PATH` (por defecto `secrets/google-service-account.json`).
4. Crear el Google Sheet con dos pestañas:
   - **Equipo**: columnas `Nombre | Numero` (número sin `+` ni espacios, ej. `573001112233`).
   - **Tareas**: se llena automáticamente; columnas
     `Fecha creación | Reportado por | Tarea | Asignado a | Fecha límite | Estado`.
5. Configurar el webhook de Evolution API para que apunte a `POST /webhook` de este servicio, con
   el evento `MESSAGES_UPSERT` activado.
6. Activar **"Webhook Base64"** en esa misma configuración del webhook -- sin esto, la revisión de
   ortografía en imágenes no puede funcionar, porque el contenido de la imagen no llega en el
   payload.

## Correr localmente

```bash
uvicorn main:app --reload --port 8000
```

## Tests

```bash
pytest -v
```
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document image spelling review setup in README"
```

---

## Post-plan note

The exact field name Evolution API uses for base64 image content in the webhook payload
(`data.base64`, assumed in Task 1) was not verified against a live payload -- unlike the text
message shapes, which were confirmed against real production logs during Phase 1 debugging. Once
this is deployed and "Webhook Base64" is enabled, send one test image with the keyword and check
the app logs: if `parse_image_messages` never returns a message despite the base64 setting being
on, the "Ignoring image message with no base64 content" log line (with the raw item dump) will
show exactly where the real field lives, and `_parse_image_item` in `services/evolution.py` can be
adjusted accordingly -- the same debugging approach used successfully for the mention-extraction
bug in Phase 1.
