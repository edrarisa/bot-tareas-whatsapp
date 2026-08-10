# Recordatorios de Tareas Urgentes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically detect urgent tasks at creation time and remind the assignee on their personal WhatsApp number at noon and 5pm on weekdays until the task is marked "Completada", without ever losing or duplicating an alert even if the bot restarts.

**Architecture:** The classifier gains an `es_urgente` field decided once at task creation. `PersonalTaskWriter` gains three columns (`Urgente`, `Alerta 12pm`, `Alerta 5pm`). A new `ReminderScanner` reads every team member's personal Sheet every 15 minutes (via a background `asyncio` loop wired into `main.py`, dispatched to a thread pool so it never blocks the webhook route) and sends a reminder for any row that's urgent, incomplete, past the 2-hour grace period, and not yet alerted for the current window -- writing the send date back into the Sheet only after a successful send, so the Sheet itself is the durable "already sent" record.

**Tech Stack:** Same as the rest of the bot -- Python 3.13, FastAPI, `gspread`, `openai`, `asyncio` (standard library, no new dependency).

**Spec:** `docs/superpowers/specs/2026-08-10-urgent-task-reminders-design.md`

---

## File Structure

```
bot-tareas-whatsapp/
├── main.py                          MODIFY: launch/cancel the reminder background loop
├── README.md                        MODIFY: document the new columns
├── services/
│   ├── classifier.py                 MODIFY: add es_urgente field + prompt rule
│   ├── sheets_client.py              MODIFY: PersonalTaskWriter gains Urgente/Alerta columns
│   ├── reminder_scanner.py           CREATE: ReminderScanner.run_check() + factory
│   └── reminder_scheduler.py         CREATE: run_reminder_loop()
├── handlers/
│   └── task_handler.py               MODIFY: pass is_urgent=result.es_urgente
└── tests/
    ├── test_classifier.py            REWRITE: es_urgente tests
    ├── test_sheets_client.py         REWRITE: new columns tests
    ├── test_task_handler.py          MODIFY: is_urgent pass-through
    ├── test_reminder_scanner.py      CREATE
    └── test_reminder_scheduler.py    CREATE
```

---

## Task 1: classifier.py — es_urgente field

**Files:**
- Modify: `services/classifier.py`
- Test: `tests/test_classifier.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_classifier.py` with:

```python
import json

import pytest

from services.classifier import ClassificationResult, ClassifierError, classify_message


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


def test_classifies_a_task_with_due_date():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Revisar el stand",
            "fecha_limite": "2026-07-24",
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    result = classify_message("Cristian revisa el stand mañana", "2026-07-23", client=client)

    assert result == ClassificationResult(
        es_tarea=True,
        descripcion="Revisar el stand",
        fecha_limite="2026-07-24",
        hora_limite=None,
        es_urgente=False,
    )


def test_classifies_a_task_with_due_date_and_time():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Revisar el código de Bancamía",
            "fecha_limite": "2026-08-10",
            "hora_limite": "18:00",
            "es_urgente": True,
        }
    )
    client = FakeClient(content=content)

    result = classify_message(
        "revisa el código de bancamía antes de las 6 pm", "2026-08-10", client=client
    )

    assert result == ClassificationResult(
        es_tarea=True,
        descripcion="Revisar el código de Bancamía",
        fecha_limite="2026-08-10",
        hora_limite="18:00",
        es_urgente=True,
    )


def test_classifies_an_urgent_task_via_explicit_language():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Enviar el informe",
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": True,
        }
    )
    client = FakeClient(content=content)

    result = classify_message("urgente, envía el informe ya", "2026-07-23", client=client)

    assert result.es_urgente is True


def test_classifies_a_non_urgent_task():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Revisar el stand",
            "fecha_limite": "2026-07-30",
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    result = classify_message("revisa el stand la próxima semana", "2026-07-23", client=client)

    assert result.es_urgente is False


def test_classifies_a_non_task():
    content = json.dumps(
        {
            "es_tarea": False,
            "descripcion": None,
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": False,
        }
    )
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


def test_sends_expected_request_to_openai():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Test task",
            "fecha_limite": "2026-07-24",
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    classify_message("Some message", "2026-07-23", client=client)

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["model"] == "gpt-5.6-terra"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["timeout"] == 30
    system_message_content = kwargs["messages"][0]["content"]
    assert "2026-07-23" in system_message_content


def test_raises_classifier_error_when_es_tarea_is_not_a_bool():
    content = json.dumps(
        {
            "es_tarea": "false",
            "descripcion": None,
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_descripcion_is_not_a_string():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": 123,
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_fecha_limite_is_not_a_string():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Task",
            "fecha_limite": ["2026-07-24"],
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_hora_limite_is_not_a_string():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Task",
            "fecha_limite": None,
            "hora_limite": 1800,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_hora_limite_key_missing():
    content = json.dumps({"es_tarea": True, "descripcion": "Task", "fecha_limite": None})
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_es_urgente_is_not_a_bool():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "Task",
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": "yes",
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_es_urgente_key_missing():
    content = json.dumps(
        {"es_tarea": True, "descripcion": "Task", "fecha_limite": None, "hora_limite": None}
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_es_tarea_true_but_descripcion_empty():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": "",
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_es_tarea_true_but_descripcion_null():
    content = json.dumps(
        {
            "es_tarea": True,
            "descripcion": None,
            "fecha_limite": None,
            "hora_limite": None,
            "es_urgente": False,
        }
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_classifier.py -v`
Expected: FAIL -- `ClassificationResult` has no `es_urgente` field yet, and the real code never reads/validates `data["es_urgente"]`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `services/classifier.py` with:

```python
"""
Classifies WhatsApp messages as tasks (or not) using OpenAI, extracting a
short description, a due date (YYYY-MM-DD), a due time (24h HH:MM), and
whether the task is urgent.
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
    hora_limite: str | None = None
    es_urgente: bool = False


SYSTEM_PROMPT = """Eres un asistente que analiza mensajes de un grupo de WhatsApp de trabajo para \
detectar si agendan una tarea para alguien.

Hoy es {current_date}.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "es_tarea": true si el mensaje le pide a alguien hacer algo concreto, false si no.
- "descripcion": resumen corto en español de qué hay que hacer. null si es_tarea es false.
- "fecha_limite": fecha límite en formato YYYY-MM-DD si el mensaje menciona una (ej. "mañana", \
"el viernes"), resuelta contra la fecha de hoy. Si el mensaje menciona una hora límite pero NO \
menciona ningún día (ej. "antes de las 6 pm", sin decir "mañana" ni ningún otro día), asume que \
es para hoy y usa la fecha de hoy. null si no se menciona ninguna fecha ni hora, o si es_tarea \
es false.
- "hora_limite": hora límite en formato de 24 horas HH:MM si el mensaje indica una hora concreta \
para completar la tarea, sin importar cómo esté redactada -- la gente lo dice de muchas formas \
distintas, no solo con "antes de". Por ejemplo: "antes de las 6 pm" -> "18:00", "a las 3:30" -> \
"15:30", "para las 6" -> "18:00", "máximo a las 5" -> "17:00", "antes del mediodía" -> "12:00", \
"entregarlo a las 9 am" -> "09:00". null si no se menciona ninguna hora concreta, si la hora es \
vaga o relativa (ej. "en la tarde", "más tarde", "pronto"), o si es_tarea es false.
- "es_urgente": true si la tarea es urgente -- porque su fecha límite es HOY (el mismo día en que \
se crea la tarea), o porque el mensaje usa lenguaje explícito de urgencia (ej. "urgente", "ya", \
"necesito esto ahora", "es urgente"), lo que ocurra primero. false en cualquier otro caso, \
incluyendo si es_tarea es false."""


def classify_message(
    text: str, current_date: str, client: OpenAI | None = None
) -> ClassificationResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-5.6-terra",
            response_format={"type": "json_object"},
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(current_date=current_date)},
                {"role": "user", "content": text},
            ],
        )
        data = json.loads(response.choices[0].message.content)
        es_tarea = data["es_tarea"]
        descripcion = data["descripcion"]
        fecha_limite = data["fecha_limite"]
        hora_limite = data["hora_limite"]
        es_urgente = data["es_urgente"]
        if not isinstance(es_tarea, bool):
            raise ValueError(f"es_tarea must be a bool, got {type(es_tarea).__name__}")
        if descripcion is not None and not isinstance(descripcion, str):
            raise ValueError(f"descripcion must be a string or null, got {type(descripcion).__name__}")
        if fecha_limite is not None and not isinstance(fecha_limite, str):
            raise ValueError(f"fecha_limite must be a string or null, got {type(fecha_limite).__name__}")
        if hora_limite is not None and not isinstance(hora_limite, str):
            raise ValueError(f"hora_limite must be a string or null, got {type(hora_limite).__name__}")
        if not isinstance(es_urgente, bool):
            raise ValueError(f"es_urgente must be a bool, got {type(es_urgente).__name__}")
        if es_tarea and not descripcion:
            raise ValueError("es_tarea is true but descripcion is missing or empty")
        return ClassificationResult(
            es_tarea=es_tarea,
            descripcion=descripcion,
            fecha_limite=fecha_limite,
            hora_limite=hora_limite,
            es_urgente=es_urgente,
        )
    except Exception as exc:
        logger.warning(f"Classifier failed: {exc}")
        raise ClassifierError(str(exc)) from exc
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_classifier.py -v`
Expected: PASS (20 tests)

- [ ] **Step 5: Commit**

```bash
git add services/classifier.py tests/test_classifier.py
git commit -m "Add es_urgente field to the task classifier"
```

---

## Task 2: sheets_client.py — Urgente/Alerta columns

**Files:**
- Modify: `services/sheets_client.py`
- Test: `tests/test_sheets_client.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_sheets_client.py` with:

```python
from gspread.exceptions import WorksheetNotFound
from gspread.utils import ValidationConditionType

from services.sheets_client import PersonalTaskWriter, SheetsClient


class FakeWorksheet:
    def __init__(self, values=None, sheet_id=0):
        self._values = values or []
        self.appended_rows: list[list] = []
        self.id = sheet_id
        self.spreadsheet = None  # set by FakePersonalSpreadsheet.add_worksheet
        self.validation_calls: list[tuple] = []

    def get_all_values(self):
        return self._values

    def append_row(self, row):
        self.appended_rows.append(row)

    def add_validation(self, range, condition_type, values, showCustomUi=False, **kwargs):
        self.validation_calls.append((range, condition_type, list(values), showCustomUi))


class FakeSpreadsheet:
    def __init__(self, worksheets: dict[str, FakeWorksheet]):
        self._worksheets = worksheets

    def worksheet(self, name):
        return self._worksheets[name]


def test_read_team_roster_skips_header_and_empty_rows():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero", "Sheet ID"],
            ["Cristian", "573001112233", "sheet-cristian"],
            ["Ana", "573004445566", "sheet-ana"],
            [""],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [
        ("Cristian", "573001112233", "sheet-cristian"),
        ("Ana", "573004445566", "sheet-ana"),
    ]


def test_read_team_roster_skips_rows_with_blank_number():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero", "Sheet ID"],
            ["Cristian", "573001112233", "sheet-cristian"],
            ["Ana", "", "sheet-ana"],
            ["   ", "573004445566", "sheet-x"],
            ["Pablo", "   ", "sheet-pablo"],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [("Cristian", "573001112233", "sheet-cristian")]


def test_read_team_roster_tolerates_missing_sheet_id_column():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero"],
            ["Cristian", "573001112233"],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [("Cristian", "573001112233", "")]


def test_read_group_mapping_skips_header_and_empty_rows():
    grupos = FakeWorksheet(
        values=[
            ["Grupo", "Cliente", "Nombre del grupo"],
            ["120363429440515454@g.us", "clinicachia", "Clinica Chia"],
            ["120363999999999@g.us", "optifalcon", "Optifalcon"],
            [""],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Grupos": grupos}))

    mapping = client.read_group_mapping()

    assert mapping == [
        ("120363429440515454@g.us", "clinicachia"),
        ("120363999999999@g.us", "optifalcon"),
    ]


class FakePersonalSpreadsheet:
    def __init__(self):
        self._worksheets: dict[str, FakeWorksheet] = {}
        self.add_worksheet_calls = []
        self.batch_update_calls = []

    def worksheet(self, name):
        if name not in self._worksheets:
            raise WorksheetNotFound(name)
        return self._worksheets[name]

    def add_worksheet(self, title, rows, cols):
        self.add_worksheet_calls.append((title, rows, cols))
        worksheet = FakeWorksheet(sheet_id=len(self._worksheets) + 1)
        worksheet.spreadsheet = self
        self._worksheets[title] = worksheet
        return worksheet

    def batch_update(self, body):
        self.batch_update_calls.append(body)


class FakeGspreadClient:
    def __init__(self, spreadsheets: dict[str, FakePersonalSpreadsheet]):
        self._spreadsheets = spreadsheets

    def open_by_key(self, sheet_id):
        return self._spreadsheets[sheet_id]


def test_personal_task_writer_creates_client_tab_when_missing():
    spreadsheet = FakePersonalSpreadsheet()
    gspread_client = FakeGspreadClient({"sheet-cristian": spreadsheet})
    writer = PersonalTaskWriter(gspread_client)

    writer.append_task(
        sheet_id="sheet-cristian",
        client_tab="clinicachia",
        created_at="2026-08-06 10:00",
        reporter="Ana",
        description="Revisar el stand",
        due_date="2026-08-07",
        due_time="18:00",
        is_urgent=True,
        status="Pendiente",
    )

    assert spreadsheet.add_worksheet_calls == [("clinicachia", 100, 9)]
    worksheet = spreadsheet._worksheets["clinicachia"]
    assert worksheet.appended_rows == [
        [
            "Fecha",
            "Reportado por",
            "Descripción",
            "Fecha límite",
            "Hora",
            "Estado",
            "Urgente",
            "Alerta 12pm",
            "Alerta 5pm",
        ],
        [
            "2026-08-06 10:00",
            "Ana",
            "Revisar el stand",
            "2026-08-07",
            "18:00",
            "Pendiente",
            "Sí",
            "",
            "",
        ],
    ]


def test_personal_task_writer_writes_no_for_non_urgent_task():
    spreadsheet = FakePersonalSpreadsheet()
    gspread_client = FakeGspreadClient({"sheet-cristian": spreadsheet})
    writer = PersonalTaskWriter(gspread_client)

    writer.append_task(
        sheet_id="sheet-cristian",
        client_tab="clinicachia",
        created_at="2026-08-06 10:00",
        reporter="Ana",
        description="Revisar el stand",
        due_date=None,
        due_time=None,
        is_urgent=False,
        status="Pendiente",
    )

    worksheet = spreadsheet._worksheets["clinicachia"]
    assert worksheet.appended_rows[1][6] == "No"


def test_personal_task_writer_reuses_existing_client_tab():
    existing_tab = FakeWorksheet(
        values=[
            [
                "Fecha",
                "Reportado por",
                "Descripción",
                "Fecha límite",
                "Hora",
                "Estado",
                "Urgente",
                "Alerta 12pm",
                "Alerta 5pm",
            ]
        ]
    )
    spreadsheet = FakePersonalSpreadsheet()
    spreadsheet._worksheets["clinicachia"] = existing_tab
    gspread_client = FakeGspreadClient({"sheet-cristian": spreadsheet})
    writer = PersonalTaskWriter(gspread_client)

    writer.append_task(
        sheet_id="sheet-cristian",
        client_tab="clinicachia",
        created_at="2026-08-06 10:00",
        reporter="Ana",
        description="Revisar el stand",
        due_date=None,
        due_time=None,
        is_urgent=False,
        status="Pendiente",
    )

    assert spreadsheet.add_worksheet_calls == []
    assert existing_tab.appended_rows == [
        ["2026-08-06 10:00", "Ana", "Revisar el stand", "", "", "Pendiente", "No", "", ""]
    ]


def test_personal_task_writer_applies_status_dropdown_on_new_tab():
    spreadsheet = FakePersonalSpreadsheet()
    gspread_client = FakeGspreadClient({"sheet-cristian": spreadsheet})
    writer = PersonalTaskWriter(gspread_client)

    writer.append_task(
        sheet_id="sheet-cristian",
        client_tab="clinicachia",
        created_at="2026-08-06 10:00",
        reporter="Ana",
        description="Revisar el stand",
        due_date="2026-08-07",
        due_time="18:00",
        is_urgent=True,
        status="Pendiente",
    )

    worksheet = spreadsheet._worksheets["clinicachia"]
    assert len(worksheet.validation_calls) == 1
    range_, condition_type, values, show_custom_ui = worksheet.validation_calls[0]
    assert range_ == "F2:F100"
    assert condition_type == ValidationConditionType.one_of_list
    assert values == ["Pendiente", "En progreso", "Completada"]
    assert show_custom_ui is True

    assert len(spreadsheet.batch_update_calls) == 1
    requests = spreadsheet.batch_update_calls[0]["requests"]
    assert len(requests) == 3
    statuses = [
        req["addConditionalFormatRule"]["rule"]["booleanRule"]["condition"]["values"][0][
            "userEnteredValue"
        ]
        for req in requests
    ]
    assert statuses == ["Pendiente", "En progreso", "Completada"]
    for req in requests:
        rule = req["addConditionalFormatRule"]["rule"]
        assert rule["ranges"][0]["sheetId"] == worksheet.id
        color = rule["booleanRule"]["format"]["backgroundColor"]
        assert {"red", "green", "blue"} <= color.keys()


def test_personal_task_writer_does_not_reapply_dropdown_on_existing_tab():
    existing_tab = FakeWorksheet(
        values=[
            [
                "Fecha",
                "Reportado por",
                "Descripción",
                "Fecha límite",
                "Hora",
                "Estado",
                "Urgente",
                "Alerta 12pm",
                "Alerta 5pm",
            ]
        ]
    )
    spreadsheet = FakePersonalSpreadsheet()
    spreadsheet._worksheets["clinicachia"] = existing_tab
    gspread_client = FakeGspreadClient({"sheet-cristian": spreadsheet})
    writer = PersonalTaskWriter(gspread_client)

    writer.append_task(
        sheet_id="sheet-cristian",
        client_tab="clinicachia",
        created_at="2026-08-06 10:00",
        reporter="Ana",
        description="Revisar el stand",
        due_date=None,
        due_time=None,
        is_urgent=False,
        status="Pendiente",
    )

    assert existing_tab.validation_calls == []
    assert spreadsheet.batch_update_calls == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_client.py -v`
Expected: FAIL -- `append_task()` doesn't accept `is_urgent` yet, and `_HEADERS` only has 6 columns.

- [ ] **Step 3: Write the implementation**

In `services/sheets_client.py`, replace the `PersonalTaskWriter` class definition (from `class PersonalTaskWriter:` through the end of `append_task`, i.e. lines 47-80 in the current file) with:

```python
class PersonalTaskWriter:
    """Writes tasks to each team member's own Google Sheet, in a tab named
    after the client. Takes the raw gspread client (not a fixed
    spreadsheet) since it needs to open a different spreadsheet per
    assignee."""

    _HEADERS = [
        "Fecha",
        "Reportado por",
        "Descripción",
        "Fecha límite",
        "Hora",
        "Estado",
        "Urgente",
        "Alerta 12pm",
        "Alerta 5pm",
    ]

    def __init__(self, gspread_client):
        self._gspread_client = gspread_client

    def append_task(
        self,
        sheet_id: str,
        client_tab: str,
        created_at: str,
        reporter: str,
        description: str,
        due_date: str | None,
        due_time: str | None,
        is_urgent: bool,
        status: str,
    ) -> None:
        spreadsheet = self._gspread_client.open_by_key(sheet_id)
        try:
            worksheet = spreadsheet.worksheet(client_tab)
        except WorksheetNotFound:
            worksheet = spreadsheet.add_worksheet(
                title=client_tab, rows=100, cols=len(self._HEADERS)
            )
            worksheet.append_row(self._HEADERS)
            self._apply_status_dropdown(worksheet)
        worksheet.append_row(
            [
                created_at,
                reporter,
                description,
                due_date or "",
                due_time or "",
                status,
                "Sí" if is_urgent else "No",
                "",
                "",
            ]
        )
```

(The `_apply_status_dropdown` static method and everything below it in the file is unchanged -- do not touch it. `_STATUS_COLUMN_RANGE` stays `"F2:F100"` since "Estado" is still the 6th column; the three new columns are appended after it.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_client.py -v`
Expected: PASS (10 tests)

- [ ] **Step 5: Commit**

```bash
git add services/sheets_client.py tests/test_sheets_client.py
git commit -m "Add Urgente/Alerta 12pm/Alerta 5pm columns to PersonalTaskWriter"
```

---

## Task 3: task_handler.py — wire is_urgent through

**Files:**
- Modify: `handlers/task_handler.py:92-101` (the `personal_task_writer.append_task(...)` call)
- Test: `tests/test_task_handler.py`

- [ ] **Step 1: Write the failing test**

In `tests/test_task_handler.py`, add this new test at the end of the file (after `test_sends_warning_when_sheets_write_fails`):

```python
def test_passes_urgency_through_to_personal_task_writer(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True,
            descripcion="Enviar el informe",
            fecha_limite="2026-08-10",
            hora_limite=None,
            es_urgente=True,
        ),
    )

    handle_webhook_payload(
        _payload("urgente, envía el informe @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    assert task_writer.appended[0]["is_urgent"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_task_handler.py::test_passes_urgency_through_to_personal_task_writer -v`
Expected: FAIL with `KeyError: 'is_urgent'` -- `task_handler.py` doesn't pass this field yet.

- [ ] **Step 3: Write the implementation**

In `handlers/task_handler.py`, find this block (currently lines 92-101):

```python
    try:
        personal_task_writer.append_task(
            sheet_id=sheet_id,
            client_tab=client_name,
            created_at=now.strftime("%Y-%m-%d %H:%M"),
            reporter=reporter_name,
            description=result.descripcion,
            due_date=result.fecha_limite,
            due_time=result.hora_limite,
            status="Pendiente",
        )
```

Replace it with:

```python
    try:
        personal_task_writer.append_task(
            sheet_id=sheet_id,
            client_tab=client_name,
            created_at=now.strftime("%Y-%m-%d %H:%M"),
            reporter=reporter_name,
            description=result.descripcion,
            due_date=result.fecha_limite,
            due_time=result.hora_limite,
            is_urgent=result.es_urgente,
            status="Pendiente",
        )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_task_handler.py -v`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add handlers/task_handler.py tests/test_task_handler.py
git commit -m "Pass task urgency through to PersonalTaskWriter"
```

---

## Task 4: reminder_scanner.py — the reminder engine

**Files:**
- Create: `services/reminder_scanner.py`
- Test: `tests/test_reminder_scanner.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reminder_scanner.py`:

```python
from datetime import datetime
from zoneinfo import ZoneInfo

from services.reminder_scanner import ReminderScanner

TZ = ZoneInfo("America/Bogota")

_HEADERS = [
    "Fecha",
    "Reportado por",
    "Descripción",
    "Fecha límite",
    "Hora",
    "Estado",
    "Urgente",
    "Alerta 12pm",
    "Alerta 5pm",
]


class FakeSheetsClient:
    def __init__(self, members):
        self._members = members

    def read_team_roster(self):
        return self._members


class FakeWorksheet:
    def __init__(self, title, values):
        self.title = title
        self._values = values
        self.update_cell_calls: list[tuple] = []

    def get_all_values(self):
        return self._values

    def update_cell(self, row, col, value):
        self.update_cell_calls.append((row, col, value))


class FakeSpreadsheet:
    def __init__(self, worksheets):
        self._worksheets = worksheets

    def worksheets(self):
        return self._worksheets


class FakeGspreadClient:
    def __init__(self, spreadsheets):
        self._spreadsheets = spreadsheets

    def open_by_key(self, sheet_id):
        return self._spreadsheets[sheet_id]


def _row(fecha, estado="Pendiente", urgente="Sí", alerta_12pm="", alerta_5pm="", descripcion="Revisar algo"):
    return [fecha, "Ana", descripcion, "2026-08-10", "18:00", estado, urgente, alerta_12pm, alerta_5pm]


def test_skips_weekend():
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({})
    sent = []
    saturday_noon = datetime(2026, 8, 8, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client,
        gspread_client,
        lambda jid, text: sent.append((jid, text)),
        now_func=lambda: saturday_noon,
    )

    scanner.run_check()

    assert sent == []


def test_skips_before_noon():
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({})
    sent = []
    monday_morning = datetime(2026, 8, 10, 9, 0, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client,
        gspread_client,
        lambda jid, text: sent.append((jid, text)),
        now_func=lambda: monday_morning,
    )

    scanner.run_check()

    assert sent == []


def test_sends_noon_alert_for_urgent_incomplete_task_past_grace_period():
    worksheet = FakeWorksheet("clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00")])
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert len(sent) == 1
    jid, text = sent[0]
    assert jid == "573042747698@s.whatsapp.net"
    assert "clinicachia" in text
    assert "Revisar algo" in text
    assert worksheet.update_cell_calls == [(2, 8, "2026-08-10")]


def test_does_not_resend_noon_alert_same_day():
    worksheet = FakeWorksheet(
        "clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00", alerta_12pm="2026-08-10")]
    )
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert sent == []


def test_resends_noon_alert_next_day():
    worksheet = FakeWorksheet(
        "clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00", alerta_12pm="2026-08-10")]
    )
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 11, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert len(sent) == 1
    assert worksheet.update_cell_calls == [(2, 8, "2026-08-11")]


def test_evaluates_5pm_alert_independently_of_noon():
    worksheet = FakeWorksheet(
        "clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00", alerta_12pm="2026-08-10")]
    )
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 17, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert len(sent) == 1
    assert worksheet.update_cell_calls == [(2, 9, "2026-08-10")]


def test_ignores_non_urgent_task():
    worksheet = FakeWorksheet("clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00", urgente="No")])
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert sent == []


def test_ignores_completed_task():
    worksheet = FakeWorksheet(
        "clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00", estado="Completada")]
    )
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert sent == []


def test_ignores_task_within_grace_period():
    worksheet = FakeWorksheet("clinicachia", [_HEADERS, _row(fecha="2026-08-10 11:00")])
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert sent == []


def test_continues_scanning_other_members_when_one_fails():
    worksheet = FakeWorksheet("clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00")])
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient(
        [("Roto", "573000000000", "sheet-broken"), ("Eduar", "573042747698", "sheet-eduar")]
    )
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert len(sent) == 1
    assert sent[0][0] == "573042747698@s.whatsapp.net"


def test_does_not_mark_as_sent_when_message_send_fails():
    worksheet = FakeWorksheet("clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00")])
    spreadsheet = FakeSpreadsheet([worksheet])
    sheets_client = FakeSheetsClient([("Eduar", "573042747698", "sheet-eduar")])
    gspread_client = FakeGspreadClient({"sheet-eduar": spreadsheet})
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)

    def raise_send(jid, text):
        raise RuntimeError("evolution api down")

    scanner = ReminderScanner(sheets_client, gspread_client, raise_send, now_func=lambda: now)

    scanner.run_check()

    assert worksheet.update_cell_calls == []


def test_skips_members_without_sheet_id():
    sheets_client = FakeSheetsClient([("SinHoja", "573000000000", "")])
    gspread_client = FakeGspreadClient({})
    sent = []
    now = datetime(2026, 8, 10, 12, 30, tzinfo=TZ)
    scanner = ReminderScanner(
        sheets_client, gspread_client, lambda jid, text: sent.append((jid, text)), now_func=lambda: now
    )

    scanner.run_check()

    assert sent == []
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reminder_scanner.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.reminder_scanner'`

- [ ] **Step 3: Write the implementation**

Create `services/reminder_scanner.py`:

```python
"""
Scans every team member's personal Google Sheet for urgent, incomplete
tasks and sends a WhatsApp reminder to their personal number at noon and
5pm on weekdays, respecting a 2-hour grace period after the task was
created. Already-sent alerts are tracked in the Sheet itself (the
"Alerta 12pm" / "Alerta 5pm" columns hold the date they were last sent),
so restarting the bot never duplicates or loses an alert.
"""
import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import Config

logger = logging.getLogger(__name__)

_URGENT_YES = "Sí"
_STATUS_COMPLETED = "Completada"
_MIN_HOURS_SINCE_CREATION = 2
_NOON_HOUR = 12
_FIVE_PM_HOUR = 17

# Column indices (0-based), matching PersonalTaskWriter._HEADERS order:
# Fecha, Reportado por, Descripción, Fecha límite, Hora, Estado, Urgente,
# Alerta 12pm, Alerta 5pm
_COL_FECHA = 0
_COL_DESCRIPCION = 2
_COL_ESTADO = 5
_COL_URGENTE = 6
_COL_ALERTA_12PM = 7
_COL_ALERTA_5PM = 8


class ReminderScanner:
    def __init__(self, sheets_client, gspread_client, send_message, now_func=None):
        self._sheets_client = sheets_client
        self._gspread_client = gspread_client
        self._send_message = send_message
        self._now_func = now_func or (lambda: datetime.now(ZoneInfo(Config.TIMEZONE)))

    def run_check(self) -> None:
        now = self._now_func()
        if now.weekday() >= 5:
            return

        noon_open = now.hour >= _NOON_HOUR
        if not noon_open:
            return
        five_pm_open = now.hour >= _FIVE_PM_HOUR

        for name, phone, sheet_id in self._sheets_client.read_team_roster():
            if not sheet_id:
                continue
            try:
                self._scan_member(sheet_id, phone, now, noon_open, five_pm_open)
            except Exception:
                logger.exception("Failed to scan reminders for %s (sheet %s)", name, sheet_id)

    def _scan_member(self, sheet_id, phone, now, noon_open, five_pm_open) -> None:
        spreadsheet = self._gspread_client.open_by_key(sheet_id)
        phone_jid = f"{phone}@s.whatsapp.net"
        for worksheet in spreadsheet.worksheets():
            client_name = worksheet.title
            rows = worksheet.get_all_values()[1:]
            for offset, row in enumerate(rows):
                row_number = offset + 2  # 1 header row, gspread rows are 1-indexed
                self._scan_row(
                    worksheet, row, row_number, client_name, phone_jid, now, noon_open, five_pm_open
                )

    def _scan_row(
        self, worksheet, row, row_number, client_name, phone_jid, now, noon_open, five_pm_open
    ) -> None:
        if len(row) <= _COL_URGENTE or row[_COL_URGENTE] != _URGENT_YES:
            return
        if len(row) > _COL_ESTADO and row[_COL_ESTADO] == _STATUS_COMPLETED:
            return

        created_at = self._parse_created_at(row[_COL_FECHA] if row else "")
        if created_at is None:
            return
        if now - created_at < timedelta(hours=_MIN_HOURS_SINCE_CREATION):
            return

        today_str = now.date().isoformat()
        description = row[_COL_DESCRIPCION] if len(row) > _COL_DESCRIPCION else ""

        alerta_12pm = row[_COL_ALERTA_12PM] if len(row) > _COL_ALERTA_12PM else ""
        if noon_open and alerta_12pm != today_str:
            self._send_and_mark(
                worksheet, row_number, _COL_ALERTA_12PM, phone_jid, client_name, description, today_str
            )

        alerta_5pm = row[_COL_ALERTA_5PM] if len(row) > _COL_ALERTA_5PM else ""
        if five_pm_open and alerta_5pm != today_str:
            self._send_and_mark(
                worksheet, row_number, _COL_ALERTA_5PM, phone_jid, client_name, description, today_str
            )

    def _send_and_mark(
        self, worksheet, row_number, alert_col, phone_jid, client_name, description, today_str
    ) -> None:
        message = (
            f'⏰ Recordatorio: tienes pendiente la tarea urgente de *{client_name}*: '
            f'"{description}". Márcala como "Completada" en tu Sheet cuando la termines.'
        )
        try:
            self._send_message(phone_jid, message)
        except Exception:
            logger.exception("Failed to send reminder to %s", phone_jid)
            return
        worksheet.update_cell(row_number, alert_col + 1, today_str)

    @staticmethod
    def _parse_created_at(value: str) -> datetime | None:
        try:
            naive = datetime.strptime(value, "%Y-%m-%d %H:%M")
        except ValueError:
            return None
        return naive.replace(tzinfo=ZoneInfo(Config.TIMEZONE))


def create_reminder_scanner(sheets_client, credentials_path: str) -> "ReminderScanner":
    """Builds a live ReminderScanner. Not covered by unit tests -- requires
    real service-account credentials."""
    import gspread

    from services.evolution import send_text_message

    gc = gspread.service_account(filename=credentials_path)
    return ReminderScanner(sheets_client, gc, send_text_message)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reminder_scanner.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add services/reminder_scanner.py tests/test_reminder_scanner.py
git commit -m "Add ReminderScanner to detect and send urgent-task WhatsApp reminders"
```

---

## Task 5: reminder_scheduler.py — the background loop

**Files:**
- Create: `services/reminder_scheduler.py`
- Test: `tests/test_reminder_scheduler.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_reminder_scheduler.py`:

```python
import asyncio

import pytest

from services.reminder_scheduler import run_reminder_loop


class StopLoop(Exception):
    pass


class FakeScanner:
    def __init__(self, fail_times=0):
        self.check_calls = 0
        self._fail_times = fail_times

    def run_check(self):
        self.check_calls += 1
        if self.check_calls <= self._fail_times:
            raise RuntimeError("boom")


def _run(coro):
    asyncio.run(coro)


def test_runs_check_immediately_before_first_sleep():
    scanner = FakeScanner()
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise StopLoop()

    with pytest.raises(StopLoop):
        _run(run_reminder_loop(scanner, interval_seconds=900, sleep=fake_sleep))

    assert scanner.check_calls == 1
    assert sleep_calls == [900]


def test_keeps_looping_after_check_raises():
    scanner = FakeScanner(fail_times=1)
    sleep_count = {"n": 0}

    async def fake_sleep(seconds):
        sleep_count["n"] += 1
        if sleep_count["n"] >= 2:
            raise StopLoop()

    with pytest.raises(StopLoop):
        _run(run_reminder_loop(scanner, interval_seconds=1, sleep=fake_sleep))

    assert scanner.check_calls == 2


def test_dispatches_check_via_run_in_thread():
    scanner = FakeScanner()
    dispatched = []

    async def fake_run_in_thread(func):
        dispatched.append(func)
        return func()

    async def fake_sleep(seconds):
        raise StopLoop()

    with pytest.raises(StopLoop):
        _run(
            run_reminder_loop(
                scanner, interval_seconds=900, sleep=fake_sleep, run_in_thread=fake_run_in_thread
            )
        )

    assert dispatched == [scanner.run_check]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_reminder_scheduler.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.reminder_scheduler'`

- [ ] **Step 3: Write the implementation**

Create `services/reminder_scheduler.py`:

```python
"""
Runs ReminderScanner.run_check() on a fixed interval in the background,
for as long as the app is running. Dispatches each check to a thread pool
(like the webhook handlers) since it does blocking I/O (Google Sheets,
Evolution API), so it never blocks the event loop. Any exception during a
single check is logged and the loop keeps going -- a bad check should
never stop future reminders from being evaluated.
"""
import asyncio
import logging

logger = logging.getLogger(__name__)

_DEFAULT_INTERVAL_SECONDS = 900  # 15 minutes


async def run_reminder_loop(
    scanner,
    interval_seconds: float = _DEFAULT_INTERVAL_SECONDS,
    sleep=asyncio.sleep,
    run_in_thread=asyncio.to_thread,
) -> None:
    while True:
        try:
            await run_in_thread(scanner.run_check)
        except Exception:
            logger.exception("Reminder check failed")
        await sleep(interval_seconds)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_reminder_scheduler.py -v`
Expected: PASS (3 tests)

- [ ] **Step 5: Commit**

```bash
git add services/reminder_scheduler.py tests/test_reminder_scheduler.py
git commit -m "Add background loop that runs ReminderScanner every 15 minutes"
```

---

## Task 6: main.py — wire the reminder loop into the app

**Files:**
- Modify: `main.py`

- [ ] **Step 1: Write the implementation**

This task has no new automated test: `main.py`'s `lifespan` function (which constructs `SheetsClient`, `Roster`, `GroupRegistry`, `LidResolver`, and `PersonalTaskWriter` today) has never had direct unit-test coverage -- those objects require real Google/OpenAI credentials, so they're validated by running the app for real, not by a test double. The reminder loop follows the same established pattern. What *is* verified automatically is that nothing about the existing `/webhook` route or its tests changes -- confirmed in Step 3 below.

Replace the full contents of `main.py` with:

```python
"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler and the spelling-review handler. Google Sheets / roster clients
are created lazily on startup so importing this module has no side effects
(needed for testing). Handlers run in a thread pool (not directly on the
event loop) since they do blocking network I/O (OpenAI, Google Sheets,
Evolution API). A background loop also runs on a fixed interval to check
for urgent tasks that need a WhatsApp reminder.
"""
import asyncio
import logging
from contextlib import asynccontextmanager, suppress

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from config import Config
from handlers.spelling_handler import handle_webhook_payload as handle_spelling_payload
from handlers.task_handler import handle_webhook_payload as handle_task_payload
from services.group_registry import GroupRegistry
from services.image_batch import ImageBatchBuffer
from services.lid_resolver import LidResolver
from services.reminder_scanner import create_reminder_scanner
from services.reminder_scheduler import run_reminder_loop
from services.roster import Roster
from services.sheets_client import create_personal_task_writer, create_sheets_client

logging.basicConfig(level=Config.LOG_LEVEL)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    Config.validate()
    sheets_client = create_sheets_client(Config.GOOGLE_SHEETS_ID, Config.GOOGLE_CREDENTIALS_PATH)
    app.state.sheets_client = sheets_client
    app.state.roster = Roster(sheets_client)
    app.state.group_registry = GroupRegistry(sheets_client)
    app.state.lid_resolver = LidResolver()
    app.state.personal_task_writer = create_personal_task_writer(Config.GOOGLE_CREDENTIALS_PATH)
    app.state.image_batch_buffer = ImageBatchBuffer()

    reminder_scanner = create_reminder_scanner(sheets_client, Config.GOOGLE_CREDENTIALS_PATH)
    reminder_task = asyncio.create_task(run_reminder_loop(reminder_scanner))
    try:
        yield
    finally:
        reminder_task.cancel()
        with suppress(asyncio.CancelledError):
            await reminder_task


app = FastAPI(lifespan=lifespan)


@app.post("/webhook")
async def webhook(request: Request):
    try:
        payload = await request.json()
    except Exception:
        logger.exception("Failed to parse webhook JSON body")
        return {"status": "ok"}

    try:
        await run_in_threadpool(
            handle_task_payload,
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            request.app.state.group_registry,
            request.app.state.personal_task_writer,
        )
    except Exception:
        logger.exception("Failed to process task webhook payload")

    try:
        await run_in_threadpool(
            handle_spelling_payload,
            payload,
            request.app.state.roster,
            request.app.state.lid_resolver,
            request.app.state.group_registry,
            request.app.state.image_batch_buffer,
        )
    except Exception:
        logger.exception("Failed to process spelling webhook payload")

    return {"status": "ok"}
```

- [ ] **Step 2: Run the existing main.py tests to confirm nothing broke**

Run: `pytest tests/test_main.py -v`
Expected: PASS (6 tests) -- `tests/test_main.py` sets `app.state.*` directly and never triggers `lifespan` (confirmed by the fact these tests already pass today without real Google/OpenAI credentials), so this change is invisible to them. This step exists specifically to prove the `/webhook` route behavior is unaffected by adding the reminder loop.

- [ ] **Step 3: Run the full test suite**

Run: `pytest -v`
Expected: PASS -- every test in the project, including all the ones from Tasks 1-5.

- [ ] **Step 4: Commit**

```bash
git add main.py
git commit -m "Launch the urgent-task reminder loop alongside the webhook route"
```

---

## Task 7: Documentation — README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Update `README.md`**

In `README.md`, find this paragraph inside the "Setup" numbered list (step 5):

```
5. Por cada integrante del equipo: crear (o usar) su Google Sheet personal, **compartirlo con el
   correo de la cuenta de servicio** (el mismo JSON de `GOOGLE_CREDENTIALS_PATH`) con permiso de
   Editor, y poner su ID en la columna "Sheet ID" de "Equipo". Las pestañas por cliente se crean
   automáticamente la primera vez que se le asigna una tarea de ese cliente -- no hay que crearlas
   a mano. Cada pestaña nueva se crea con columnas `Fecha | Reportado por | Descripción | Fecha
   límite | Hora | Estado`, y la columna "Estado" ya viene con un desplegable de colores
   (Pendiente / En progreso / Completada).
```

Replace it with:

```
5. Por cada integrante del equipo: crear (o usar) su Google Sheet personal, **compartirlo con el
   correo de la cuenta de servicio** (el mismo JSON de `GOOGLE_CREDENTIALS_PATH`) con permiso de
   Editor, y poner su ID en la columna "Sheet ID" de "Equipo". Las pestañas por cliente se crean
   automáticamente la primera vez que se le asigna una tarea de ese cliente -- no hay que crearlas
   a mano. Cada pestaña nueva se crea con columnas `Fecha | Reportado por | Descripción | Fecha
   límite | Hora | Estado | Urgente | Alerta 12pm | Alerta 5pm`, y la columna "Estado" ya viene con
   un desplegable de colores (Pendiente / En progreso / Completada).
6. Las tareas que la IA marca como urgentes (fecha límite el mismo día, o lenguaje explícito de
   urgencia) reciben un recordatorio automático por WhatsApp al número personal de la persona
   asignada a las 12 m. y a las 5 p. m., de lunes a viernes, mientras la tarea siga sin marcarse
   como "Completada". Este chequeo corre solo dentro del propio bot -- no requiere configuración
   adicional. Ver `docs/superpowers/specs/2026-08-10-urgent-task-reminders-design.md`.
```

Then renumber the remaining steps in the list (the old step 6 "Agregar el bot a cada grupo..." becomes step 7, old step 7 becomes step 8, old step 8 "Activar Webhook Base64..." becomes step 9) so the list stays sequential.

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "Document the urgent-task reminder system in the README"
```
