import json

import pytest

from services.classifier import ClassificationResult, ClassifierError, classify_message


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


def test_classifies_a_task_with_due_date():
    content = json.dumps(
        {"es_tarea": True, "descripcion": "Revisar el stand", "fecha_limite": "2026-07-24"}
    )
    client = FakeClient(content=content)

    result = classify_message("Cristian revisa el stand mañana", "2026-07-23", client=client)

    assert result == ClassificationResult(
        es_tarea=True, descripcion="Revisar el stand", fecha_limite="2026-07-24"
    )


def test_classifies_a_non_task():
    content = json.dumps({"es_tarea": False, "descripcion": None, "fecha_limite": None})
    client = FakeClient(content=content)

    result = classify_message("jajaja buenísimo", "2026-07-23", client=client)

    assert result.es_tarea is False


def test_raises_classifier_error_on_invalid_json():
    client = FakeClient(content="not json")

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_on_missing_key():
    client = FakeClient(content=json.dumps({"descripcion": "x"}))

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_api_call_fails():
    client = FakeClient(raise_exc=RuntimeError("timeout"))

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_sends_expected_request_to_openai():
    content = json.dumps(
        {"es_tarea": True, "descripcion": "Test task", "fecha_limite": "2026-07-24"}
    )
    client = FakeClient(content=content)

    classify_message("Some message", "2026-07-23", client=client)

    kwargs = client.chat.completions.last_call_kwargs
    assert kwargs["model"] == "gpt-5.6-terra"
    assert kwargs["response_format"] == {"type": "json_object"}
    assert kwargs["timeout"] == 30
    system_message_content = kwargs["messages"][0]["content"]
    assert "2026-07-23" in system_message_content


def test_raises_classifier_error_when_es_tarea_is_not_a_bool():
    content = json.dumps(
        {"es_tarea": "false", "descripcion": None, "fecha_limite": None}
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_descripcion_is_not_a_string():
    content = json.dumps(
        {"es_tarea": True, "descripcion": 123, "fecha_limite": None}
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_fecha_limite_is_not_a_string():
    content = json.dumps(
        {"es_tarea": True, "descripcion": "Task", "fecha_limite": ["2026-07-24"]}
    )
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_es_tarea_true_but_descripcion_empty():
    content = json.dumps({"es_tarea": True, "descripcion": "", "fecha_limite": None})
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)


def test_raises_classifier_error_when_es_tarea_true_but_descripcion_null():
    content = json.dumps({"es_tarea": True, "descripcion": None, "fecha_limite": None})
    client = FakeClient(content=content)

    with pytest.raises(ClassifierError):
        classify_message("algo", "2026-07-23", client=client)
