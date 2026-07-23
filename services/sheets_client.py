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
        return [
            (row[0], row[1])
            for row in rows
            if len(row) >= 2 and row[0].strip() and row[1].strip()
        ]

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
