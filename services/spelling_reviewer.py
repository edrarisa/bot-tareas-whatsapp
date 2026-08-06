"""
Reviews the Spanish spelling of text visible in an image, using OpenAI's
vision-capable chat completions API.
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


class SpellingReviewError(Exception):
    pass


@dataclass
class SpellingReviewResult:
    has_errors: bool
    details: list[str]


SYSTEM_PROMPT = """Eres un corrector de ortografía y redacción en español. Analiza el texto \
visible en la imagen y revisa si tiene errores.

Revisa cada palabra y cada signo del texto, uno por uno, con cuidado, sin saltarte nada -- es \
importante encontrar TODOS los errores presentes, no solo los más evidentes. Incluye en tu \
revisión:
- Ortografía de palabras: letras de más, de menos o cambiadas, tildes faltantes o sobrantes.
- Signos de puntuación: comas, puntos, dos puntos y punto y coma mal usados, faltantes o \
sobrantes, incluyendo su posición dentro de la frase.
- Signos de interrogación y exclamación: en español deben ir tanto el signo de apertura (¿ o ¡) \
como el de cierre (? o !); marca como error cualquier pregunta o exclamación a la que le falte \
el signo de apertura o el de cierre.
- Mayúsculas y minúsculas mal usadas, por ejemplo meses, días de la semana o palabras comunes \
escritas con mayúscula sin ser nombres propios ni inicio de oración.
- Espaciado entre palabras: palabras que deberían ir separadas y aparecen juntas, o que deberían \
ir juntas y aparecen separadas.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "has_errors": true si encontraste al menos un error, false si no.
- "details": una lista (array) de strings. Si has_errors es true, cada elemento de la lista \
describe UN solo error (qué está mal y cuál sería la forma correcta) -- un elemento por error, \
no los combines en un solo texto. Si has_errors es false, una lista con un único mensaje corto \
confirmando que no hay errores."""


def review_spelling(
    image_base64: str, mimetype: str, client: OpenAI | None = None
) -> SpellingReviewResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-5.6-sol",
            response_format={"type": "json_object"},
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image_url",
                            "image_url": {"url": f"data:{mimetype};base64,{image_base64}"},
                        }
                    ],
                },
            ],
        )
        data = json.loads(response.choices[0].message.content)
        has_errors = data["has_errors"]
        details = data["details"]
        if not isinstance(has_errors, bool):
            raise ValueError(f"has_errors must be a bool, got {type(has_errors).__name__}")
        if not isinstance(details, list) or not details:
            raise ValueError("details must be a non-empty list of strings")
        if not all(isinstance(item, str) and item for item in details):
            raise ValueError("details must contain only non-empty strings")
        return SpellingReviewResult(has_errors=has_errors, details=details)
    except Exception as exc:
        logger.warning(f"Spelling reviewer failed: {str(exc)[:300]}")
        raise SpellingReviewError(str(exc)) from exc
