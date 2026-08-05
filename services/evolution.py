"""
Evolution API integration: parses incoming webhook payloads and sends
outgoing messages back to the group.
"""
import logging
import re
from dataclasses import dataclass

import requests

from config import Config

logger = logging.getLogger(__name__)

# Fallback for messages where WhatsApp/Evolution didn't attach structured
# mention metadata (contextInfo.mentionedJid) even though the message text
# visibly contains an "@<number>" tag -- this happens for some plain
# "conversation" messages. Matched numbers are treated as "@lid" candidates;
# Roster matches purely on the digits before "@", so this works whether the
# number turns out to be a real LID or already a phone number.
_TEXT_MENTION_PATTERN = re.compile(r"(?:^|\s)@(\d{5,20})")


@dataclass
class IncomingMessage:
    group_jid: str
    sender_jid: str
    text: str
    mentioned_jids: list[str]
    from_me: bool


@dataclass
class IncomingImageMessage:
    group_jid: str
    sender_jid: str
    caption: str
    image_base64: str
    mimetype: str
    from_me: bool


def parse_webhook_payload(payload: dict) -> list[IncomingMessage]:
    """Returns the parseable text messages found in the payload (possibly empty).

    Evolution API's "data" field is sometimes a single message object and
    sometimes a list of them (e.g. when several messages arrive in one
    MESSAGES_UPSERT call) -- both shapes are handled here.
    """
    data = payload.get("data")
    if not data:
        logger.info("Ignoring webhook payload with no 'data' field")
        return []

    items = data if isinstance(data, list) else [data]

    messages = []
    for item in items:
        message = _parse_message_item(item)
        if message is not None:
            messages.append(message)
    return messages


def _parse_message_item(item: dict) -> IncomingMessage | None:
    key = item.get("key") or {}
    group_jid = key.get("remoteJid")
    if not group_jid:
        logger.info("Ignoring webhook payload with no 'remoteJid'. Raw item: %s", repr(item)[:800])
        return None

    sender_jid = key.get("participant") or group_jid
    from_me = bool(key.get("fromMe", False))

    message = item.get("message") or {}
    text = message.get("conversation")
    mentioned_jids: list[str] = []
    if text is None:
        extended = message.get("extendedTextMessage") or {}
        text = extended.get("text")
        mentioned_jids = (extended.get("contextInfo") or {}).get("mentionedJid") or []

    if not text:
        logger.info("Ignoring webhook payload with no text content. Raw item: %s", repr(item)[:800])
        return None

    if not mentioned_jids:
        mentioned_jids = [f"{digits}@lid" for digits in _TEXT_MENTION_PATTERN.findall(text)]

    logger.info("Parsed message. Raw 'message' object: %s", repr(message)[:800])

    return IncomingMessage(
        group_jid=group_jid,
        sender_jid=sender_jid,
        text=text,
        mentioned_jids=mentioned_jids,
        from_me=from_me,
    )


def parse_image_messages(payload: dict) -> list[IncomingImageMessage]:
    """Returns the parseable image messages found in the payload (possibly empty).

    Requires the Evolution API instance to have "Webhook Base64" enabled, so
    the image content arrives directly in the payload as a "base64" field --
    without it, there is nothing here to send to the spelling reviewer.
    """
    data = payload.get("data")
    if not data:
        return []

    items = data if isinstance(data, list) else [data]

    messages = []
    for item in items:
        message = _parse_image_item(item)
        if message is not None:
            messages.append(message)
    return messages


def _parse_image_item(item: dict) -> IncomingImageMessage | None:
    key = item.get("key") or {}
    group_jid = key.get("remoteJid")
    if not group_jid:
        return None

    message = item.get("message") or {}
    image_message = message.get("imageMessage")
    if image_message is None:
        return None

    image_base64 = item.get("base64")
    if not image_base64:
        logger.info(
            "Ignoring image message with no base64 content -- check that "
            "'Webhook Base64' is enabled on the Evolution API instance. Raw item: %s",
            repr(item)[:800],
        )
        return None

    sender_jid = key.get("participant") or group_jid
    from_me = bool(key.get("fromMe", False))
    caption = image_message.get("caption") or ""
    mimetype = image_message.get("mimetype") or "image/jpeg"

    return IncomingImageMessage(
        group_jid=group_jid,
        sender_jid=sender_jid,
        caption=caption,
        image_base64=image_base64,
        mimetype=mimetype,
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
