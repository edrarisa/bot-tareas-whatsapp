"""
Orchestrates a single incoming webhook message: parse -> filter -> classify
-> resolve assignee -> save to the assignee's personal Sheet (or warn the
group on failure).
"""
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from config import Config
from services.classifier import ClassifierError, classify_message
from services.evolution import parse_webhook_payload, send_text_message

logger = logging.getLogger(__name__)


def handle_webhook_payload(
    payload: dict, roster, lid_resolver, group_registry, personal_task_writer
) -> None:
    for message in parse_webhook_payload(payload):
        _handle_message(message, roster, lid_resolver, group_registry, personal_task_writer)


def _handle_message(message, roster, lid_resolver, group_registry, personal_task_writer) -> None:
    if message.from_me:
        return

    client_name = group_registry.get_client_name(message.group_jid)
    if client_name is None:
        return

    sender_jid = lid_resolver.resolve(message.sender_jid, message.group_jid)

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

    assignee_jid = None
    assignee_name = None
    for raw_jid in message.mentioned_jids:
        jid = lid_resolver.resolve(raw_jid, message.group_jid)
        if roster.same_person(jid, sender_jid):
            continue
        name = roster.resolve_name(jid)
        if name:
            assignee_jid = jid
            assignee_name = name
            break

    reporter_name = roster.resolve_name(sender_jid) or sender_jid

    logger.info(
        "Task resolution: raw_sender=%s -> sender=%s (reporter=%s) | "
        "raw_mentions=%s -> assignee=%s (client=%s)",
        message.sender_jid,
        sender_jid,
        reporter_name,
        message.mentioned_jids,
        assignee_name,
        client_name,
    )

    if assignee_jid is None:
        send_text_message(
            message.group_jid,
            "⚠️ No pude identificar a quién asignar esta tarea, no la guardé.",
        )
        return

    sheet_id = roster.resolve_personal_sheet_id(assignee_jid)
    if not sheet_id:
        send_text_message(
            message.group_jid,
            f"⚠️ No encontré la hoja personal de {assignee_name}, avísenle para configurarla.",
        )
        return

    try:
        personal_task_writer.append_task(
            sheet_id=sheet_id,
            client_tab=client_name,
            created_at=now.strftime("%Y-%m-%d %H:%M"),
            reporter=reporter_name,
            description=result.descripcion,
            due_date=result.fecha_limite,
            due_time=result.hora_limite,
            is_urgent=result.es_urgente,
            status="Pendiente",
        )
    except Exception:
        logger.exception("Failed to save task to personal sheet")
        send_text_message(message.group_jid, "⚠️ No pude guardar esta tarea, avísenle a alguien.")
