import pytest

from services.roster import Roster


class FakeSheetsClient:
    def __init__(self, rows):
        self._rows = rows
        self.read_calls = 0
        self.raise_exc = None

    def read_team_roster(self):
        self.read_calls += 1
        if self.raise_exc is not None:
            exc = self.raise_exc
            self.raise_exc = None  # One-time exception
            raise exc
        return self._rows


def test_is_known_sender_true_for_roster_member():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573001112233@s.whatsapp.net") is True


def test_is_known_sender_false_for_unknown_number():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573009998877@s.whatsapp.net") is False


def test_resolve_name_returns_name_for_known_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_resolve_name_returns_none_for_unknown_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573009998877@s.whatsapp.net") is None


def test_normalizes_non_digit_characters_in_stored_numbers():
    sheets_client = FakeSheetsClient([("Cristian", "+57 300 111 2233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_caches_roster_within_ttl():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    clock = {"now": 1000.0}
    roster = Roster(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    roster.is_known_sender("573001112233@s.whatsapp.net")
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 2


def test_falls_back_to_stale_cache_when_refresh_fails():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    clock = {"now": 1000.0}
    roster = Roster(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    # First successful load
    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"
    assert sheets_client.read_calls == 1

    # Advance past TTL and make next read fail
    clock["now"] += 301
    sheets_client.raise_exc = ValueError("Sheets API error")

    # Should use stale cache instead of raising
    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"
    assert sheets_client.read_calls == 2


def test_same_person_true_for_jids_with_different_device_suffix():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.same_person("573001112233@s.whatsapp.net", "573001112233:19@s.whatsapp.net") is True


def test_same_person_false_for_different_numbers():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.same_person("573001112233@s.whatsapp.net", "573009998877@s.whatsapp.net") is False


def test_raises_when_first_load_fails():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    sheets_client.raise_exc = ValueError("Sheets API error")
    roster = Roster(sheets_client)

    # Should raise because there's no cache to fall back to
    with pytest.raises(ValueError, match="Sheets API error"):
        roster.is_known_sender("573001112233@s.whatsapp.net")


def test_resolve_personal_sheet_id_returns_sheet_id_for_known_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_personal_sheet_id("573001112233@s.whatsapp.net") == "sheet-cristian"


def test_resolve_personal_sheet_id_returns_none_for_unknown_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "sheet-cristian")])
    roster = Roster(sheets_client)

    assert roster.resolve_personal_sheet_id("573009998877@s.whatsapp.net") is None


def test_resolve_personal_sheet_id_returns_none_when_not_configured():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233", "")])
    roster = Roster(sheets_client)

    assert roster.resolve_personal_sheet_id("573001112233@s.whatsapp.net") is None
