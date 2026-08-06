"""
Buffers image messages arriving in quick succession from the same sender,
so a single "ortografia" keyword anywhere in a WhatsApp multi-image send
triggers review of every image in that send -- not just the one that
happened to carry the caption.
"""
import threading


class ImageBatchBuffer:
    """Thread-safe buffer keyed by sender.

    Each caller appends its message via `add` and gets back a snapshot of
    the batch so far. After waiting a short debounce window, the caller
    calls `try_claim` with the length of its snapshot: if the batch is
    still that same length (nothing else was added meanwhile), it "wins"
    and claims (pops) the whole batch for processing. Otherwise a later
    caller -- whose own snapshot is longer -- will claim it instead.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self._batches: dict[str, list] = {}

    def add(self, key: str, message) -> list:
        with self._lock:
            batch = self._batches.setdefault(key, [])
            batch.append(message)
            return list(batch)

    def try_claim(self, key: str, expected_length: int) -> list | None:
        with self._lock:
            batch = self._batches.get(key)
            if batch is None or len(batch) != expected_length:
                return None
            return self._batches.pop(key)
