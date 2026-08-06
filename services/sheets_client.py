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
