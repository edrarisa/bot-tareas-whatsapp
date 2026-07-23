import pytest

from config import Config

REQUIRED_ATTRS = [
    "EVOLUTION_API_URL",
    "EVOLUTION_API_KEY",
    "EVOLUTION_INSTANCE",
    "WHATSAPP_GROUP_JID",
    "GOOGLE_SHEETS_ID",
    "OPENAI_API_KEY",
]


def _set_all(monkeypatch, except_attr=None):
    for attr in REQUIRED_ATTRS:
        monkeypatch.setattr(Config, attr, "" if attr == except_attr else "x")


def test_validate_raises_when_a_required_var_is_missing(monkeypatch):
    _set_all(monkeypatch, except_attr="EVOLUTION_API_URL")
    with pytest.raises(ValueError, match="EVOLUTION_API_URL"):
        Config.validate()


def test_validate_passes_when_all_required_vars_present(monkeypatch):
    _set_all(monkeypatch)
    Config.validate()
