import json

import pytest

from services.classifier import ClassificationResult, ClassifierError, classify_message


class FakeCompletions:
    def __init__(self, content=None, raise_exc=None):
        self._content = content
        self._raise_exc = raise_exc

    def create(self, **kwargs):
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
