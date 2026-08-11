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
            self._normalize(row[1]): (row[0], row[2] if len(row) > 2 else "") for row in rows
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
