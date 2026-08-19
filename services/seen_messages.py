"""
Tracks recently-seen WhatsApp message IDs so a webhook redelivery (e.g. a
retry from Evolution API when a slow request wasn't acknowledged in time)
doesn't get reprocessed as if it were a brand new message.
"""
import time


class SeenMessageTracker:
    def __init__(self, ttl_seconds: int = 600, time_func=time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._seen_at: dict[str, float] = {}

    def mark_if_new(self, message_id: str) -> bool:
        """Returns True the first time `message_id` is seen (and records
        it); False on any later call within the TTL window."""
        now = self._time_func()
        self._evict_expired(now)
        if message_id in self._seen_at:
            return False
        self._seen_at[message_id] = now
        return True

    def _evict_expired(self, now: float) -> None:
        expired = [mid for mid, seen_at in self._seen_at.items() if now - seen_at > self._ttl_seconds]
        for mid in expired:
            del self._seen_at[mid]
