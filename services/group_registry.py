"""
Resolves WhatsApp group JIDs to a client name via the "Grupos" tab, caching
in memory for a short TTL (same pattern as Roster) so the bot supports
several groups -- one per client -- without hitting the Sheets API on every
message.
"""
import logging
import time

logger = logging.getLogger(__name__)


class GroupRegistry:
    def __init__(self, sheets_client, ttl_seconds: int = 300, time_func=time.monotonic):
        self._sheets_client = sheets_client
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._by_group: dict[str, str] = {}
        self._loaded_at: float = float("-inf")

    def _ensure_loaded(self) -> None:
        now = self._time_func()
        if self._loaded_at != float("-inf") and now - self._loaded_at <= self._ttl_seconds:
            return
        try:
            rows = self._sheets_client.read_group_mapping()
        except Exception:
            if self._loaded_at == float("-inf"):
                raise
            logger.warning("Failed to refresh group mapping, using stale cache", exc_info=True)
            return
        by_group: dict[str, str] = {}
        for group_jid, client_name in rows:
            existing = by_group.get(group_jid)
            if existing is not None and existing != client_name:
                logger.warning(
                    "Duplicate group %s in Grupos tab with conflicting client names "
                    "(%r and %r) -- using %r",
                    group_jid,
                    existing,
                    client_name,
                    client_name,
                )
            by_group[group_jid] = client_name
        self._by_group = by_group
        self._loaded_at = now

    def get_client_name(self, group_jid: str) -> str | None:
        self._ensure_loaded()
        return self._by_group.get(group_jid)
