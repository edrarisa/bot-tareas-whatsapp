"""
Orchestrates incoming image messages: parse -> filter (group registered,
known sender, not from_me) -> buffer briefly so images sent together in one
WhatsApp multi-image send are grouped -> if any image in the group has a
trigger keyword in its caption, review every image in the group with
OpenAI -> reply in the group once per image, numbered when the group has
more than one image.

WhatsApp delivers a multi-image send as separate messages (often as
separate webhook calls), and typically only one of them carries the
caption text -- the rest arrive with no caption at all. The batch buffer
exists to catch those caption-less siblings instead of silently ignoring
them. Batches are keyed by (sender, group) so images sent to two
different client groups around the same time never mix into one batch.
"""
import logging
import time
import unicodedata

from services.evolution import parse_image_messages, send_text_message
from services.image_batch import ImageBatchBuffer
from services.spelling_reviewer import SpellingReviewError, review_spelling

logger = logging.getLogger(__name__)

_KEYWORDS = ("ortografia", "u56")

# How long to wait after an image arrives to see if sibling images from the
# same sender show up before deciding whether to process the batch.
_BATCH_WINDOW_SECONDS = 4.0


def handle_webhook_payload(
    payload: dict,
    roster,
    lid_resolver,
    group_registry,
    batch_buffer: ImageBatchBuffer,
    sleep=time.sleep,
) -> None:
    for message in parse_image_messages(payload):
        _handle_image_message(message, roster, lid_resolver, group_registry, batch_buffer, sleep)


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _has_trigger_keyword(caption: str) -> bool:
    normalized = _normalize(caption)
    return any(keyword in normalized for keyword in _KEYWORDS)


def _handle_image_message(
    message, roster, lid_resolver, group_registry, batch_buffer: ImageBatchBuffer, sleep
) -> None:
    if message.from_me:
        return

    if group_registry.get_client_name(message.group_jid) is None:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid, message.group_jid)

    if not roster.is_known_sender(sender_jid):
        return

    batch_key = (sender_jid, message.group_jid)
    snapshot = batch_buffer.add(batch_key, message)
    sleep(_BATCH_WINDOW_SECONDS)
    batch = batch_buffer.try_claim(batch_key, len(snapshot))
    if batch is None:
        # A later image in the same batch is responsible for processing
        # the whole group -- nothing to do here.
        return

    if not any(_has_trigger_keyword(m.caption) for m in batch):
        return

    total = len(batch)
    for index, image_message in enumerate(batch, start=1):
        _review_and_reply(image_message, index, total)


def _review_and_reply(message, index: int, total: int) -> None:
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
        body = f"⚠️ Encontré posibles errores de ortografía:\n{bullets}"
    else:
        body = "✅ Ortografía revisada, no encontré errores."

    reply = f"Imagen {index} de {total}:\n{body}" if total > 1 else body

    send_text_message(message.group_jid, reply)
