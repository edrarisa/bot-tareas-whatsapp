# Multi-Grupo y Enrutamiento de Tareas por Cliente Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Support the bot being added to several WhatsApp groups (one per client), route each task to the mentioned person's own Google Sheet under a tab named after the client, and make image spelling review work across all configured groups too.

**Architecture:** A new `GroupRegistry` (mirrors `Roster`'s TTL-cached-sheet-read pattern) maps each WhatsApp group JID to a client name via a new "Grupos" tab. `Roster` gains a personal Sheet ID per person. A new `PersonalTaskWriter` opens each assignee's own spreadsheet by ID and auto-creates the client's tab the first time it's needed. `LidResolver` stops being bound to a single group at construction and caches participants per group instead. Both handlers replace their single fixed `group_jid` filter with a `GroupRegistry` lookup, and `Config.WHATSAPP_GROUP_JID` goes away entirely.

**Tech Stack:** Same as the rest of the bot -- Python 3.13, FastAPI, `gspread`, `requests`. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-08-06-multi-client-task-routing-design.md`

---

## File Structure

```
bot-tareas-whatsapp/
├── main.py                          MODIFY: wire GroupRegistry + PersonalTaskWriter, drop WHATSAPP_GROUP_JID
├── config.py                        MODIFY: remove WHATSAPP_GROUP_JID
├── .env.example                     MODIFY: remove WHATSAPP_GROUP_JID
├── README.md                        MODIFY: document Grupos tab, Equipo's new column, personal sheets
├── services/
│   ├── group_registry.py            CREATE: GroupRegistry (group_jid -> client name)
│   ├── sheets_client.py             MODIFY: 3-column Equipo, read_group_mapping, PersonalTaskWriter
│   ├── roster.py                    MODIFY: resolve_personal_sheet_id
│   └── lid_resolver.py              MODIFY: per-group participant caching, resolve(jid, group_jid)
├── handlers/
│   ├── task_handler.py              MODIFY: GroupRegistry filter, personal-sheet routing, new warnings
│   └── spelling_handler.py          MODIFY: GroupRegistry filter, batch key includes group
└── tests/
    ├── test_group_registry.py       CREATE
    ├── test_sheets_client.py        REWRITE
    ├── test_roster.py               REWRITE
    ├── test_lid_resolver.py         REWRITE
    ├── test_config.py               MODIFY
    ├── test_task_handler.py         REWRITE
    ├── test_spelling_handler.py     REWRITE
    └── test_main.py                 REWRITE
```

---

## Task 1: GroupRegistry

**Files:**
- Create: `services/group_registry.py`
- Test: `tests/test_group_registry.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_group_registry.py`:

```python
import pytest

from services.group_registry import GroupRegistry


class FakeSheetsClient:
    def __init__(self, rows):
        self._rows = rows
        self.read_calls = 0
        self.raise_exc = None

    def read_group_mapping(self):
        self.read_calls += 1
        if self.raise_exc is not None:
            exc = self.raise_exc
            self.raise_exc = None  # One-time exception
            raise exc
        return self._rows


def test_get_client_name_returns_client_for_known_group():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    registry = GroupRegistry(sheets_client)

    assert registry.get_client_name("120363429440515454@g.us") == "clinicachia"


def test_get_client_name_returns_none_for_unknown_group():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    registry = GroupRegistry(sheets_client)

    assert registry.get_client_name("999999999999999@g.us") is None


def test_caches_mapping_within_ttl():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    clock = {"now": 1000.0}
    registry = GroupRegistry(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    registry.get_client_name("120363429440515454@g.us")
    registry.get_client_name("120363429440515454@g.us")
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    registry.get_client_name("120363429440515454@g.us")
    assert sheets_client.read_calls == 2


def test_falls_back_to_stale_cache_when_refresh_fails():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    clock = {"now": 1000.0}
    registry = GroupRegistry(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    assert registry.get_client_name("120363429440515454@g.us") == "clinicachia"
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    sheets_client.raise_exc = ValueError("Sheets API error")

    assert registry.get_client_name("120363429440515454@g.us") == "clinicachia"
    assert sheets_client.read_calls == 2


def test_raises_when_first_load_fails():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    sheets_client.raise_exc = ValueError("Sheets API error")
    registry = GroupRegistry(sheets_client)

    with pytest.raises(ValueError, match="Sheets API error"):
        registry.get_client_name("120363429440515454@g.us")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_group_registry.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'services.group_registry'`

- [ ] **Step 3: Write the implementation**

Create `services/group_registry.py`:

```python
"""
Resolves WhatsApp group JIDs to a client name via the "Grupos" tab, caching
in memory for a short TTL (same pattern as Roster) so the bot supports
several groups -- one per client -- without hitting the Sheets API on every
message.
"""
import logging
import time

logger = logging.getLogger(__name__)


class GroupRegistry:
    def __init__(self, sheets_client, ttl_seconds: int = 300, time_func=time.monotonic):
        self._sheets_client = sheets_client
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._by_group: dict[str, str] = {}
        self._loaded_at: float = float("-inf")

    def _ensure_loaded(self) -> None:
        now = self._time_func()
        if self._loaded_at != float("-inf") and now - self._loaded_at <= self._ttl_seconds:
            return
        try:
            rows = self._sheets_client.read_group_mapping()
        except Exception:
            if self._loaded_at == float("-inf"):
                raise
            logger.warning("Failed to refresh group mapping, using stale cache", exc_info=True)
            return
        self._by_group = {group_jid: client_name for group_jid, client_name in rows}
        self._loaded_at = now

    def get_client_name(self, group_jid: str) -> str | None:
        self._ensure_loaded()
        return self._by_group.get(group_jid)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_group_registry.py -v`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add services/group_registry.py tests/test_group_registry.py
git commit -m "Add GroupRegistry to map WhatsApp groups to client names"
```

---

## Task 2: SheetsClient (3-column Equipo, Grupos tab) + PersonalTaskWriter

**Files:**
- Modify: `services/sheets_client.py`
- Test: `tests/test_sheets_client.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_sheets_client.py` with:

```python
from gspread.exceptions import WorksheetNotFound

from services.sheets_client import PersonalTaskWriter, SheetsClient


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

    def worksheet(self, name):
        if name not in self._worksheets:
            raise WorksheetNotFound(name)
        return self._worksheets[name]

    def add_worksheet(self, title, rows, cols):
        self.add_worksheet_calls.append((title, rows, cols))
        worksheet = FakeWorksheet()
        self._worksheets[title] = worksheet
        return worksheet


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
        status="Pendiente",
    )

    assert spreadsheet.add_worksheet_calls == [("clinicachia", 100, 5)]
    worksheet = spreadsheet._worksheets["clinicachia"]
    assert worksheet.appended_rows == [
        ["Fecha", "Reportado por", "Descripción", "Fecha límite", "Estado"],
        ["2026-08-06 10:00", "Ana", "Revisar el stand", "2026-08-07", "Pendiente"],
    ]


def test_personal_task_writer_reuses_existing_client_tab():
    existing_tab = FakeWorksheet(
        values=[["Fecha", "Reportado por", "Descripción", "Fecha límite", "Estado"]]
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
        status="Pendiente",
    )

    assert spreadsheet.add_worksheet_calls == []
    assert existing_tab.appended_rows == [
        ["2026-08-06 10:00", "Ana", "Revisar el stand", "", "Pendiente"]
    ]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_sheets_client.py -v`
Expected: FAIL -- `read_team_roster` returns 2-tuples not 3-tuples, `read_group_mapping` and `PersonalTaskWriter` don't exist yet.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `services/sheets_client.py` with:

```python
"""
Thin wrapper over gspread. `SheetsClient` reads the shared "Equipo" and
"Grupos" tabs from the central config spreadsheet. `PersonalTaskWriter`
writes tasks to each team member's own personal spreadsheet, creating the
client's tab automatically the first time a task is logged for it. Both
take already-open gspread objects so they can be unit-tested without a
live Google Sheets connection.
"""
from gspread.exceptions import WorksheetNotFound


class SheetsClient:
    def __init__(self, spreadsheet):
        self._spreadsheet = spreadsheet

    def read_team_roster(self) -> list[tuple[str, str, str]]:
        worksheet = self._spreadsheet.worksheet("Equipo")
        rows = worksheet.get_all_values()[1:]
        result = []
        for row in rows:
            if len(row) < 2 or not row[0].strip() or not row[1].strip():
                continue
            sheet_id = row[2].strip() if len(row) >= 3 else ""
            result.append((row[0], row[1], sheet_id))
        return result

    def read_group_mapping(self) -> list[tuple[str, str]]:
        worksheet = self._spreadsheet.worksheet("Grupos")
        rows = worksheet.get_all_values()[1:]
        return [
            (row[0], row[1])
            for row in rows
            if len(row) >= 2 and row[0].strip() and row[1].strip()
        ]


class PersonalTaskWriter:
    """Writes tasks to each team member's own Google Sheet, in a tab named
    after the client. Takes the raw gspread client (not a fixed
    spreadsheet) since it needs to open a different spreadsheet per
    assignee."""

    _HEADERS = ["Fecha", "Reportado por", "Descripción", "Fecha límite", "Estado"]

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
        worksheet.append_row([created_at, reporter, description, due_date or "", status])


def create_sheets_client(sheet_id: str, credentials_path: str) -> SheetsClient:
    """Opens a live Google Sheets connection to the central config
    spreadsheet. Not covered by unit tests -- requires real
    service-account credentials."""
    import gspread

    gc = gspread.service_account(filename=credentials_path)
    spreadsheet = gc.open_by_key(sheet_id)
    return SheetsClient(spreadsheet)


def create_personal_task_writer(credentials_path: str) -> PersonalTaskWriter:
    """Opens a live Google Sheets connection for writing to team members'
    personal spreadsheets. Not covered by unit tests -- requires real
    service-account credentials."""
    import gspread

    gc = gspread.service_account(filename=credentials_path)
    return PersonalTaskWriter(gc)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_sheets_client.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add services/sheets_client.py tests/test_sheets_client.py
git commit -m "Add PersonalTaskWriter and Grupos tab reading to SheetsClient"
```

---

## Task 3: Roster — personal Sheet ID

**Files:**
- Modify: `services/roster.py`
- Test: `tests/test_roster.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_roster.py` with:

```python
import pytest

from services.roster import Roster


class FakeSheetsClient:
    def __init__(self, rows):
        self._rows = rows
        self.read_calls = 0
        self.raise_exc = None

    def read_team_roster(self):
        self.read_calls += 1
        if self.raise_exc is not None:
            exc = self.raise_exc
            self.raise_exc = None  # One-time exception
            raise exc
        return self._rows


def test_is_known_sender_true_for_roster_member():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573001112233@s.whatsapp.net") is True


def test_is_known_sender_false_for_unknown_number():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573009998877@s.whatsapp.net") is False


def test_resolve_name_returns_name_for_known_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_resolve_name_returns_none_for_unknown_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573009998877@s.whatsapp.net") is None


def test_normalizes_non_digit_characters_in_stored_numbers():
    sheets_client = FakeSheetsClient([("Cristian", "+57 300 111 2233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_caches_roster_within_ttl():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    clock = {"now": 1000.0}
    roster = Roster(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    roster.is_known_sender("573001112233@s.whatsapp.net")
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 2


def test_falls_back_to_stale_cache_when_refresh_fails():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    clock = {"now": 1000.0}
    roster = Roster(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    # First successful load
    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"
    assert sheets_client.read_calls == 1

    # Advance past TTL and make next read fail
    clock["now"] += 301
    sheets_client.raise_exc = ValueError("Sheets API error")

    # Should use stale cache instead of raising
    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"
    assert sheets_client.read_calls == 2


def test_same_person_true_for_jids_with_different_device_suffix():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.same_person("573001112233@s.whatsapp.net", "573001112233:19@s.whatsapp.net") is True


def test_same_person_false_for_different_numbers():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.same_person("573001112233@s.whatsapp.net", "573009998877@s.whatsapp.net") is False


def test_raises_when_first_load_fails():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    sheets_client.raise_exc = ValueError("Sheets API error")
    roster = Roster(sheets_client)

    # Should raise because there's no cache to fall back to
    with pytest.raises(ValueError, match="Sheets API error"):
        roster.is_known_sender("573001112233@s.whatsapp.net")


def test_resolve_personal_sheet_id_returns_sheet_id_for_known_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_personal_sheet_id("573001112233@s.whatsapp.net") == "sheet-cristian"


def test_resolve_personal_sheet_id_returns_none_for_unknown_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_personal_sheet_id("573009998877@s.whatsapp.net") is None


def test_resolve_personal_sheet_id_returns_none_when_not_configured():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "")])
    roster = Roster(sheets_client)

    assert roster.resolve_personal_sheet_id("573001112233@s.whatsapp.net") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_roster.py -v`
Expected: FAIL -- `FakeSheetsClient` now returns 3-tuples but `Roster` still unpacks 2-tuples (`ValueError: too many values to unpack`), and `resolve_personal_sheet_id` doesn't exist.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `services/roster.py` with:

```python
"""
Resolves WhatsApp JIDs against the "Equipo" roster tab, caching the roster
in memory for a short TTL to avoid hitting the Sheets API on every message.
"""
import logging
import time

logger = logging.getLogger(__name__)


class Roster:
    def __init__(self, sheets_client, ttl_seconds: int = 300, time_func=time.monotonic):
        self._sheets_client = sheets_client
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._by_phone: dict[str, tuple[str, str]] = {}
        self._loaded_at: float = float("-inf")

    def _ensure_loaded(self) -> None:
        now = self._time_func()
        if self._loaded_at != float("-inf") and now - self._loaded_at <= self._ttl_seconds:
            return
        try:
            rows = self._sheets_client.read_team_roster()
        except Exception:
            if self._loaded_at == float("-inf"):
                raise
            logger.warning("Failed to refresh roster, using stale cache", exc_info=True)
            return
        self._by_phone = {
            self._normalize(number): (name, sheet_id) for name, number, sheet_id in rows
        }
        self._loaded_at = now

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(ch for ch in value if ch.isdigit())

    @staticmethod
    def _phone_from_jid(jid: str) -> str:
        # JIDs may carry a device suffix (e.g. "573001112233:19@s.whatsapp.net"),
        # which must be dropped before comparing/normalizing the phone number.
        return jid.split("@", 1)[0].split(":", 1)[0]

    def is_known_sender(self, jid: str) -> bool:
        self._ensure_loaded()
        return self._normalize(self._phone_from_jid(jid)) in self._by_phone

    def resolve_name(self, jid: str) -> str | None:
        self._ensure_loaded()
        entry = self._by_phone.get(self._normalize(self._phone_from_jid(jid)))
        return entry[0] if entry else None

    def resolve_personal_sheet_id(self, jid: str) -> str | None:
        self._ensure_loaded()
        entry = self._by_phone.get(self._normalize(self._phone_from_jid(jid)))
        if entry is None:
            return None
        return entry[1] or None

    def same_person(self, jid_a: str, jid_b: str) -> bool:
        return self._normalize(self._phone_from_jid(jid_a)) == self._normalize(self._phone_from_jid(jid_b))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_roster.py -v`
Expected: PASS (13 tests)

- [ ] **Step 5: Commit**

```bash
git add services/roster.py tests/test_roster.py
git commit -m "Add personal Sheet ID to Roster"
```

---

## Task 4: LidResolver — per-group participant caching

**Files:**
- Modify: `services/lid_resolver.py`
- Test: `tests/test_lid_resolver.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_lid_resolver.py` with:

```python
import pytest

from services.lid_resolver import LidResolver

GROUP_JID = "120363429677992008@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"


def _fake_response(status_code=200, json_data=None):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code
            self.text = str(json_data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return json_data

    return FakeResponse()


def test_returns_non_lid_jids_unchanged():
    resolver = LidResolver()
    assert resolver.resolve("573042747698@s.whatsapp.net", GROUP_JID) == "573042747698@s.whatsapp.net"


def test_resolves_lid_to_phone_jid(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["count"] += 1
        return _fake_response(
            json_data={
                "participants": [
                    {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"},
                    {"id": "203744859922485@lid", "phoneNumber": "573118964235@s.whatsapp.net"},
                ]
            }
        )

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"
    assert resolver.resolve("203744859922485@lid", GROUP_JID) == "573118964235@s.whatsapp.net"
    assert calls["count"] == 1


def test_returns_unknown_lid_unchanged(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _fake_response(json_data={"participants": []})

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("999999999999999@lid", GROUP_JID) == "999999999999999@lid"


def test_skips_participants_without_a_resolvable_phone_number(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _fake_response(
            json_data={
                "participants": [
                    {"id": "111111111111111@lid", "admin": None},
                    {"id": "222222222222222@lid", "phoneNumber": "573000000000@s.whatsapp.net"},
                ]
            }
        )

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("111111111111111@lid", GROUP_JID) == "111111111111111@lid"
    assert resolver.resolve("222222222222222@lid", GROUP_JID) == "573000000000@s.whatsapp.net"


def test_caches_participants_within_ttl(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["count"] += 1
        return _fake_response(
            json_data={
                "participants": [
                    {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"}
                ]
            }
        )

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    clock = {"now": 1000.0}
    resolver = LidResolver(ttl_seconds=300, time_func=lambda: clock["now"])

    resolver.resolve("151556578083034@lid", GROUP_JID)
    resolver.resolve("151556578083034@lid", GROUP_JID)
    assert calls["count"] == 1

    clock["now"] += 301
    resolver.resolve("151556578083034@lid", GROUP_JID)
    assert calls["count"] == 2


def test_falls_back_to_stale_cache_when_refresh_fails(monkeypatch):
    responses = [
        _fake_response(
            json_data={
                "participants": [
                    {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"}
                ]
            }
        )
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if responses:
            return responses.pop()
        raise RuntimeError("network down")

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    clock = {"now": 1000.0}
    resolver = LidResolver(ttl_seconds=300, time_func=lambda: clock["now"])

    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"

    clock["now"] += 301
    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"


def test_raises_when_first_load_fails(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    with pytest.raises(RuntimeError):
        resolver.resolve("151556578083034@lid", GROUP_JID)


def test_caches_are_isolated_per_group(monkeypatch):
    """Resolving a LID for one group must not use another group's cached
    participants -- each group has its own participant list."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        group_jid = params["groupJid"]
        calls.append(group_jid)
        if group_jid == GROUP_JID:
            participants = [
                {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"}
            ]
        else:
            participants = [
                {"id": "151556578083034@lid", "phoneNumber": "573099998877@s.whatsapp.net"}
            ]
        return _fake_response(json_data={"participants": participants})

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"
    assert resolver.resolve("151556578083034@lid", OTHER_GROUP_JID) == "573099998877@s.whatsapp.net"
    assert calls == [GROUP_JID, OTHER_GROUP_JID]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_lid_resolver.py -v`
Expected: FAIL -- `LidResolver()` currently requires a `group_jid` positional argument, and `resolve()` doesn't accept a second argument.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `services/lid_resolver.py` with:

```python
"""
Resolves WhatsApp's privacy LIDs (opaque "@lid" identifiers) back to the
real phone-number JID, by querying Evolution API's group participants
endpoint. WhatsApp increasingly sends "@lid" identifiers instead of phone
numbers for message senders and mentions, so this sits in front of Roster
lookups to translate them back to something Roster can match.

Caches participants per group, since the bot can be in more than one group
at a time -- each group has its own participant list and its own TTL.
"""
import logging
import time

import requests

from config import Config

logger = logging.getLogger(__name__)


class LidResolver:
    def __init__(self, ttl_seconds: int = 300, time_func=time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._lid_to_phone_jid: dict[str, dict[str, str]] = {}
        self._loaded_at: dict[str, float] = {}

    def resolve(self, jid: str, group_jid: str) -> str:
        """Returns the real phone-number JID for a "@lid" identifier.

        Returns the input unchanged if it isn't a "@lid" JID, or if it
        can't be resolved (e.g. the participant's number is itself
        hidden).
        """
        if not jid.endswith("@lid"):
            return jid
        self._ensure_loaded(group_jid)
        mapping = self._lid_to_phone_jid.get(group_jid, {})
        resolved = mapping.get(jid, jid)
        logger.info(
            "LID resolve: %s -> %s (%d entries in map for %s)",
            jid,
            resolved,
            len(mapping),
            group_jid,
        )
        return resolved

    def _ensure_loaded(self, group_jid: str) -> None:
        now = self._time_func()
        loaded_at = self._loaded_at.get(group_jid, float("-inf"))
        if loaded_at != float("-inf") and now - loaded_at <= self._ttl_seconds:
            return
        try:
            participants = self._fetch_participants(group_jid)
        except Exception:
            logger.warning("Failed to fetch group participants for LID mapping", exc_info=True)
            if loaded_at == float("-inf"):
                raise
            logger.warning("Failed to refresh LID mapping, using stale cache", exc_info=True)
            return
        self._lid_to_phone_jid[group_jid] = {
            p["id"]: p["phoneNumber"]
            for p in participants
            if p.get("id") and p.get("phoneNumber")
        }
        self._loaded_at[group_jid] = now
        logger.info(
            "Loaded LID mapping for %s: %d participants, %d with a resolvable phone number",
            group_jid,
            len(participants),
            len(self._lid_to_phone_jid[group_jid]),
        )

    def _fetch_participants(self, group_jid: str) -> list[dict]:
        url = f"{Config.EVOLUTION_API_URL.rstrip('/')}/group/participants/{Config.EVOLUTION_INSTANCE}"
        headers = {"apikey": Config.EVOLUTION_API_KEY}
        response = requests.get(
            url, headers=headers, params={"groupJid": group_jid}, timeout=30
        )
        logger.info("Group participants fetch: HTTP %s, body: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()
        return data.get("participants", data if isinstance(data, list) else [])
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_lid_resolver.py -v`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add services/lid_resolver.py tests/test_lid_resolver.py
git commit -m "Cache LID resolution per group instead of a single fixed group"
```

---

## Task 5: Config — remove WHATSAPP_GROUP_JID

**Files:**
- Modify: `config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write the failing test change**

In `tests/test_config.py`, remove `"WHATSAPP_GROUP_JID",` from `REQUIRED_ATTRS` so the full list reads:

```python
import pytest

from config import Config

REQUIRED_ATTRS = [
    "EVOLUTION_API_URL",
    "EVOLUTION_API_KEY",
    "EVOLUTION_INSTANCE",
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

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL -- `test_validate_passes_when_all_required_vars_present` fails because `Config.validate()` still requires `WHATSAPP_GROUP_JID`, which `_set_all` no longer sets.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `config.py` with:

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

    # -- Google Sheets --
    GOOGLE_SHEETS_ID: str = os.getenv("GOOGLE_SHEETS_ID", "")
    GOOGLE_CREDENTIALS_PATH: str = os.getenv(
        "GOOGLE_CREDENTIALS_PATH", "secrets/google-service-account.json"
    )

    # -- OpenAI --
    OPENAI_API_KEY: str = os.getenv("OPENAI_API_KEY", "")

    # -- Logging --
    LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()

    # -- Behavior --
    TIMEZONE: str = os.getenv("TIMEZONE", "America/Bogota")

    @classmethod
    def validate(cls) -> None:
        """Raises ValueError if any required credential/setting is missing."""
        required = {
            "EVOLUTION_API_URL": cls.EVOLUTION_API_URL,
            "EVOLUTION_API_KEY": cls.EVOLUTION_API_KEY,
            "EVOLUTION_INSTANCE": cls.EVOLUTION_INSTANCE,
            "GOOGLE_SHEETS_ID": cls.GOOGLE_SHEETS_ID,
            "OPENAI_API_KEY": cls.OPENAI_API_KEY,
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            raise ValueError(f"Missing required environment variables: {', '.join(missing)}")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_config.py -v`
Expected: PASS (2 tests)

- [ ] **Step 5: Commit**

```bash
git add config.py tests/test_config.py
git commit -m "Remove WHATSAPP_GROUP_JID -- groups are now looked up via GroupRegistry"
```

---

## Task 6: task_handler — GroupRegistry filter + personal-sheet routing

**Files:**
- Modify: `handlers/task_handler.py`
- Test: `tests/test_task_handler.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_task_handler.py` with:

```python
import re

from services.classifier import ClassificationResult, ClassifierError
from handlers.task_handler import handle_webhook_payload

GROUP_JID = "120363429440515454@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"
SENDER_JID = "573001112233@s.whatsapp.net"
ASSIGNEE_JID = "573004445566@s.whatsapp.net"


class FakeRoster:
    def __init__(self, known_jids: dict[str, str], sheet_ids: dict[str, str] | None = None):
        self._known = known_jids
        self._sheet_ids = sheet_ids or {}

    def is_known_sender(self, jid):
        return jid in self._known

    def resolve_name(self, jid):
        return self._known.get(jid)

    def resolve_personal_sheet_id(self, jid):
        return self._sheet_ids.get(jid)

    def same_person(self, jid_a, jid_b):
        return jid_a == jid_b


class FakeLidResolver:
    """Passthrough by default; pass a mapping to simulate real @lid -> phone
    JID resolution."""

    def __init__(self, mapping: dict[str, str] | None = None):
        self._mapping = mapping or {}

    def resolve(self, jid, group_jid):
        return self._mapping.get(jid, jid)


class FakeGroupRegistry:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def get_client_name(self, group_jid):
        return self._mapping.get(group_jid)


class FakePersonalTaskWriter:
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
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: (_ for _ in ()).throw(AssertionError("should not classify")),
    )

    handle_webhook_payload(
        _payload("Cristian revisa el stand"), roster, lid_resolver, group_registry, task_writer
    )

    assert task_writer.appended == []


def test_ignores_message_from_unmapped_group(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    handle_webhook_payload(
        _payload("Cristian revisa el stand", group_jid=OTHER_GROUP_JID),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []


def test_ignores_own_messages(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    handle_webhook_payload(
        _payload("aviso de error", from_me=True), roster, lid_resolver, group_registry, task_writer
    )

    assert task_writer.appended == []


def test_ignores_non_task_message(monkeypatch):
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
            es_tarea=False, descripcion=None, fecha_limite=None
        ),
    )

    handle_webhook_payload(
        _payload("jajaja buenísimo @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []


def test_saves_task_to_assignees_personal_sheet_under_client_tab(monkeypatch):
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
            es_tarea=True, descripcion="Revisar el stand", fecha_limite="2026-07-24"
        ),
    )

    handle_webhook_payload(
        _payload("revisa el stand mañana @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    saved = task_writer.appended[0]
    assert saved["sheet_id"] == "sheet-cristian"
    assert saved["client_tab"] == "clinicachia"
    assert saved["reporter"] == "Ana"
    assert saved["description"] == "Revisar el stand"
    assert saved["due_date"] == "2026-07-24"
    assert saved["status"] == "Pendiente"


def test_resolves_lid_mentions_and_sender_before_matching_roster(monkeypatch):
    """The real-world case that broke in production: WhatsApp sends '@lid'
    identifiers instead of phone JIDs for the sender and for mentions."""
    sender_lid = "151556578083034@lid"
    assignee_lid = "203744859922485@lid"
    roster = FakeRoster(
        {SENDER_JID: "Eduar", ASSIGNEE_JID: "Gustavo"},
        {ASSIGNEE_JID: "sheet-gustavo"},
    )
    lid_resolver = FakeLidResolver({sender_lid: SENDER_JID, assignee_lid: ASSIGNEE_JID})
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )

    handle_webhook_payload(
        _payload(
            "revisa el stand @Gustavo",
            sender_jid=sender_lid,
            mentioned_jids=[assignee_lid],
        ),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    saved = task_writer.appended[0]
    assert saved["reporter"] == "Eduar"
    assert saved["sheet_id"] == "sheet-gustavo"


def test_self_mention_warns_instead_of_saving(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Avisarle a alguien", fecha_limite=None
        ),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.task_handler.send_text_message", lambda group_jid, text: sent.append(text)
    )

    handle_webhook_payload(
        _payload("recuérdame @Ana avisarle a alguien", mentioned_jids=[SENDER_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "no pude identificar a quién asignar" in sent[0].lower()


def test_unresolvable_mention_warns_instead_of_saving(monkeypatch):
    unknown_jid = "573007778899@s.whatsapp.net"
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
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

    handle_webhook_payload(
        _payload("revisa el stand @alguien", mentioned_jids=[unknown_jid]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "no pude identificar a quién asignar" in sent[0].lower()


def test_warns_when_assignee_has_no_personal_sheet_configured(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"})  # no sheet_ids passed
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
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

    handle_webhook_payload(
        _payload("revisa el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "no encontré la hoja personal de cristian" in sent[0].lower()


def test_ignores_messages_with_no_mention_without_calling_classifier(monkeypatch):
    """A mention is required for a message to even be considered a possible
    task -- messages with no '@' at all should never reach the classifier
    (saves an unnecessary OpenAI call) or get saved."""
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: (_ for _ in ()).throw(AssertionError("should not classify")),
    )

    handle_webhook_payload(
        _payload("hay que revisar el stand"), roster, lid_resolver, group_registry, task_writer
    )

    assert task_writer.appended == []


def test_ignores_classifier_errors_without_saving(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    def raise_error(text, date, **kw):
        raise ClassifierError("timeout")

    monkeypatch.setattr("handlers.task_handler.classify_message", raise_error)

    handle_webhook_payload(
        _payload("algo @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []


def test_created_at_and_classifier_date_share_the_same_moment(monkeypatch):
    """created_at (date + time, for the Sheet) and the date passed to the
    classifier (date only, for resolving 'mañana'/'el viernes') must come
    from a single `datetime.now()` call, not two separate ones that could
    disagree across a midnight boundary."""
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    captured = {}

    def fake_classify(text, date, **kw):
        captured["classify_date"] = date
        return ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        )

    monkeypatch.setattr("handlers.task_handler.classify_message", fake_classify)

    handle_webhook_payload(
        _payload("hay que revisar el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    created_at = task_writer.appended[0]["created_at"]
    assert created_at.startswith(captured["classify_date"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", created_at)


def test_today_is_computed_using_configured_timezone(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from config import Config

    monkeypatch.setattr(Config, "TIMEZONE", "Pacific/Kiritimati")
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    captured = {}

    def fake_classify(text, date, **kw):
        captured["classify_date"] = date
        return ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        )

    monkeypatch.setattr("handlers.task_handler.classify_message", fake_classify)

    handle_webhook_payload(
        _payload("hay que revisar el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
    assert captured["classify_date"] == expected


def test_processes_multiple_messages_in_one_payload(monkeypatch):
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
            es_tarea=True, descripcion=text, fecha_limite=None
        ),
    )

    payload = {
        "data": [
            {
                "key": {"remoteJid": GROUP_JID, "participant": SENDER_JID, "fromMe": False},
                "message": {
                    "extendedTextMessage": {
                        "text": "primera tarea @Cristian",
                        "contextInfo": {"mentionedJid": [ASSIGNEE_JID]},
                    }
                },
            },
            {
                "key": {"remoteJid": GROUP_JID, "participant": SENDER_JID, "fromMe": False},
                "message": {
                    "extendedTextMessage": {
                        "text": "segunda tarea @Cristian",
                        "contextInfo": {"mentionedJid": [ASSIGNEE_JID]},
                    }
                },
            },
        ]
    }

    handle_webhook_payload(payload, roster, lid_resolver, group_registry, task_writer)

    assert len(task_writer.appended) == 2
    assert task_writer.appended[0]["description"] == "primera tarea @Cristian"
    assert task_writer.appended[1]["description"] == "segunda tarea @Cristian"


def test_sends_warning_when_sheets_write_fails(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter(fail=True)
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

    handle_webhook_payload(
        _payload("hay que revisar el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(sent) == 1
    assert "no pude guardar" in sent[0].lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_task_handler.py -v`
Expected: FAIL -- `handle_webhook_payload` still has the old `(payload, roster, lid_resolver, sheets_client, group_jid)` signature.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `handlers/task_handler.py` with:

```python
"""
Orchestrates a single incoming webhook message: parse -> filter -> classify
-> resolve assignee -> save to the assignee's personal Sheet (or warn the
group on failure).
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config
from services.classifier import ClassifierError, classify_message
from services.evolution import parse_webhook_payload, send_text_message

logger = logging.getLogger(__name__)


def handle_webhook_payload(
    payload: dict, roster, lid_resolver, group_registry, personal_task_writer
) -> None:
    for message in parse_webhook_payload(payload):
        _handle_message(message, roster, lid_resolver, group_registry, personal_task_writer)


def _handle_message(message, roster, lid_resolver, group_registry, personal_task_writer) -> None:
    if message.from_me:
        return

    client_name = group_registry.get_client_name(message.group_jid)
    if client_name is None:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid, message.group_jid)

    if not roster.is_known_sender(sender_jid):
        return

    if not message.mentioned_jids:
        return

    now = datetime.now(ZoneInfo(Config.TIMEZONE))
    today = now.date().isoformat()

    try:
        result = classify_message(message.text, today)
    except ClassifierError:
        logger.exception("Classifier failed for message from %s", sender_jid)
        return

    if not result.es_tarea:
        return

    assignee_jid = None
    assignee_name = None
    for raw_jid in message.mentioned_jids:
        jid = lid_resolver.resolve(raw_jid, message.group_jid)
        if roster.same_person(jid, sender_jid):
            continue
        name = roster.resolve_name(jid)
        if name:
            assignee_jid = jid
            assignee_name = name
            break

    reporter_name = roster.resolve_name(sender_jid) or sender_jid

    logger.info(
        "Task resolution: raw_sender=%s -> sender=%s (reporter=%s) | "
        "raw_mentions=%s -> assignee=%s (client=%s)",
        message.sender_jid,
        sender_jid,
        reporter_name,
        message.mentioned_jids,
        assignee_name,
        client_name,
    )

    if assignee_jid is None:
        send_text_message(
            message.group_jid,
            "⚠️ No pude identificar a quién asignar esta tarea, no la guardé.",
        )
        return

    sheet_id = roster.resolve_personal_sheet_id(assignee_jid)
    if not sheet_id:
        send_text_message(
            message.group_jid,
            f"⚠️ No encontré la hoja personal de {assignee_name}, avísenle para configurarla.",
        )
        return

    try:
        personal_task_writer.append_task(
            sheet_id=sheet_id,
            client_tab=client_name,
            created_at=now.strftime("%Y-%m-%d %H:%M"),
            reporter=reporter_name,
            description=result.descripcion,
            due_date=result.fecha_limite,
            status="Pendiente",
        )
    except Exception:
        logger.exception("Failed to save task to personal sheet")
        send_text_message(message.group_jid, "⚠️ No pude guardar esta tarea, avísenle a alguien.")
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_task_handler.py -v`
Expected: PASS (15 tests)

- [ ] **Step 5: Commit**

```bash
git add handlers/task_handler.py tests/test_task_handler.py
git commit -m "Route tasks to the assignee's personal Sheet, filtered by GroupRegistry"
```

---

## Task 7: spelling_handler — GroupRegistry filter + group-aware batching

**Files:**
- Modify: `handlers/spelling_handler.py`
- Test: `tests/test_spelling_handler.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_spelling_handler.py` with:

```python
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

    def resolve(self, jid, group_jid):
        return self._mapping.get(jid, jid)


class FakeGroupRegistry:
    def __init__(self, mapping):
        self._mapping = mapping

    def get_client_name(self, group_jid):
        return self._mapping.get(group_jid)


def _payload(caption, sender_jid=SENDER_JID, group_jid=GROUP_JID, from_me=False, base64="aGk="):
    return {
        "data": {
            "key": {"remoteJid": group_jid, "participant": sender_jid, "fromMe": from_me},
            "message": {"imageMessage": {"caption": caption}, "base64": base64},
        }
    }


def _run(payload, roster, lid_resolver, group_registry=None, batch_buffer=None):
    """Runs the handler for a single image with no real waiting -- used by
    tests that don't care about batching multiple images together."""
    handle_webhook_payload(
        payload,
        roster,
        lid_resolver,
        group_registry or FakeGroupRegistry({GROUP_JID: "clinicachia"}),
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


def test_ignores_image_from_unmapped_group(monkeypatch):
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
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
        group_registry,
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
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
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
        group_registry,
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
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})

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
            group_registry,
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
        group_registry,
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
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
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
            group_registry,
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
        group_registry,
        batch_buffer,
        sleep=lambda seconds: None,
    )

    release_first_image.set()
    first_call.join(timeout=2)

    assert sent == []


def test_images_from_the_same_sender_in_different_groups_are_not_batched_together(monkeypatch):
    """The batch key must include the group, not just the sender -- two
    images sent to two different client groups around the same time must
    never be merged into one batch."""
    roster = FakeRoster({SENDER_JID: True})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia", OTHER_GROUP_JID: "optifalcon"})

    reviewed_images = []

    def fake_review(image_base64, mimetype, **kw):
        reviewed_images.append(image_base64)
        return SpellingReviewResult(has_errors=False, details=["Sin errores"])

    monkeypatch.setattr("handlers.spelling_handler.review_spelling", fake_review)
    sent = []
    monkeypatch.setattr(
        "handlers.spelling_handler.send_text_message", lambda g, t: sent.append((g, t))
    )

    batch_buffer = ImageBatchBuffer()
    added_first_image = threading.Event()
    release_first_image = threading.Event()

    def sleep_and_wait_for_sibling(seconds):
        added_first_image.set()
        release_first_image.wait(timeout=2)

    payload_group_a = _payload("revisar ortografia", group_jid=GROUP_JID, base64="aW1hZ2Ux")
    payload_group_b = _payload("revisar ortografia", group_jid=OTHER_GROUP_JID, base64="aW1hZ2Uy")

    first_call = threading.Thread(
        target=handle_webhook_payload,
        args=(
            payload_group_a,
            roster,
            lid_resolver,
            group_registry,
            batch_buffer,
            sleep_and_wait_for_sibling,
        ),
    )
    first_call.start()
    assert added_first_image.wait(timeout=2)

    handle_webhook_payload(
        payload_group_b,
        roster,
        lid_resolver,
        group_registry,
        batch_buffer,
        sleep=lambda seconds: None,
    )

    release_first_image.set()
    first_call.join(timeout=2)

    # Each image was reviewed as its own batch of one -- neither reply is
    # numbered, and each was sent to its own group.
    assert sorted(reviewed_images) == ["aW1hZ2Ux", "aW1hZ2Uy"]
    assert len(sent) == 2
    for group_jid, text in sent:
        assert not text.startswith("Imagen")
    sent_groups = {g for g, _ in sent}
    assert sent_groups == {GROUP_JID, OTHER_GROUP_JID}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_spelling_handler.py -v`
Expected: FAIL -- `handle_webhook_payload` still takes a fixed `group_jid` string instead of a `group_registry`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `handlers/spelling_handler.py` with:

```python
"""
Orchestrates incoming image messages: parse -> filter (group registered,
known sender, not from_me) -> buffer briefly so images sent together in one
WhatsApp multi-image send are grouped -> if any image in the group has a
trigger keyword in its caption, review every image in the group with
OpenAI -> reply in the group once per image, numbered when the group has
more than one image.

WhatsApp delivers a multi-image send as separate messages (often as
separate webhook calls), and typically only one of them carries the
caption text -- the rest arrive with no caption at all. The batch buffer
exists to catch those caption-less siblings instead of silently ignoring
them. Batches are keyed by (sender, group) so images sent to two
different client groups around the same time never mix into one batch.
"""
import logging
import time
import unicodedata

from services.evolution import parse_image_messages, send_text_message
from services.image_batch import ImageBatchBuffer
from services.spelling_reviewer import SpellingReviewError, review_spelling

logger = logging.getLogger(__name__)

_KEYWORDS = ("ortografia", "u56")

# How long to wait after an image arrives to see if sibling images from the
# same sender show up before deciding whether to process the batch.
_BATCH_WINDOW_SECONDS = 4.0


def handle_webhook_payload(
    payload: dict,
    roster,
    lid_resolver,
    group_registry,
    batch_buffer: ImageBatchBuffer,
    sleep=time.sleep,
) -> None:
    for message in parse_image_messages(payload):
        _handle_image_message(message, roster, lid_resolver, group_registry, batch_buffer, sleep)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _has_trigger_keyword(caption: str) -> bool:
    normalized = _normalize(caption)
    return any(keyword in normalized for keyword in _KEYWORDS)


def _handle_image_message(
    message, roster, lid_resolver, group_registry, batch_buffer: ImageBatchBuffer, sleep
) -> None:
    if message.from_me:
        return

    if group_registry.get_client_name(message.group_jid) is None:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid, message.group_jid)

    if not roster.is_known_sender(sender_jid):
        return

    batch_key = (sender_jid, message.group_jid)
    snapshot = batch_buffer.add(batch_key, message)
    sleep(_BATCH_WINDOW_SECONDS)
    batch = batch_buffer.try_claim(batch_key, len(snapshot))
    if batch is None:
        # A later image in the same batch is responsible for processing
        # the whole group -- nothing to do here.
        return

    if not any(_has_trigger_keyword(m.caption) for m in batch):
        return

    total = len(batch)
    for index, image_message in enumerate(batch, start=1):
        _review_and_reply(image_message, index, total)


def _review_and_reply(message, index: int, total: int) -> None:
    try:
        result = review_spelling(message.image_base64, message.mimetype)
    except SpellingReviewError as exc:
        logger.error(
            "Spelling review failed for message from %s: %s",
            message.sender_jid,
            str(exc)[:300],
        )
        return

    if result.has_errors:
        bullets = "\n".join(f"• {item}" for item in result.details)
        body = f"⚠️ Encontré posibles errores de ortografía:\n{bullets}"
    else:
        body = "✅ Ortografía revisada, no encontré errores."

    reply = f"Imagen {index} de {total}:\n{body}" if total > 1 else body

    send_text_message(message.group_jid, reply)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_spelling_handler.py -v`
Expected: PASS (18 tests)

- [ ] **Step 5: Commit**

```bash
git add handlers/spelling_handler.py tests/test_spelling_handler.py
git commit -m "Filter spelling review by GroupRegistry and key batches by (sender, group)"
```

---

## Task 8: main.py — wire GroupRegistry and PersonalTaskWriter

**Files:**
- Modify: `main.py`
- Test: `tests/test_main.py` (rewrite)

- [ ] **Step 1: Write the failing tests**

Replace the full contents of `tests/test_main.py` with:

```python
from fastapi.testclient import TestClient

import main


def _set_common_state():
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    main.app.state.group_registry = "fake-group-registry"
    main.app.state.personal_task_writer = "fake-personal-task-writer"
    main.app.state.image_batch_buffer = "fake-image-batch-buffer"


def test_webhook_delegates_to_both_handlers(monkeypatch):
    task_calls = []
    spelling_calls = []

    def fake_task_handler(payload, roster, lid_resolver, group_registry, personal_task_writer):
        task_calls.append((payload, roster, lid_resolver, group_registry, personal_task_writer))

    def fake_spelling_handler(payload, roster, lid_resolver, group_registry, batch_buffer):
        spelling_calls.append((payload, roster, lid_resolver, group_registry, batch_buffer))

    monkeypatch.setattr(main, "handle_task_payload", fake_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    _set_common_state()

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert task_calls == [
        (body, "fake-roster", "fake-lid-resolver", "fake-group-registry", "fake-personal-task-writer")
    ]
    assert spelling_calls == [
        (body, "fake-roster", "fake-lid-resolver", "fake-group-registry", "fake-image-batch-buffer")
    ]


def test_webhook_returns_200_even_if_task_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, group_registry, personal_task_writer):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", raising_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: None)
    _set_common_state()

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_webhook_returns_200_even_if_spelling_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, group_registry, batch_buffer):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", lambda *a: None)
    monkeypatch.setattr(main, "handle_spelling_payload", raising_handler)
    _set_common_state()

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_spelling_handler_still_runs_when_task_handler_raises(monkeypatch):
    """The two handlers are independent -- one failing must not block the other."""
    spelling_calls = []

    def raising_task_handler(payload, roster, lid_resolver, group_registry, personal_task_writer):
        raise RuntimeError("boom")

    def fake_spelling_handler(payload, roster, lid_resolver, group_registry, batch_buffer):
        spelling_calls.append(payload)

    monkeypatch.setattr(main, "handle_task_payload", raising_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    _set_common_state()

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
    _set_common_state()

    client = TestClient(main.app)
    response = client.post(
        "/webhook", content=b"not-json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200
    assert task_calls == []
    assert spelling_calls == []


def test_handlers_are_dispatched_via_threadpool(monkeypatch):
    """Handlers do blocking I/O (OpenAI, Sheets, Evolution) -- they must run
    off the event loop via run_in_threadpool, not be called directly."""
    dispatched_funcs = []

    async def fake_run_in_threadpool(func, *args):
        dispatched_funcs.append(func)
        return func(*args)

    monkeypatch.setattr(main, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(main, "handle_task_payload", lambda *a: None)
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: None)
    _set_common_state()

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200
    assert main.handle_task_payload in dispatched_funcs
    assert main.handle_spelling_payload in dispatched_funcs
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest tests/test_main.py -v`
Expected: FAIL -- `main.py` still dispatches with the old fixed `Config.WHATSAPP_GROUP_JID` argument and doesn't have `app.state.group_registry` / `app.state.personal_task_writer`.

- [ ] **Step 3: Write the implementation**

Replace the full contents of `main.py` with:

```python
"""
FastAPI app: receives Evolution API webhooks and hands each message to the
task handler and the spelling-review handler. Google Sheets / roster clients
are created lazily on startup so importing this module has no side effects
(needed for testing). Handlers run in a thread pool (not directly on the
event loop) since they do blocking network I/O (OpenAI, Google Sheets,
Evolution API).
"""
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from starlette.concurrency import run_in_threadpool

from config import Config
from handlers.spelling_handler import handle_webhook_payload as handle_spelling_payload
from handlers.task_handler import handle_webhook_payload as handle_task_payload
from services.group_registry import GroupRegistry
from services.image_batch import ImageBatchBuffer
from services.lid_resolver import LidResolver
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

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_main.py -v`
Expected: PASS (6 tests)

- [ ] **Step 5: Run the full test suite**

Run: `pytest -v`
Expected: PASS -- every test in the project, across all files touched in Tasks 1-8.

- [ ] **Step 6: Commit**

```bash
git add main.py tests/test_main.py
git commit -m "Wire GroupRegistry and PersonalTaskWriter into the webhook route"
```

---

## Task 9: Documentation — .env.example and README

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

- [ ] **Step 1: Update `.env.example`**

Replace the full contents of `.env.example` with:

```
# Evolution API (WhatsApp)
EVOLUTION_API_URL=
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=

# Google Sheets (central config spreadsheet: Equipo + Grupos tabs)
GOOGLE_SHEETS_ID=
GOOGLE_CREDENTIALS_PATH=secrets/google-service-account.json

# OpenAI
OPENAI_API_KEY=

# Logging
LOG_LEVEL=INFO

# Timezone for date calculations (task due dates, creation dates)
TIMEZONE=America/Bogota
```

- [ ] **Step 2: Update `README.md`**

Replace the full contents of `README.md` with:

```markdown
# bot-tareas-whatsapp

Bot de WhatsApp con dos funciones, en varios grupos (uno por cliente):
1. Vigila cada grupo, detecta cuándo alguien agenda una tarea (mencionando a alguien con `@`), y la
   registra en el Google Sheet personal de esa persona, en la pestaña del cliente correspondiente.
   Ver `docs/superpowers/specs/2026-07-23-task-bot-whatsapp-design.md` y
   `docs/superpowers/specs/2026-08-06-multi-client-task-routing-design.md`.
2. Cuando alguien del equipo manda una imagen con la palabra "ortografía" (o el código "u56") en el
   texto, revisa la ortografía en español de la imagen con OpenAI y responde en el grupo. Ver
   `docs/superpowers/specs/2026-08-05-image-spelling-review-design.md`.

## Setup

1. `pip install -r requirements.txt`
2. Copiar `.env.example` a `.env` y completar las credenciales (Evolution API, Google Sheets,
   OpenAI).
3. Colocar el JSON de la service account de Google en la ruta indicada por
   `GOOGLE_CREDENTIALS_PATH` (por defecto `secrets/google-service-account.json`).
4. Crear el Google Sheet **central de configuración** (el que apunta `GOOGLE_SHEETS_ID`) con dos
   pestañas:
   - **Equipo**: columnas `Nombre | Numero | Sheet ID` (número sin `+` ni espacios, ej.
     `573001112233`; el Sheet ID es el de la hoja personal de esa persona -- se puede dejar vacío
     hasta que la tenga lista, el bot avisará en el grupo si falta).
   - **Grupos**: columnas `Grupo | Cliente | Nombre del grupo` (el JID del grupo de WhatsApp, el
     nombre del cliente que se usará como nombre de pestaña, y un tercer campo libre solo para tu
     referencia).
5. Por cada integrante del equipo: crear (o usar) su Google Sheet personal, **compartirlo con el
   correo de la cuenta de servicio** (el mismo JSON de `GOOGLE_CREDENTIALS_PATH`) con permiso de
   Editor, y poner su ID en la columna "Sheet ID" de "Equipo". Las pestañas por cliente se crean
   automáticamente la primera vez que se le asigna una tarea de ese cliente -- no hay que crearlas
   a mano.
6. Agregar el bot a cada grupo de WhatsApp de cliente, y agregar una fila en "Grupos" por cada uno.
7. Configurar el webhook de Evolution API para que apunte a `POST /webhook` de este servicio, con
   el evento `MESSAGES_UPSERT` activado.
8. Activar **"Webhook Base64"** en esa misma configuración del webhook -- sin esto, la revisión de
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

- [ ] **Step 3: Commit**

```bash
git add .env.example README.md
git commit -m "Document multi-group setup: Grupos tab, personal Sheet IDs, sharing requirement"
```
