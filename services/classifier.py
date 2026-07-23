"""
Classifies WhatsApp messages as tasks (or not) using OpenAI, extracting a
short description and, if mentioned, a due date resolved to YYYY-MM-DD.
"""
import json
import logging
from dataclasses import dataclass

from openai import OpenAI

from config import Config

logger = logging.getLogger(__name__)

_client: OpenAI | None = None


def _get_client() -> OpenAI:
    global _client
    if _client is None:
        _client = OpenAI(api_key=Config.OPENAI_API_KEY)
    return _client


class ClassifierError(Exception):
    pass


@dataclass
class ClassificationResult:
    es_tarea: bool
    descripcion: str | None
    fecha_limite: str | None


SYSTEM_PROMPT = """Eres un asistente que analiza mensajes de un grupo de WhatsApp de trabajo para \
detectar si agendan una tarea para alguien.

Hoy es {current_date}.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "es_tarea": true si el mensaje le pide a alguien hacer algo concreto, false si no.
- "descripcion": resumen corto en español de qué hay que hacer. null si es_tarea es false.
- "fecha_limite": fecha límite en formato YYYY-MM-DD si el mensaje menciona una (ej. "mañana", \
"el viernes"), resuelta contra la fecha de hoy. null si no se menciona ninguna fecha o si \
es_tarea es false."""


def classify_message(
    text: str, current_date: str, client: OpenAI | None = None
) -> ClassificationResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-4o-mini",
            response_format={"type": "json_object"},
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT.format(current_date=current_date)},
                {"role": "user", "content": text},
            ],
        )
        data = json.loads(response.choices[0].message.content)
        es_tarea = data["es_tarea"]
        descripcion = data["descripcion"]
        fecha_limite = data["fecha_limite"]
        if not isinstance(es_tarea, bool):
            raise ValueError(f"es_tarea must be a bool, got {type(es_tarea).__name__}")
        if descripcion is not None and not isinstance(descripcion, str):
            raise ValueError(f"descripcion must be a string or null, got {type(descripcion).__name__}")
        if fecha_limite is not None and not isinstance(fecha_limite, str):
            raise ValueError(f"fecha_limite must be a string or null, got {type(fecha_limite).__name__}")
        return ClassificationResult(
            es_tarea=es_tarea, descripcion=descripcion, fecha_limite=fecha_limite
        )
    except Exception as exc:
        logger.warning(f"Classifier failed: {exc}")
        raise ClassifierError(str(exc)) from exc
