"""
Orchestrates a single incoming webhook message: parse -> filter -> classify
-> resolve assignee -> save to Sheets (or warn the group on save failure).
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config
from services.classifier import ClassifierError, classify_message
from services.evolution import parse_webhook_payload, send_text_message

logger = logging.getLogger(__name__)


def handle_webhook_payload(
    payload: dict, roster, lid_resolver, sheets_client, group_jid: str
) -> None:
    for message in parse_webhook_payload(payload):
        _handle_message(message, roster, lid_resolver, sheets_client, group_jid)


def _handle_message(message, roster, lid_resolver, sheets_client, group_jid: str) -> None:
    if message.from_me or message.group_jid != group_jid:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid)

    if not roster.is_known_sender(sender_jid):
        return

    if not message.mentioned_jids:
        return

    now = datetime.now(ZoneInfo(Config.TIMEZONE))
    today = now.date().isoformat()

    try:
        result = classify_message(message.text, today)
    except ClassifierError:
        logger.exception("Classifier failed for message from %s", sender_jid)
        return

    if not result.es_tarea:
        return

    assignee = "Sin asignar"
    for raw_jid in message.mentioned_jids:
        jid = lid_resolver.resolve(raw_jid)
        if roster.same_person(jid, sender_jid):
            continue
        name = roster.resolve_name(jid)
        if name:
            assignee = name
            break

    reporter_name = roster.resolve_name(sender_jid) or sender_jid

    logger.info(
        "Task resolution: raw_sender=%s -> sender=%s (reporter=%s) | "
        "raw_mentions=%s -> assignee=%s",
        message.sender_jid,
        sender_jid,
        reporter_name,
        message.mentioned_jids,
        assignee,
    )

    try:
        sheets_client.append_task(
            created_at=now.strftime("%Y-%m-%d %H:%M"),
            reporter=reporter_name,
            description=result.descripcion,
            assignee=assignee,
            due_date=result.fecha_limite,
            status="Pendiente",
        )
    except Exception:
        logger.exception("Failed to save task to Sheets")
        send_text_message(group_jid, "⚠️ No pude guardar esta tarea, avísenle a alguien.")
