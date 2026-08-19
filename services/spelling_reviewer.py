"""
Reviews the Spanish spelling of text visible in an image or a PDF document,
using OpenAI's vision-capable chat completions API.
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


class FileTooLargeError(SpellingReviewError):
    pass


# A large PDF makes OpenAI extract text AND render a page image for every
# page, which can take long enough to blow past our own request timeout and
# WhatsApp's webhook-delivery timeout (the latter causes Evolution API to
# retry the whole webhook call, reprocessing the same message). Rejecting
# oversized PDFs upfront avoids both.
_MAX_PDF_BYTES = 15 * 1024 * 1024


@dataclass
class SpellingReviewResult:
    has_errors: bool
    details: list[str]


SYSTEM_PROMPT = """Eres un corrector de ortografía y redacción en español. Analiza el texto \
visible en la imagen o el documento PDF que se te comparte y revisa si tiene errores.

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


def _build_content(file_base64: str, mimetype: str, filename: str | None) -> list[dict]:
    if mimetype.startswith("image/"):
        return [
            {
                "type": "image_url",
                "image_url": {"url": f"data:{mimetype};base64,{file_base64}"},
            }
        ]
    if mimetype == "application/pdf":
        estimated_bytes = len(file_base64) * 3 // 4
        if estimated_bytes > _MAX_PDF_BYTES:
            logger.info(
                "Rejecting oversized PDF: ~%.1f MB, limit is %.0f MB",
                estimated_bytes / 1_048_576,
                _MAX_PDF_BYTES / 1_048_576,
            )
            raise FileTooLargeError(
                f"PDF is too large to review (~{estimated_bytes / 1_048_576:.1f} MB, "
                f"limit is {_MAX_PDF_BYTES / 1_048_576:.0f} MB)"
            )
        return [
            {
                "type": "file",
                "file": {
                    "filename": filename or "documento.pdf",
                    "file_data": f"data:{mimetype};base64,{file_base64}",
                },
            }
        ]
    raise ValueError(f"Unsupported mimetype for spelling review: {mimetype}")


def review_spelling(
    file_base64: str,
    mimetype: str,
    filename: str | None = None,
    client: OpenAI | None = None,
) -> SpellingReviewResult:
    active_client = client or _get_client()
    try:
        content = _build_content(file_base64, mimetype, filename)
        response = active_client.chat.completions.create(
            model="gpt-5.6-sol",
            response_format={"type": "json_object"},
            timeout=30,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": content},
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
    except FileTooLargeError:
        raise
    except Exception as exc:
        logger.warning(f"Spelling reviewer failed: {str(exc)[:300]}")
        raise SpellingReviewError(str(exc)) from exc
