"""
Orchestrates incoming image messages: parse -> filter (group, known
sender, not from_me) -> buffer briefly so images sent together in one
WhatsApp multi-image send are grouped -> if any image in the group has
the "ortografia" keyword in its caption, review every image in the group
with OpenAI -> reply in the group once per image.

WhatsApp delivers a multi-image send as separate messages (often as
separate webhook calls), and typically only one of them carries the
caption text -- the rest arrive with no caption at all. The batch buffer
exists to catch those caption-less siblings instead of silently ignoring
them.
"""
import logging
import time
import unicodedata

from services.evolution import parse_image_messages, send_text_message
from services.image_batch import ImageBatchBuffer
from services.spelling_reviewer import SpellingReviewError, review_spelling

logger = logging.getLogger(__name__)

_KEYWORD = "ortografia"

# How long to wait after an image arrives to see if sibling images from the
# same sender show up before deciding whether to process the batch.
_BATCH_WINDOW_SECONDS = 4.0


def handle_webhook_payload(
    payload: dict,
    roster,
    lid_resolver,
    group_jid: str,
    batch_buffer: ImageBatchBuffer,
    sleep=time.sleep,
) -> None:
    for message in parse_image_messages(payload):
        _handle_image_message(message, roster, lid_resolver, group_jid, batch_buffer, sleep)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _handle_image_message(
    message, roster, lid_resolver, group_jid: str, batch_buffer: ImageBatchBuffer, sleep
) -> None:
    if message.from_me or message.group_jid != group_jid:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid)

    if not roster.is_known_sender(sender_jid):
        return

    snapshot = batch_buffer.add(sender_jid, message)
    sleep(_BATCH_WINDOW_SECONDS)
    batch = batch_buffer.try_claim(sender_jid, len(snapshot))
    if batch is None:
        # A later image in the same batch is responsible for processing
        # the whole group -- nothing to do here.
        return

    if not any(_KEYWORD in _normalize(m.caption) for m in batch):
        return

    for image_message in batch:
        _review_and_reply(image_message, group_jid)


def _review_and_reply(message, group_jid: str) -> None:
    try:
        result = review_spelling(message.image_base64, message.mimetype)
    except SpellingReviewError as exc:
        logger.error(
            "Spelling review failed for message from %s: %s",
            message.sender_jid,
            str(exc)[:300],
        )
        return

    if result.has_errors:
        bullets = "\n".join(f"• {item}" for item in result.details)
        reply = f"⚠️ Encontré posibles errores de ortografía:\n{bullets}"
    else:
        reply = "✅ Ortografía revisada, no encontré errores."

    send_text_message(group_jid, reply)
