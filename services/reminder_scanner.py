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
