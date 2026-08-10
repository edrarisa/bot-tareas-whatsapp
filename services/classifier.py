"""
Classifies WhatsApp messages as tasks (or not) using OpenAI, extracting a
short description, a due date (YYYY-MM-DD), a due time (24h HH:MM), and
whether the task is urgent.
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
    hora_limite: str | None = None
    es_urgente: bool = False


SYSTEM_PROMPT = """Eres un asistente que analiza mensajes de un grupo de WhatsApp de trabajo para \
detectar si agendan una tarea para alguien.

Hoy es {current_date}.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "es_tarea": true si el mensaje le pide a alguien hacer algo concreto, false si no.
- "descripcion": resumen corto en español de qué hay que hacer. null si es_tarea es false.
- "fecha_limite": fecha límite en formato YYYY-MM-DD si el mensaje menciona una (ej. "mañana", \
"el viernes"), resuelta contra la fecha de hoy. Si el mensaje menciona una hora límite pero NO \
menciona ningún día (ej. "antes de las 6 pm", sin decir "mañana" ni ningún otro día), asume que \
es para hoy y usa la fecha de hoy. null si no se menciona ninguna fecha ni hora, o si es_tarea \
es false.
- "hora_limite": hora límite en formato de 24 horas HH:MM si el mensaje indica una hora concreta \
para completar la tarea, sin importar cómo esté redactada -- la gente lo dice de muchas formas \
distintas, no solo con "antes de". Por ejemplo: "antes de las 6 pm" -> "18:00", "a las 3:30" -> \
"15:30", "para las 6" -> "18:00", "máximo a las 5" -> "17:00", "antes del mediodía" -> "12:00", \
"entregarlo a las 9 am" -> "09:00". null si no se menciona ninguna hora concreta, si la hora es \
vaga o relativa (ej. "en la tarde", "más tarde", "pronto"), o si es_tarea es false.
- "es_urgente": true si la tarea es urgente -- porque su fecha límite es HOY (el mismo día en que \
se crea la tarea), o porque el mensaje usa lenguaje explícito de urgencia (ej. "urgente", "ya", \
"necesito esto ahora", "es urgente"), lo que ocurra primero. false en cualquier otro caso, \
incluyendo si es_tarea es false."""


def classify_message(
    text: str, current_date: str, client: OpenAI | None = None
) -> ClassificationResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-5.6-terra",
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
        hora_limite = data["hora_limite"]
        es_urgente = data["es_urgente"]
        if not isinstance(es_tarea, bool):
            raise ValueError(f"es_tarea must be a bool, got {type(es_tarea).__name__}")
        if descripcion is not None and not isinstance(descripcion, str):
            raise ValueError(f"descripcion must be a string or null, got {type(descripcion).__name__}")
        if fecha_limite is not None and not isinstance(fecha_limite, str):
            raise ValueError(f"fecha_limite must be a string or null, got {type(fecha_limite).__name__}")
        if hora_limite is not None and not isinstance(hora_limite, str):
            raise ValueError(f"hora_limite must be a string or null, got {type(hora_limite).__name__}")
        if not isinstance(es_urgente, bool):
            raise ValueError(f"es_urgente must be a bool, got {type(es_urgente).__name__}")
        if es_tarea and not descripcion:
            raise ValueError("es_tarea is true but descripcion is missing or empty")
        return ClassificationResult(
            es_tarea=es_tarea,
            descripcion=descripcion,
            fecha_limite=fecha_limite,
            hora_limite=hora_limite,
            es_urgente=es_urgente,
        )
    except Exception as exc:
        logger.warning(f"Classifier failed: {exc}")
        raise ClassifierError(str(exc)) from exc
