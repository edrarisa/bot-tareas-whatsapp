"""
Orchestrates a single incoming image message: parse -> filter (group, known
sender, keyword in caption) -> review spelling with OpenAI -> always reply
in the group with the result.
"""
import logging
import unicodedata

from services.evolution import parse_image_messages, send_text_message
from services.spelling_reviewer import SpellingReviewError, review_spelling

logger = logging.getLogger(__name__)

_KEYWORD = "ortografia"


def handle_webhook_payload(payload: dict, roster, lid_resolver, group_jid: str) -> None:
    for message in parse_image_messages(payload):
        _handle_image_message(message, roster, lid_resolver, group_jid)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _handle_image_message(message, roster, lid_resolver, group_jid: str) -> None:
    if message.from_me or message.group_jid != group_jid:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid)

    if not roster.is_known_sender(sender_jid):
        return

    if _KEYWORD not in _normalize(message.caption):
        return

    try:
        result = review_spelling(message.image_base64, message.mimetype)
    except SpellingReviewError as exc:
        logger.error(
            "Spelling review failed for message from %s: %s", sender_jid, str(exc)[:300]
        )
        return

    if result.has_errors:
        reply = f"⚠️ Encontré posibles errores de ortografía: {result.details}"
    else:
        reply = "✅ Ortografía revisada, no encontré errores."

    send_text_message(group_jid, reply)
