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
    assert worksheet.update_cell_calls == [(2, 8, "2026-08-10 12:30")]


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
    assert worksheet.update_cell_calls == [(2, 8, "2026-08-11 12:30")]


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
    assert worksheet.update_cell_calls == [(2, 9, "2026-08-10 17:30")]


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


class RaisingUpdateCellWorksheet(FakeWorksheet):
    def update_cell(self, row, col, value):
        raise RuntimeError("sheets api rate limited")


def test_does_not_crash_when_marking_as_sent_fails():
    worksheet = RaisingUpdateCellWorksheet("clinicachia", [_HEADERS, _row(fecha="2026-08-10 08:00")])
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
