"""
Orchestrates a single incoming webhook message: parse -> filter -> classify
-> resolve assignee -> save to Sheets (or warn the group on save failure).
"""
import logging
from datetime import date

from services.classifier import ClassifierError, classify_message
from services.evolution import parse_webhook_payload, send_text_message

logger = logging.getLogger(__name__)


def handle_webhook_payload(payload: dict, roster, sheets_client, group_jid: str) -> None:
    message = parse_webhook_payload(payload)
    if message is None or message.from_me or message.group_jid != group_jid:
        return

    if not roster.is_known_sender(message.sender_jid):
        return

    try:
        result = classify_message(message.text, date.today().isoformat())
    except ClassifierError:
        logger.exception("Classifier failed for message from %s", message.sender_jid)
        return

    if not result.es_tarea:
        return

    assignee = "Sin asignar"
    for jid in message.mentioned_jids:
        if roster.same_person(jid, message.sender_jid):
            continue
        name = roster.resolve_name(jid)
        if name:
            assignee = name
            break

    reporter_name = roster.resolve_name(message.sender_jid) or message.sender_jid

    try:
        sheets_client.append_task(
            created_at=date.today().isoformat(),
            reporter=reporter_name,
            description=result.descripcion,
            assignee=assignee,
            due_date=result.fecha_limite,
            status="Pendiente",
        )
    except Exception:
        logger.exception("Failed to save task to Sheets")
        send_text_message(group_jid, "⚠️ No pude guardar esta tarea, avísenle a alguien.")
