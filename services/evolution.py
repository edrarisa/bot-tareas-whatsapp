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
