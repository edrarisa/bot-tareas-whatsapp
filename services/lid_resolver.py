"""
Resolves WhatsApp's privacy LIDs (opaque "@lid" identifiers) back to the
real phone-number JID, by querying Evolution API's group participants
endpoint. WhatsApp increasingly sends "@lid" identifiers instead of phone
numbers for message senders and mentions, so this sits in front of Roster
lookups to translate them back to something Roster can match.

Caches participants per group, since the bot can be in more than one group
at a time -- each group has its own participant list and its own TTL.
"""
import logging
import time

import requests

from config import Config

logger = logging.getLogger(__name__)


class LidResolver:
    def __init__(self, ttl_seconds: int = 300, time_func=time.monotonic):
        self._ttl_seconds = ttl_seconds
        self._time_func = time_func
        self._lid_to_phone_jid: dict[str, dict[str, str]] = {}
        self._loaded_at: dict[str, float] = {}

    def resolve(self, jid: str, group_jid: str) -> str:
        """Returns the real phone-number JID for a "@lid" identifier.

        Returns the input unchanged if it isn't a "@lid" JID, or if it
        can't be resolved (e.g. the participant's number is itself
        hidden).
        """
        if not jid.endswith("@lid"):
            return jid
        self._ensure_loaded(group_jid)
        mapping = self._lid_to_phone_jid.get(group_jid, {})
        resolved = mapping.get(jid, jid)
        logger.info(
            "LID resolve: %s -> %s (%d entries in map for %s)",
            jid,
            resolved,
            len(mapping),
            group_jid,
        )
        return resolved

    def _ensure_loaded(self, group_jid: str) -> None:
        now = self._time_func()
        loaded_at = self._loaded_at.get(group_jid, float("-inf"))
        if loaded_at != float("-inf") and now - loaded_at <= self._ttl_seconds:
            return
        try:
            participants = self._fetch_participants(group_jid)
        except Exception:
            logger.warning("Failed to fetch group participants for LID mapping", exc_info=True)
            if loaded_at == float("-inf"):
                raise
            logger.warning("Failed to refresh LID mapping, using stale cache", exc_info=True)
            return
        self._lid_to_phone_jid[group_jid] = {
            p["id"]: p["phoneNumber"]
            for p in participants
            if p.get("id") and p.get("phoneNumber")
        }
        self._loaded_at[group_jid] = now
        logger.info(
            "Loaded LID mapping for %s: %d participants, %d with a resolvable phone number",
            group_jid,
            len(participants),
            len(self._lid_to_phone_jid[group_jid]),
        )

    def _fetch_participants(self, group_jid: str) -> list[dict]:
        url = f"{Config.EVOLUTION_API_URL.rstrip('/')}/group/participants/{Config.EVOLUTION_INSTANCE}"
        headers = {"apikey": Config.EVOLUTION_API_KEY}
        response = requests.get(
            url, headers=headers, params={"groupJid": group_jid}, timeout=30
        )
        logger.info("Group participants fetch: HTTP %s, body: %s", response.status_code, response.text[:500])
        response.raise_for_status()
        data = response.json()
        return data.get("participants", data if isinstance(data, list) else [])
