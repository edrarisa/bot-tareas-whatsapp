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
        self._by_phone: dict[str, str] = {}
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
        self._by_phone = {self._normalize(number): name for name, number in rows}
        self._loaded_at = now

    @staticmethod
    def _normalize(value: str) -> str:
        return "".join(ch for ch in value if ch.isdigit())

    @staticmethod
    def _phone_from_jid(jid: str) -> str:
        return jid.split("@", 1)[0]

    def is_known_sender(self, jid: str) -> bool:
        self._ensure_loaded()
        return self._normalize(self._phone_from_jid(jid)) in self._by_phone

    def resolve_name(self, jid: str) -> str | None:
        self._ensure_loaded()
        return self._by_phone.get(self._normalize(self._phone_from_jid(jid)))
