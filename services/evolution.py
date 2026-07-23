"""
Evolution API integration: parses incoming webhook payloads and sends
outgoing messages back to the group.
"""
import logging
from dataclasses import dataclass

import requests

from config import Config

logger = logging.getLogger(__name__)


@dataclass
class IncomingMessage:
    group_jid: str
    sender_jid: str
    text: str
    mentioned_jids: list[str]
    from_me: bool


def parse_webhook_payload(payload: dict) -> IncomingMessage | None:
    """Returns None when the payload isn't a parseable text message."""
    data = payload.get("data")
    if not data:
        return None

    key = data.get("key") or {}
    group_jid = key.get("remoteJid")
    if not group_jid:
        return None

    sender_jid = key.get("participant") or group_jid
    from_me = bool(key.get("fromMe", False))

    message = data.get("message") or {}
    text = message.get("conversation")
    mentioned_jids: list[str] = []
    if text is None:
        extended = message.get("extendedTextMessage") or {}
        text = extended.get("text")
        mentioned_jids = (extended.get("contextInfo") or {}).get("mentionedJid") or []

    if not text:
        return None

    return IncomingMessage(
        group_jid=group_jid,
        sender_jid=sender_jid,
        text=text,
        mentioned_jids=mentioned_jids,
        from_me=from_me,
    )


def send_text_message(group_jid: str, text: str) -> None:
    """Sends a text message to a group JID via Evolution API."""
    url = f"{Config.EVOLUTION_API_URL.rstrip('/')}/message/sendText/{Config.EVOLUTION_INSTANCE}"
    headers = {"apikey": Config.EVOLUTION_API_KEY, "Content-Type": "application/json"}
    payload = {"number": group_jid, "text": text}
    response = requests.post(url, headers=headers, json=payload, timeout=30)
    if not response.ok:
        logger.error(f"Evolution API error: {response.status_code} — {response.text}")
        response.raise_for_status()
