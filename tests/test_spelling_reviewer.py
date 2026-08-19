import json

import httpx
import pytest
from openai import RateLimitError

from services.spelling_reviewer import (
    FileTooLargeError,
    QuotaExceededError,
    SpellingReviewError,
    SpellingReviewResult,
    review_spelling,
)


def _rate_limit_error(message="insufficient_quota"):
    request = httpx.Request("POST", "https://api.openai.com/v1/chat/completions")
    response = httpx.Response(status_code=429, request=request)
    return RateLimitError(message, response=response, body=None)


class FakeCompletions:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise_exc = raise_exc
        self.last_call_kwargs = None

    def create(self, **kwargs):
        self.last_call_kwargs = kwargs
        if self._raise_exc:
            raise self._raise_exc
        return FakeResponse(self._content)


class FakeChat:
    def __init__(self, **kwargs):
        self.completions = FakeCompletions(**kwargs)


class FakeClient:
    def __init__(self, **kwargs):
        self.chat = FakeChat(**kwargs)


class FakeMessage:
    def __init__(self, content):
        self.content = content


class FakeChoice:
    def __init__(self, content):
        self.message = FakeMessage(content)


class FakeResponse:
    def __init__(self, content):
        self.choices = [FakeChoice(content)]


def test_detects_spelling_errors():
    content = json.dumps(
        {"has_errors": True, "details": ["'campana' deberia ser 'campaña'"]}
    )
    client = FakeClient(content=content)

    result = review_spelling("aGVsbG8=", "image/png", client=client)

    assert result == SpellingReviewResult(
        has_errors=True, details=["'campana' deberia ser 'campaña'"]
    )


def test_detects_multiple_spelling_errors_as_separate_items():
    content = json.dumps(
        {
            "has_errors": True,
            "details": [
                "'campana' deberia ser 'campaña'",
                "Falta el signo de apertura '¡' en la exclamación",
            ],
        }
    )
    client = FakeClient(content=content)

    result = review_spelling("aGVsbG8=", "image/png", client=client)

    assert result.details == [
        "'campana' deberia ser 'campaña'",
        "Falta el signo de apertura '¡' en la exclamación",
    ]


def test_confirms_no_errors():
    content = json.dumps({"has_errors": False, "details": ["Sin errores detectados"]})
    client = FakeClient(content=content)

    result = review_spelling("aGVsbG8=", "image/png", client=client)

    assert result.has_errors is False


def test_sends_image_as_data_url_to_openai():
    content = json.dumps({"has_errors": False, "details": ["Sin errores"]})
    client = FakeClient(content=content)

    review_spelling("aGVsbG8=", "image/png", client=client)

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["model"] == "gpt-5.6-sol"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["timeout"] == 30
    user_message = kwargs["messages"][1]
    assert user_message["role"] == "user"
    image_url = user_message["content"][0]["image_url"]["url"]
    assert image_url == "data:image/png;base64,aGVsbG8="


def test_sends_pdf_as_file_data_url_to_openai():
    content = json.dumps({"has_errors": False, "details": ["Sin errores"]})
    client = FakeClient(content=content)

    review_spelling("aGVsbG8=", "application/pdf", "propuesta.pdf", client=client)

    kwargs = client.chat.completions.last_call_kwargs
    user_message = kwargs["messages"][1]
    file_content = user_message["content"][0]
    assert file_content["type"] == "file"
    assert file_content["file"]["filename"] == "propuesta.pdf"
    assert file_content["file"]["file_data"] == "data:application/pdf;base64,aGVsbG8="


def test_defaults_pdf_filename_when_not_given():
    content = json.dumps({"has_errors": False, "details": ["Sin errores"]})
    client = FakeClient(content=content)

    review_spelling("aGVsbG8=", "application/pdf", client=client)

    kwargs = client.chat.completions.last_call_kwargs
    file_content = kwargs["messages"][1]["content"][0]
    assert file_content["file"]["filename"] == "documento.pdf"


def test_raises_error_for_unsupported_mimetype():
    client = FakeClient(content=json.dumps({"has_errors": False, "details": ["x"]}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "application/vnd.ms-excel", client=client)


def test_rejects_pdf_larger_than_the_limit():
    client = FakeClient(content=json.dumps({"has_errors": False, "details": ["x"]}))
    # Base64 inflates size by ~4/3, so this decodes to ~51 MB -- over the 50 MB limit.
    oversized_base64 = "A" * (51 * 1024 * 1024 * 4 // 3)

    with pytest.raises(FileTooLargeError):
        review_spelling(oversized_base64, "application/pdf", client=client)


def test_accepts_a_pdf_within_the_limit():
    content = json.dumps({"has_errors": False, "details": ["Sin errores"]})
    client = FakeClient(content=content)

    result = review_spelling("A" * 1000, "application/pdf", client=client)

    assert result.has_errors is False


def test_file_too_large_error_is_a_spelling_review_error():
    """The handler catches SpellingReviewError broadly for generic failures
    -- FileTooLargeError must stay a subclass so that catch also covers it,
    even though the handler checks for the specific subtype first to give a
    more helpful reply."""
    assert issubclass(FileTooLargeError, SpellingReviewError)


def test_raises_error_on_invalid_json():
    client = FakeClient(content="not json")

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_on_missing_key():
    client = FakeClient(content=json.dumps({"details": "x"}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_api_call_fails():
    client = FakeClient(raise_exc=RuntimeError("timeout"))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_quota_exceeded_error_on_rate_limit():
    client = FakeClient(raise_exc=_rate_limit_error())

    with pytest.raises(QuotaExceededError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_quota_exceeded_error_is_a_spelling_review_error():
    assert issubclass(QuotaExceededError, SpellingReviewError)


def test_raises_error_when_has_errors_is_not_a_bool():
    client = FakeClient(content=json.dumps({"has_errors": "yes", "details": "x"}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_details_is_missing_or_empty():
    client = FakeClient(content=json.dumps({"has_errors": False, "details": []}))

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_details_is_not_a_list():
    client = FakeClient(
        content=json.dumps({"has_errors": False, "details": "Sin errores"})
    )

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_raises_error_when_details_contains_empty_strings():
    client = FakeClient(
        content=json.dumps({"has_errors": True, "details": ["algo mal", ""]})
    )

    with pytest.raises(SpellingReviewError):
        review_spelling("aGVsbG8=", "image/png", client=client)


def test_truncates_long_exception_messages_in_logs(caplog):
    long_message = "x" * 1000
    client = FakeClient(raise_exc=RuntimeError(long_message))

    with pytest.raises(SpellingReviewError) as exc_info:
        review_spelling("aGVsbG8=", "image/png", client=client)

    # Verify the full message is in the raised exception
    assert len(str(exc_info.value)) == 1000
    assert str(exc_info.value) == long_message

    # Verify the logged message is truncated
    assert len(caplog.records) > 0
    logged_message = caplog.records[0].message
    assert len(logged_message) < 500
    assert "Spelling reviewer failed:" in logged_message
