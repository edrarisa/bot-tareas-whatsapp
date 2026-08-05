"""
Resolves WhatsApp's privacy LIDs (opaque "@lid" identifiers) back to the
real phone-number JID, by querying Evolution API's group participants
endpoint. WhatsApp increasingly sends "@lid" identifiers instead of phone
numbers for message senders and mentions, so this sits in front of Roster
lookups to translate them back to something Roster can match.
"""
import logging
import time

import requests

from config import Config

logger = logging.getLogger(__name__)


class LidResolver:
    def __init__(self, group_jid: str, ttl_seconds: int = 300, time_func=time.monotonic):
        self._group_jid = group_jid
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._lid_to_phone_jid: dict[str, str] = {}
        self._loaded_at: float = float("-inf")

    def resolve(self, jid: str) -> str:
        """Returns the real phone-number JID for a "@lid" identifier.

        Returns the input unchanged if it isn't a "@lid" JID, or if it can't
        be resolved (e.g. the participant's number is itself hidden).
        """
        if not jid.endswith("@lid"):
            return jid
        self._ensure_loaded()
        resolved = self._lid_to_phone_jid.get(jid, jid)
        logger.info(
            "LID resolve: %s -> %s (%d entries in map)",
            jid,
            resolved,
            len(self._lid_to_phone_jid),
        )
        return resolved

    def _ensure_loaded(self) -> None:
        now = self._time_func()
        if self._loaded_at != float("-inf") and now - self._loaded_at <= self._ttl_seconds:
            return
        try:
            participants = self._fetch_participants()
        except Exception:
            logger.warning("Failed to fetch group participants for LID mapping", exc_info=True)
            if self._loaded_at == float("-inf"):
                raise
            logger.warning("Failed to refresh LID mapping, using stale cache", exc_info=True)
            return
        self._lid_to_phone_jid = {
            p["id"]: p["phoneNumber"]
            for p in participants
            if p.get("id") and p.get("phoneNumber")
        }
        self._loaded_at = now
        logger.info(
            "Loaded LID mapping: %d participants, %d with a resolvable phone number",
            len(participants),
            len(self._lid_to_phone_jid),
        )

    def _fetch_participants(self) -> list[dict]:
        url = f"{Config.EVOLUTION_API_URL.rstrip('/')}/group/participants/{Config.EVOLUTION_INSTANCE}"
        headers = {"apikey": Config.EVOLUTION_API_KEY}
        response = requests.get(
            url, headers=headers, params={"groupJid": self._group_jid}, timeout=30
        )
        logger.info("Group participants fetch: HTTP %s, body: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()
        return data.get("participants", data if isinstance(data, list) else [])
