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
    details: str


SYSTEM_PROMPT = """Eres un corrector ortográfico en español. Analiza el texto visible en la \
imagen y revisa si tiene errores de ortografía.

Revisa cada palabra del texto una por una, con cuidado, sin saltarte ninguna -- es importante \
encontrar TODOS los errores de ortografía presentes, no solo los más evidentes.

Devuelve SIEMPRE un JSON con estas claves, sin texto adicional:
- "has_errors": true si encontraste al menos un error de ortografía, false si no.
- "details": si has_errors es true, describe cada error encontrado (la palabra mal escrita y \
cuál sería la forma correcta), separados por punto y coma si hay más de uno. Si has_errors es \
false, un mensaje corto confirmando que no hay errores."""


def review_spelling(
    image_base64: str, mimetype: str, client: OpenAI | None = None
) -> SpellingReviewResult:
    active_client = client or _get_client()
    try:
        response = active_client.chat.completions.create(
            model="gpt-4o",
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
        if not isinstance(details, str) or not details:
            raise ValueError("details must be a non-empty string")
        return SpellingReviewResult(has_errors=has_errors, details=details)
    except Exception as exc:
        logger.warning(f"Spelling reviewer failed: {str(exc)[:300]}")
        raise SpellingReviewError(str(exc)) from exc
