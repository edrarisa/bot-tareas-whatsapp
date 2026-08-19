"""
Orchestrates incoming image/PDF messages: parse -> skip already-seen message
IDs (a redelivered webhook must not be reprocessed) -> filter (group
registered, known sender, not from_me) -> buffer briefly so several files
sent together in one WhatsApp multi-file send are grouped -> if any file in
the group has a trigger keyword in its caption, send a short "reviewing
now" message, then review every file in the group with OpenAI -> reply in
the group once per file, numbered when the group has more than one file
and tagging (@) whoever sent it.

WhatsApp delivers a multi-image send as separate messages (often as
separate webhook calls), and typically only one of them carries the
caption text -- the rest arrive with no caption at all. The batch buffer
exists to catch those caption-less siblings instead of silently ignoring
them. Batches are keyed by (sender, group) so files sent to two
different client groups around the same time never mix into one batch.

A large PDF can take OpenAI long enough to process that Evolution API's
own webhook delivery gives up and retries the same webhook call -- without
the seen-message-ID check, that retry would be treated as a brand new file
and reprocessed (including sending "reviewing now" again).
"""
import logging
import time
import unicodedata

from services.evolution import parse_reviewable_messages, send_text_message
from services.image_batch import ImageBatchBuffer
from services.spelling_reviewer import (
    FileTooLargeError,
    QuotaExceededError,
    SpellingReviewError,
    review_spelling,
)
from services.seen_messages import SeenMessageTracker

logger = logging.getLogger(__name__)

_KEYWORDS = ("ortografia", "a1")

# How long to wait after a file arrives to see if sibling files from the
# same sender show up before deciding whether to process the batch.
_BATCH_WINDOW_SECONDS = 4.0


def handle_webhook_payload(
    payload: dict,
    roster,
    lid_resolver,
    group_registry,
    batch_buffer: ImageBatchBuffer,
    seen_messages: SeenMessageTracker,
    sleep=time.sleep,
) -> None:
    for message in parse_reviewable_messages(payload):
        _handle_reviewable_message(
            message, roster, lid_resolver, group_registry, batch_buffer, seen_messages, sleep
        )


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch)).lower()


def _has_trigger_keyword(caption: str) -> bool:
    normalized = _normalize(caption)
    return any(keyword in normalized for keyword in _KEYWORDS)


def _handle_reviewable_message(
    message,
    roster,
    lid_resolver,
    group_registry,
    batch_buffer: ImageBatchBuffer,
    seen_messages: SeenMessageTracker,
    sleep,
) -> None:
    if message.message_id and not seen_messages.mark_if_new(message.message_id):
        logger.info("Ignoring redelivered message %s (already processed)", message.message_id)
        return

    if message.from_me:
        return

    if group_registry.get_client_name(message.group_jid) is None:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid, message.group_jid)

    if not roster.is_known_sender(sender_jid):
        logger.info(
            "Ignoring file from unrecognized sender %s (resolved from %s) in group %s -- if this "
            "person is in the roster, their WhatsApp phone-number privacy setting may be blocking "
            "LID resolution",
            sender_jid,
            message.sender_jid,
            message.group_jid,
        )
        return

    batch_key = (sender_jid, message.group_jid)
    snapshot = batch_buffer.add(batch_key, message)
    sleep(_BATCH_WINDOW_SECONDS)
    batch = batch_buffer.try_claim(batch_key, len(snapshot))
    if batch is None:
        # A later file in the same batch is responsible for processing
        # the whole group -- nothing to do here.
        return

    if not any(_has_trigger_keyword(m.caption) for m in batch):
        return

    send_text_message(message.group_jid, "⏳ Revisando la ortografía, dame un momento...")

    total = len(batch)
    for index, reviewable_message in enumerate(batch, start=1):
        _review_and_reply(reviewable_message, index, total, sender_jid)


def _build_mention(sender_jid: str) -> tuple[str, list[str]]:
    """Returns an "@<digits>" tag plus the matching `mentioned` list for
    `send_text_message`, or ("", []) if `sender_jid` isn't a real
    phone-number JID (e.g. an unresolved "@lid") -- WhatsApp can't render
    a mention for those."""
    if not sender_jid.endswith("@s.whatsapp.net"):
        return "", []
    digits = sender_jid.split("@", 1)[0]
    return f"@{digits}", [sender_jid]


def _review_and_reply(message, index: int, total: int, sender_jid: str) -> None:
    try:
        result = review_spelling(message.file_base64, message.mimetype, message.filename)
    except FileTooLargeError:
        _send_reply(
            message,
            index,
            total,
            sender_jid,
            "⚠️ El archivo es muy grande para revisarlo, intenta con uno más liviano.",
        )
        return
    except QuotaExceededError:
        logger.error("Spelling review out of quota for message from %s", message.sender_jid)
        _send_reply(
            message,
            index,
            total,
            sender_jid,
            "⚠️ No pude revisar esto: el servicio de IA se quedó sin créditos o está saturado "
            "por ahora. Avisen a quien administra el bot.",
        )
        return
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

    _send_reply(message, index, total, sender_jid, body)


def _send_reply(message, index: int, total: int, sender_jid: str, body: str) -> None:
    reply = f"Archivo {index} de {total}:\n{body}" if total > 1 else body

    mention_tag, mentioned_jids = _build_mention(sender_jid)
    if mention_tag:
        reply = f"{mention_tag} {reply}"

    send_text_message(message.group_jid, reply, mentioned=mentioned_jids)
