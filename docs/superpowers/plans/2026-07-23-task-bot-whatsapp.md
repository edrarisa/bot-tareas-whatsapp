# Bot de Tareas por WhatsApp Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a FastAPI service that receives WhatsApp group messages via Evolution API webhooks, detects task-assignment messages from known team members using an LLM classifier, resolves the assignee via a real WhatsApp @mention, and logs the task to a Google Sheet.

**Architecture:** A single always-on FastAPI process exposes `POST /webhook`. Each incoming message is parsed, filtered (correct group + sender known in the "Equipo" roster), classified by OpenAI (task or not, description, due date), resolved to an assignee via mentioned JIDs, and appended as a row in the "Tareas" sheet. Google Sheets access and the roster lookup go through thin, dependency-injected wrapper classes so all logic is unit-testable without live network calls.

**Tech Stack:** Python 3.13, FastAPI + uvicorn, `openai` SDK (GPT-4o mini), `gspread` (Google Sheets), `requests` (Evolution API), `python-dotenv`, `pytest` + `pytest-mock`-free hand-written fakes.

**Spec:** `docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md`

---

## File Structure

```
bot-tareas-whatsapp/
├── requirements.txt
├── .env.example
├── .gitignore                  (already exists, will be extended)
├── config.py                   Config class, env vars, validate()
├── main.py                     FastAPI app, /webhook route
├── services/
│   ├── __init__.py
│   ├── evolution.py            IncomingMessage, parse_webhook_payload, send_text_message
│   ├── classifier.py           ClassificationResult, ClassifierError, classify_message
│   ├── sheets_client.py        SheetsClient, create_sheets_client
│   └── roster.py                Roster
├── handlers/
│   ├── __init__.py
│   └── task_handler.py         handle_webhook_payload (orchestration)
└── tests/
    ├── test_config.py
    ├── test_evolution.py
    ├── test_classifier.py
    ├── test_sheets_client.py
    ├── test_roster.py
    ├── test_task_handler.py
    └── test_main.py
```

`tests/` has no `__init__.py` so pytest inserts the repo root onto `sys.path`, making `services.*`, `handlers.*`, and `config`/`main` importable — same layout the archived project used.

---

## Task 1: Project scaffolding — dependencies, env template, config

**Files:**
- Create: `requirements.txt`
- Create: `.env.example`
- Modify: `.gitignore`
- Create: `config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write `requirements.txt`**

```
fastapi==0.115.6
uvicorn[standard]==0.34.0
requests==2.31.0
python-dotenv==1.0.0
openai==1.82.0
gspread==6.1.4
pytest==8.3.4
httpx==0.28.1
```

(`httpx` is required by FastAPI's `TestClient`.)

- [ ] **Step 2: Write `.env.example`**

```
# Evolution API (WhatsApp)
EVOLUTION_API_URL=
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=
WHATSAPP_GROUP_JID=

# Google Sheets
GOOGLE_SHEETS_ID=
GOOGLE_CREDENTIALS_PATH=secrets/google-service-account.json

# OpenAI
OPENAI_API_KEY=

# Logging
LOG_LEVEL=INFO
```

- [ ] **Step 3: Extend `.gitignore`**

Read the existing `.gitignore` first (it currently just has `# bot-tareas-whatsapp` boilerplate from GitHub's default), then add:

```
.env
__pycache__/
*.pyc
.venv/
secrets/
```

- [ ] **Step 4: Write the failing test for `config.py`**

```python
# tests/test_config.py
import pytest

from config import Config

REQUIRED_ATTRS = [
    "EVOLUTION_API_URL",
    "EVOLUTION_API_KEY",
    "EVOLUTION_INSTANCE",
    "WHATSAPP_GROUP_JID",
    "GOOGLE_SHEETS_ID",
    "OPENAI_API_KEY",
]


def _set_all(monkeypatch, except_attr=None):
    for attr in REQUIRED_ATTRS:
        monkeypatch.setattr(Config, attr, "" if attr == except_attr else "x")


def test_validate_raises_when_a_required_var_is_missing(monkeypatch):
    _set_all(monkeypatch, except_attr="EVOLUTION_API_URL")
    with pytest.raises(ValueError, match="EVOLUTION_API_URL"):
        Config.validate()


def test_validate_passes_when_all_required_vars_present(monkeypatch):
    _set_all(monkeypatch)
    Config.validate()
```

- [ ] **Step 5: Run the test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'config'`

- [ ] **Step 6: Write `config.py`**

```python
"""
Centralizes all configuration loaded from environment variables.
"""
import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    # -- Evolution API (WhatsApp) --
    EVOLUTION_API_URL: str = os.getenv("EVOLUTION_API_URL", "")
    EVOLUTION_API_KEY: str = os.getenv("EVOLUTION_API_KEY", "")
    EVOLUTION_INSTANCE: str = os.getenv("EVOLUTION_INSTANCE", "")
    WHATSAPP_GROUP_JID: str = os.getenv("WHATSAPP_GROUP_JID", "")

    # -- Google Sheets --
    GOOGLE_SHEETS_ID: str = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_CREDENTIALS_PATH: str = os.getenv(
        "GOOGLE_CREDENTIALS_PATH", "secrets/google-service-account.json"
    )

    # -- OpenAI --
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # -- Logging --
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    @classmethod
    def validate(cls) -> None:
        """Raises ValueError if any required credential/setting is missing."""
        required = {
            "EVOLUTION_API_URL": cls.EVOLUTION_API_URL,
            "EVOLUTION_API_KEY": cls.EVOLUTION_API_KEY,
            "EVOLUTION_INSTANCE": cls.EVOLUTION_INSTANCE,
            "WHATSAPP_GROUP_JID": cls.WHATSAPP_GROUP_JID,
            "GOOGLE_SHEETS_ID": cls.GOOGLE_SHEETS_ID,
            "OPENAI_API_KEY": cls.OPENAI_API_KEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
```

- [ ] **Step 7: Run the test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 8: Install dependencies**

Run: `pip install -r requirements.txt`

- [ ] **Step 9: Commit**

```bash
git add requirements.txt .env.example .gitignore config.py tests/test_config.py
git commit -m "Add project scaffolding and config module"
```

---

## Task 2: Evolution API — parsing incoming webhook payloads

**Files:**
- Create: `services/__init__.py`
- Create: `services/evolution.py`
- Test: `tests/test_evolution.py`

- [ ] **Step 1: Write `services/__init__.py`** (empty file, makes `services` a package)

- [ ] **Step 2: Write the failing tests for payload parsing**

```python
# tests/test_evolution.py
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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_evolution.py -v`
Expected: FAIL with `ImportError: cannot import name 'parse_webhook_payload'`

- [ ] **Step 4: Write `services/evolution.py` parsing logic**

```python
"""
Evolution API integration: parses incoming webhook payloads and sends
outgoing messages back to the group.
"""
import logging
from dataclasses import dataclass

import requests

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    group_jid: str
    sender_jid: str
    text: str
    mentioned_jids: list[str]
    from_me: bool


def parse_webhook_payload(payload: dict) -> IncomingMessage | None:
    """Returns None when the payload isn't a parseable text message."""
    data = payload.get("data")
    if not data:
        return None

    key = data.get("key", {})
    group_jid = key.get("remoteJid")
    if not group_jid:
        return None

    sender_jid = key.get("participant") or group_jid
    from_me = bool(key.get("fromMe", False))

    message = data.get("message", {})
    text = message.get("conversation")
    mentioned_jids: list[str] = []
    if text is None:
        extended = message.get("extendedTextMessage", {})
        text = extended.get("text")
        mentioned_jids = extended.get("contextInfo", {}).get("mentionedJid") or []

    if not text:
        return None

    return IncomingMessage(
        group_jid=group_jid,
        sender_jid=sender_jid,
        text=text,
        mentioned_jids=mentioned_jids,
        from_me=from_me,
    )
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_evolution.py -v`
Expected: PASS (6 tests)

- [ ] **Step 6: Commit**

```bash
git add services/__init__.py services/evolution.py tests/test_evolution.py
git commit -m "Add Evolution API webhook payload parsing"
```

---

## Task 3: Evolution API — sending messages back to the group

**Files:**
- Modify: `services/evolution.py`
- Modify: `tests/test_evolution.py`

- [ ] **Step 1: Write the failing test for `send_text_message`**

Add these imports to the top of `tests/test_evolution.py` (alongside the existing
`from services.evolution import parse_webhook_payload`):

```python
import pytest
import requests

from services.evolution import send_text_message
from config import Config
```

Then append to the bottom of the file:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_evolution.py -v`
Expected: FAIL with `ImportError: cannot import name 'send_text_message'`

- [ ] **Step 3: Add `send_text_message` to `services/evolution.py`**

Append to `services/evolution.py`:

```python
def send_text_message(group_jid: str, text: str) -> None:
    """Sends a text message to a group JID via Evolution API."""
    url = f"{Config.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{Config.EVOLUTION_INSTANCE}"
    headers = {"apikey": Config.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"number": group_jid, "text": text}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if not response.ok:
        logger.error(f"Evolution API error: {response.status_code} — {response.text}")
        response.raise_for_status()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_evolution.py -v`
Expected: PASS (8 tests)

- [ ] **Step 5: Commit**

```bash
git add services/evolution.py tests/test_evolution.py
git commit -m "Add Evolution API send_text_message"
```

---

## Task 4: LLM classifier — is this a task, what is it, when is it due

**Files:**
- Create: `services/classifier.py`
- Test: `tests/test_classifier.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_classifier.py
import json

import pytest

from services.classifier import ClassificationResult, ClassifierError, classify_message


class FakeCompletions:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise_exc = raise_exc

    def create(self, **kwargs):
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


def test_classifies_a_task_with_due_date():
    content = json.dumps(
        {"es_tarea": True, "descripcion": "Revisar el stand", "fecha_limite": "2026-07-24"}
    )
    client = FakeClient(content=content)

    result = classify_message("Cristian revisa el stand mañana", "2026-07-23", client=client)

    assert result == ClassificationResult(
        es_tarea=True, descripcion="Revisar el stand", fecha_limite="2026-07-24"
    )


def test_classifies_a_non_task():
    content = json.dumps({"es_tarea": False, "descripcion": None, "fecha_limite": None})
    client = FakeClient(content=content)

    result = classify_message("jajaja buenísimo", "2026-07-23", client=client)

    assert result.es_tarea is False


def test_raises_classifier_error_on_invalid_json():
    client = FakeClient(content="not json")

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_on_missing_key():
    client = FakeClient(content=json.dumps({"descripcion": "x"}))

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_api_call_fails():
    client = FakeClient(raise_exc=RuntimeError("timeout"))

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_classifier.py -v`
Expected: FAIL with `ImportError: cannot import name 'ClassificationResult'`

- [ ] **Step 3: Write `services/classifier.py`**

```python
"""
Classifies WhatsApp messages as tasks (or not) using OpenAI, extracting a
short description and, if mentioned, a due date resolved to YYYY-MM-DD.
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


class ClassifierError(Exception):
    pass


@dataclass
class ClassificationResult:
    es_tarea: bool
    descripcion: str | None
    fecha_limite: str | None


SYSTEM_PROMPT = """Eres un asistente que analiza mensajes de un grupo de WhatsApp de trabajo para \
detectar si agendan una tarea para alguien.

Hoy es {current_date}.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "es_tarea": true si el mensaje le pide a alguien hacer algo concreto, false si no.
- "descripcion": resumen corto en español de qué hay que hacer. null si es_tarea es false.
- "fecha_limite": fecha límite en formato YYYY-MM-DD si el mensaje menciona una (ej. "mañana", \
"el viernes"), resuelta contra la fecha de hoy. null si no se menciona ninguna fecha o si \
es_tarea es false."""


def classify_message(
    text: str, current_date: str, client: OpenAI | None = None
) -> ClassificationResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(current_date=current_date)},
                {"role": "user", "content": text},
            ],
        )
        data = json.loads(response.choices[0].message.content)
        return ClassificationResult(
            es_tarea=bool(data["es_tarea"]),
            descripcion=data["descripcion"],
            fecha_limite=data["fecha_limite"],
        )
    except Exception as exc:
        logger.warning(f"Classifier failed: {exc}")
        raise ClassifierError(str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_classifier.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/classifier.py tests/test_classifier.py
git commit -m "Add OpenAI-based task classifier"
```

---

## Task 5: Google Sheets client — read roster, append tasks

**Files:**
- Create: `services/sheets_client.py`
- Test: `tests/test_sheets_client.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_sheets_client.py
from services.sheets_client import SheetsClient


class FakeWorksheet:
    def __init__(self, values=None):
        self._values = values or []
        self.appended_rows: list[list] = []

    def get_all_values(self):
        return self._values

    def append_row(self, row):
        self.appended_rows.append(row)


class FakeSpreadsheet:
    def __init__(self, worksheets: dict[str, FakeWorksheet]):
        self._worksheets = worksheets

    def worksheet(self, name):
        return self._worksheets[name]


def test_read_team_roster_skips_header_and_empty_rows():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero"],
            ["Cristian", "573001112233"],
            ["Ana", "573004445566"],
            [""],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [("Cristian", "573001112233"), ("Ana", "573004445566")]


def test_append_task_writes_expected_row():
    tareas = FakeWorksheet()
    client = SheetsClient(FakeSpreadsheet({"Tareas": tareas}))

    client.append_task(
        created_at="2026-07-23",
        reporter="Ana",
        description="Revisar el stand",
        assignee="Cristian",
        due_date="2026-07-24",
        status="Pendiente",
    )

    assert tareas.appended_rows == [
        ["2026-07-23", "Ana", "Revisar el stand", "Cristian", "2026-07-24", "Pendiente"]
    ]


def test_append_task_writes_empty_string_when_no_due_date():
    tareas = FakeWorksheet()
    client = SheetsClient(FakeSpreadsheet({"Tareas": tareas}))

    client.append_task(
        created_at="2026-07-23",
        reporter="Ana",
        description="Revisar el stand",
        assignee="Sin asignar",
        due_date=None,
        status="Pendiente",
    )

    assert tareas.appended_rows[0][4] == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_client.py -v`
Expected: FAIL with `ImportError: cannot import name 'SheetsClient'`

- [ ] **Step 3: Write `services/sheets_client.py`**

```python
"""
Thin wrapper over gspread: reads the "Equipo" roster tab and appends rows
to the "Tareas" tab. Takes an already-open spreadsheet object so it can be
unit-tested without a live Google Sheets connection.
"""


class SheetsClient:
    def __init__(self, spreadsheet):
        self._spreadsheet = spreadsheet

    def read_team_roster(self) -> list[tuple[str, str]]:
        worksheet = self._spreadsheet.worksheet("Equipo")
        rows = worksheet.get_all_values()[1:]
        return [(row[0], row[1]) for row in rows if len(row) >= 2 and row[0]]

    def append_task(
        self,
        created_at: str,
        reporter: str,
        description: str,
        assignee: str,
        due_date: str | None,
        status: str,
    ) -> None:
        worksheet = self._spreadsheet.worksheet("Tareas")
        worksheet.append_row([created_at, reporter, description, assignee, due_date or "", status])


def create_sheets_client(sheet_id: str, credentials_path: str) -> SheetsClient:
    """Opens a live Google Sheets connection. Not covered by unit tests —
    requires real service-account credentials."""
    import gspread

    gc = gspread.service_account(filename=credentials_path)
    spreadsheet = gc.open_by_key(sheet_id)
    return SheetsClient(spreadsheet)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_client.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add services/sheets_client.py tests/test_sheets_client.py
git commit -m "Add Google Sheets client wrapper"
```

---

## Task 6: Roster — resolve JIDs against the "Equipo" tab, with caching

**Files:**
- Create: `services/roster.py`
- Test: `tests/test_roster.py`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_roster.py
from services.roster import Roster


class FakeSheetsClient:
    def __init__(self, rows):
        self._rows = rows
        self.read_calls = 0

    def read_team_roster(self):
        self.read_calls += 1
        return self._rows


def test_is_known_sender_true_for_roster_member():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573001112233@s.whatsapp.net") is True


def test_is_known_sender_false_for_unknown_number():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573009998877@s.whatsapp.net") is False


def test_resolve_name_returns_name_for_known_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_resolve_name_returns_none_for_unknown_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573009998877@s.whatsapp.net") is None


def test_normalizes_non_digit_characters_in_stored_numbers():
    sheets_client = FakeSheetsClient([("Cristian", "+57 300 111 2233")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_caches_roster_within_ttl():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    clock = {"now": 1000.0}
    roster = Roster(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    roster.is_known_sender("573001112233@s.whatsapp.net")
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_roster.py -v`
Expected: FAIL with `ImportError: cannot import name 'Roster'`

- [ ] **Step 3: Write `services/roster.py`**

```python
"""
Resolves WhatsApp JIDs against the "Equipo" roster tab, caching the roster
in memory for a short TTL to avoid hitting the Sheets API on every message.
"""
import time


class Roster:
    def __init__(self, sheets_client, ttl_seconds: int = 300, time_func=time.monotonic):
        self._sheets_client = sheets_client
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._by_phone: dict[str, str] = {}
        self._loaded_at: float = float("-inf")

    def _ensure_loaded(self) -> None:
        now = self._time_func()
        if self._loaded_at != float("-inf") and now - self._loaded_at <= self._ttl_seconds:
            return
        rows = self._sheets_client.read_team_roster()
        self._by_phone = {self._normalize(number): name for name, number in rows}
        self._loaded_at = now

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(ch for ch in value if ch.isdigit())

    @staticmethod
    def _phone_from_jid(jid: str) -> str:
        return jid.split("@", 1)[0]

    def is_known_sender(self, jid: str) -> bool:
        self._ensure_loaded()
        return self._normalize(self._phone_from_jid(jid)) in self._by_phone

    def resolve_name(self, jid: str) -> str | None:
        self._ensure_loaded()
        return self._by_phone.get(self._normalize(self._phone_from_jid(jid)))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_roster.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/roster.py tests/test_roster.py
git commit -m "Add roster resolution with TTL caching"
```

---

## Task 7: Task handler — orchestrates parse, filter, classify, assign, save

**Files:**
- Create: `handlers/__init__.py`
- Create: `handlers/task_handler.py`
- Test: `tests/test_task_handler.py`

- [ ] **Step 1: Write `handlers/__init__.py`** (empty file)

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_task_handler.py
from services.classifier import ClassificationResult, ClassifierError
from handlers.task_handler import handle_webhook_payload

GROUP_JID = "120363429440515454@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"
SENDER_JID = "573001112233@s.whatsapp.net"
ASSIGNEE_JID = "573004445566@s.whatsapp.net"


class FakeRoster:
    def __init__(self, known_jids: dict[str, str]):
        self._known = known_jids

    def is_known_sender(self, jid):
        return jid in self._known

    def resolve_name(self, jid):
        return self._known.get(jid)


class FakeSheetsClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.appended = []

    def append_task(self, **kwargs):
        if self.fail:
            raise RuntimeError("sheets down")
        self.appended.append(kwargs)


def _payload(text, sender_jid=SENDER_JID, mentioned_jids=None, group_jid=GROUP_JID, from_me=False):
    return {
        "data": {
            "key": {"remoteJid": group_jid, "participant": sender_jid, "fromMe": from_me},
            "message": {
                "extendedTextMessage": {
                    "text": text,
                    "contextInfo": {"mentionedJid": mentioned_jids or []},
                }
            }
            if mentioned_jids
            else {"conversation": text},
        }
    }


def test_ignores_message_from_unknown_sender(monkeypatch):
    roster = FakeRoster({})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: (_ for _ in ()).throw(AssertionError("should not classify")),
    )

    handle_webhook_payload(_payload("Cristian revisa el stand"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended == []


def test_ignores_message_from_other_group(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()

    handle_webhook_payload(
        _payload("Cristian revisa el stand", group_jid=OTHER_GROUP_JID),
        roster,
        sheets_client,
        GROUP_JID,
    )

    assert sheets_client.appended == []


def test_ignores_own_messages(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()

    handle_webhook_payload(
        _payload("aviso de error", from_me=True), roster, sheets_client, GROUP_JID
    )

    assert sheets_client.appended == []


def test_ignores_non_task_message(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=False, descripcion=None, fecha_limite=None
        ),
    )

    handle_webhook_payload(_payload("jajaja buenísimo"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended == []


def test_saves_task_with_assignee_from_mention(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite="2026-07-24"
        ),
    )

    handle_webhook_payload(
        _payload("revisa el stand mañana @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        sheets_client,
        GROUP_JID,
    )

    assert len(sheets_client.appended) == 1
    saved = sheets_client.appended[0]
    assert saved["reporter"] == "Ana"
    assert saved["description"] == "Revisar el stand"
    assert saved["assignee"] == "Cristian"
    assert saved["due_date"] == "2026-07-24"
    assert saved["status"] == "Pendiente"


def test_saves_task_as_unassigned_when_no_mention(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )

    handle_webhook_payload(_payload("hay que revisar el stand"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended[0]["assignee"] == "Sin asignar"


def test_ignores_classifier_errors_without_saving(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()

    def raise_error(text, date, **kw):
        raise ClassifierError("timeout")

    monkeypatch.setattr("handlers.task_handler.classify_message", raise_error)

    handle_webhook_payload(_payload("algo"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended == []


def test_sends_warning_when_sheets_write_fails(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient(fail=True)
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.task_handler.send_text_message", lambda group_jid, text: sent.append(text)
    )

    handle_webhook_payload(_payload("hay que revisar el stand"), roster, sheets_client, GROUP_JID)

    assert len(sent) == 1
    assert "no pude guardar" in sent[0].lower()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_task_handler.py -v`
Expected: FAIL with `ImportError: cannot import name 'handle_webhook_payload'`

- [ ] **Step 4: Write `handlers/task_handler.py`**

```python
"""
Orchestrates a single incoming webhook message: parse -> filter -> classify
-> resolve assignee -> save to Sheets (or warn the group on save failure).
"""
import logging
from datetime import date

from services.classifier import ClassifierError, classify_message
from services.evolution import parse_webhook_payload, send_text_message

logger = logging.getLogger(__name__)


def handle_webhook_payload(payload: dict, roster, sheets_client, group_jid: str) -> None:
    message = parse_webhook_payload(payload)
    if message is None or message.from_me or message.group_jid != group_jid:
        return

    if not roster.is_known_sender(message.sender_jid):
        return

    try:
        result = classify_message(message.text, date.today().isoformat())
    except ClassifierError:
        logger.exception("Classifier failed for message from %s", message.sender_jid)
        return

    if not result.es_tarea:
        return

    assignee = "Sin asignar"
    for jid in message.mentioned_jids:
        if jid == message.sender_jid:
            continue
        name = roster.resolve_name(jid)
        if name:
            assignee = name
            break

    reporter_name = roster.resolve_name(message.sender_jid) or message.sender_jid

    try:
        sheets_client.append_task(
            created_at=date.today().isoformat(),
            reporter=reporter_name,
            description=result.descripcion,
            assignee=assignee,
            due_date=result.fecha_limite,
            status="Pendiente",
        )
    except Exception:
        logger.exception("Failed to save task to Sheets")
        send_text_message(group_jid, "⚠️ No pude guardar esta tarea, avísenle a alguien.")
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_task_handler.py -v`
Expected: PASS (8 tests)

- [ ] **Step 6: Commit**

```bash
git add handlers/__init__.py handlers/task_handler.py tests/test_task_handler.py
git commit -m "Add task handler orchestration"
```

---

## Task 8: FastAPI app — the /webhook endpoint

**Files:**
- Create: `main.py`
- Test: `tests/test_main.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_main.py
from fastapi.testclient import TestClient

import main


def test_webhook_delegates_to_task_handler(monkeypatch):
    received = []

    def fake_handler(payload, roster, sheets_client, group_jid):
        received.append((payload, roster, sheets_client, group_jid))

    monkeypatch.setattr(main, "handle_webhook_payload", fake_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert len(received) == 1
    assert received[0][0] == body
    assert received[0][1] == "fake-roster"
    assert received[0][2] == "fake-sheets-client"
    assert received[0][3] == "120363429440515454@g.us"
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `pytest tests/test_main.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'main'`

- [ ] **Step 3: Write `main.py`**

```python
"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler. Google Sheets / roster clients are created lazily on startup
so importing this module has no side effects (needed for testing).
"""
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request

from config import Config
from handlers.task_handler import handle_webhook_payload
from services.roster import Roster
from services.sheets_client import create_sheets_client


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.validate()
    sheets_client = create_sheets_client(Config.GOOGLE_SHEETS_ID, Config.GOOGLE_CREDENTIALS_PATH)
    app.state.sheets_client = sheets_client
    app.state.roster = Roster(sheets_client)
    yield


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    payload = await request.json()
    handle_webhook_payload(
        payload,
        request.app.state.roster,
        request.app.state.sheets_client,
        Config.WHATSAPP_GROUP_JID,
    )
    return {"status": "ok"}
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `pytest tests/test_main.py -v`
Expected: PASS (1 test). The `lifespan` function is not invoked because `TestClient(main.app)` is used without a `with` block, so no real Google/Evolution credentials are needed for this test.

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS (33 tests across every file)

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Add FastAPI webhook endpoint"
```

---

## Task 9: README — setup and run instructions

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Replace the placeholder README**

The current `README.md` only has the GitHub-generated `# bot-tareas-whatsapp` line. Replace its contents with:

```markdown
# bot-tareas-whatsapp

Bot de WhatsApp que vigila un grupo, detecta cuándo alguien agenda una tarea, y la registra en un
Google Sheet con responsable, fecha límite y estado. Ver el diseño completo en
`docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md`.

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
5. Configurar el webhook de Evolution API para que apunte a `POST /webhook` de este servicio.

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
git commit -m "Document setup and run instructions"
```

---

## Post-plan note

Deployment to the Coolify VPS (new Evolution API instance, environment variables, service
creation) is an infrastructure step outside this repo's code and isn't broken into TDD tasks here
— do it manually following the README once this plan is fully implemented and pushed.
