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


def test_read_team_roster_skips_rows_with_blank_number():
    equipo = FakeWorksheet(
        values=[
            ["Nombre", "Numero"],
            ["Cristian", "573001112233"],
            ["Ana", ""],
            ["   ", "573004445566"],
            ["Pablo", "   "],
        ]
    )
    client = SheetsClient(FakeSpreadsheet({"Equipo": equipo}))

    roster = client.read_team_roster()

    assert roster == [("Cristian", "573001112233")]
