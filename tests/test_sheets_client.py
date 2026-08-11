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
            ["Nombre", "Numero", "Sheet ID", "Sheet drive"],
            [
                "Cristian",
                "573001112233",
                "sheet-cristian",
                "https://docs.google.com/spreadsheets/d/sheet-cristian",
            ],
            ["Ana", "573004445566", "sheet-ana", "https://docs.google.com/spreadsheets/d/sheet-ana"],
            [""],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [
        (
            "Cristian",
            "573001112233",
            "sheet-cristian",
            "https://docs.google.com/spreadsheets/d/sheet-cristian",
        ),
        ("Ana", "573004445566", "sheet-ana", "https://docs.google.com/spreadsheets/d/sheet-ana"),
    ]


def test_read_team_roster_skips_rows_with_blank_number():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero", "Sheet ID", "Sheet drive"],
            [
                "Cristian",
                "573001112233",
                "sheet-cristian",
                "https://docs.google.com/spreadsheets/d/sheet-cristian",
            ],
            ["Ana", "", "sheet-ana", "https://docs.google.com/spreadsheets/d/sheet-ana"],
            ["   ", "573004445566", "sheet-x", "https://docs.google.com/spreadsheets/d/sheet-x"],
            ["Pablo", "   ", "sheet-pablo", "https://docs.google.com/spreadsheets/d/sheet-pablo"],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [
        (
            "Cristian",
            "573001112233",
            "sheet-cristian",
            "https://docs.google.com/spreadsheets/d/sheet-cristian",
        )
    ]


def test_read_team_roster_tolerates_missing_sheet_id_column():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero"],
            ["Cristian", "573001112233"],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [("Cristian", "573001112233", "", "")]


def test_read_team_roster_tolerates_missing_sheet_drive_column():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero", "Sheet ID"],
            ["Cristian", "573001112233", "sheet-cristian"],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [("Cristian", "573001112233", "sheet-cristian", "")]


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
