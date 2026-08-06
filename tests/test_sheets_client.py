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
