"""
Thin wrapper over gspread. `SheetsClient` reads the shared "Equipo" and
"Grupos" tabs from the central config spreadsheet. `PersonalTaskWriter`
writes tasks to each team member's own personal spreadsheet, creating the
client's tab automatically the first time a task is logged for it. Both
take already-open gspread objects so they can be unit-tested without a
live Google Sheets connection.
"""
from gspread.exceptions import WorksheetNotFound
from gspread.utils import ValidationConditionType, a1_range_to_grid_range


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


_STATUS_OPTIONS = ["Pendiente", "En progreso", "Completada"]
_STATUS_COLORS = {
    "Pendiente": {"red": 0.99, "green": 0.76, "blue": 0.42},
    "En progreso": {"red": 0.68, "green": 0.85, "blue": 0.98},
    "Completada": {"red": 0.72, "green": 0.89, "blue": 0.72},
}
_STATUS_COLUMN_RANGE = "E2:E100"


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
            self._apply_status_dropdown(worksheet)
        worksheet.append_row([created_at, reporter, description, due_date or "", status])

    @staticmethod
    def _apply_status_dropdown(worksheet) -> None:
        """Turns the "Estado" column into a colored dropdown (data
        validation + one conditional format rule per status) on a freshly
        created client tab, so status looks the same as the rest of the
        team's Sheets without anyone having to set it up by hand."""
        worksheet.add_validation(
            _STATUS_COLUMN_RANGE,
            ValidationConditionType.one_of_list,
            _STATUS_OPTIONS,
            showCustomUi=True,
        )
        grid_range = a1_range_to_grid_range(_STATUS_COLUMN_RANGE, worksheet.id)
        requests = [
            {
                "addConditionalFormatRule": {
                    "rule": {
                        "ranges": [grid_range],
                        "booleanRule": {
                            "condition": {
                                "type": ValidationConditionType.text_eq.value,
                                "values": [{"userEnteredValue": status}],
                            },
                            "format": {"backgroundColor": color},
                        },
                    },
                    "index": index,
                }
            }
            for index, (status, color) in enumerate(_STATUS_COLORS.items())
        ]
        worksheet.spreadsheet.batch_update({"requests": requests})


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
