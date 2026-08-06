import pytest

from services.group_registry import GroupRegistry


class FakeSheetsClient:
    def __init__(self, rows):
        self._rows = rows
        self.read_calls = 0
        self.raise_exc = None

    def read_group_mapping(self):
        self.read_calls += 1
        if self.raise_exc is not None:
            exc = self.raise_exc
            self.raise_exc = None  # One-time exception
            raise exc
        return self._rows


def test_get_client_name_returns_client_for_known_group():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    registry = GroupRegistry(sheets_client)

    assert registry.get_client_name("120363429440515454@g.us") == "clinicachia"


def test_get_client_name_returns_none_for_unknown_group():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    registry = GroupRegistry(sheets_client)

    assert registry.get_client_name("999999999999999@g.us") is None


def test_caches_mapping_within_ttl():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    clock = {"now": 1000.0}
    registry = GroupRegistry(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    registry.get_client_name("120363429440515454@g.us")
    registry.get_client_name("120363429440515454@g.us")
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    registry.get_client_name("120363429440515454@g.us")
    assert sheets_client.read_calls == 2


def test_falls_back_to_stale_cache_when_refresh_fails():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    clock = {"now": 1000.0}
    registry = GroupRegistry(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    assert registry.get_client_name("120363429440515454@g.us") == "clinicachia"
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    sheets_client.raise_exc = ValueError("Sheets API error")

    assert registry.get_client_name("120363429440515454@g.us") == "clinicachia"
    assert sheets_client.read_calls == 2


def test_raises_when_first_load_fails():
    sheets_client = FakeSheetsClient([("120363429440515454@g.us", "clinicachia")])
    sheets_client.raise_exc = ValueError("Sheets API error")
    registry = GroupRegistry(sheets_client)

    with pytest.raises(ValueError, match="Sheets API error"):
        registry.get_client_name("120363429440515454@g.us")
