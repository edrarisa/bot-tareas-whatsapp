"""
Scans every team member's personal Google Sheet for urgent, incomplete
tasks and sends a WhatsApp reminder to their personal number at noon and
5pm on weekdays, respecting a 2-hour grace period after the task was
created. Already-sent alerts are tracked in the Sheet itself (the
"Alerta 12pm" / "Alerta 5pm" columns hold the date and time they were last
sent), so restarting the bot never duplicates or loses an alert.
"""
import logging
import os
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from config import Config

logger = logging.getLogger(__name__)

_URGENT_YES = "Sí"
_STATUS_COMPLETED = "Completada"
# Overridable via env vars for testing in production without touching code
# or breaking the test suite (which relies on these defaults). Unset in
# normal operation -- defaults match the design spec (2h grace period,
# noon/5pm windows).
_MIN_MINUTES_SINCE_CREATION = float(os.getenv("REMINDER_MIN_MINUTES_SINCE_CREATION", "120"))
_NOON_HOUR = int(os.getenv("REMINDER_NOON_HOUR", "12"))
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
        logger.info(
            "Reminder check starting: now=%s weekday=%s min_minutes_since_creation=%s noon_hour=%s",
            now.isoformat(),
            now.weekday(),
            _MIN_MINUTES_SINCE_CREATION,
            _NOON_HOUR,
        )
        if now.weekday() >= 5:
            logger.info("Reminder check skipped: it's the weekend")
            return

        noon_open = now.hour >= _NOON_HOUR
        if not noon_open:
            logger.info(
                "Reminder check skipped: hour %s is before the noon window (%s)", now.hour, _NOON_HOUR
            )
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

        raw_fecha = row[_COL_FECHA] if row else ""
        created_at = self._parse_created_at(raw_fecha)
        if created_at is None:
            logger.warning(
                "Unparseable task creation date %r for client %s, row %s; skipping row",
                raw_fecha,
                client_name,
                row_number,
            )
            return
        if now - created_at < timedelta(minutes=_MIN_MINUTES_SINCE_CREATION):
            return

        today_str = now.date().isoformat()
        sent_at_str = now.strftime("%Y-%m-%d %H:%M")
        description = row[_COL_DESCRIPCION] if len(row) > _COL_DESCRIPCION else ""

        # Compare by date prefix (not exact equality) since the cell stores a
        # full "YYYY-MM-DD HH:MM" timestamp, not just a date -- this also
        # keeps already-sent rows written before this change (date-only)
        # working correctly.
        alerta_12pm = row[_COL_ALERTA_12PM] if len(row) > _COL_ALERTA_12PM else ""
        if noon_open and not alerta_12pm.startswith(today_str):
            self._send_and_mark(
                worksheet, row_number, _COL_ALERTA_12PM, phone_jid, client_name, description, sent_at_str
            )

        alerta_5pm = row[_COL_ALERTA_5PM] if len(row) > _COL_ALERTA_5PM else ""
        if five_pm_open and not alerta_5pm.startswith(today_str):
            self._send_and_mark(
                worksheet, row_number, _COL_ALERTA_5PM, phone_jid, client_name, description, sent_at_str
            )

    def _send_and_mark(
        self, worksheet, row_number, alert_col, phone_jid, client_name, description, sent_at_str
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
        logger.info(
            "Sent urgent-task reminder to %s for client %s (row %s)", phone_jid, client_name, row_number
        )
        try:
            worksheet.update_cell(row_number, alert_col + 1, sent_at_str)
        except Exception:
            logger.exception(
                "Reminder sent to %s but failed to mark row %s as sent at %s; "
                "a duplicate reminder may be sent next cycle",
                phone_jid,
                row_number,
                sent_at_str,
            )

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
