from services.roster import Roster


class FakeSheetsClient:
    def __init__(self, rows):
        self._rows = rows
        self.read_calls = 0

    def read_team_roster(self):
        self.read_calls += 1
        return self._rows


def test_is_known_sender_true_for_roster_member():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573001112233@s.whatsapp.net") is True


def test_is_known_sender_false_for_unknown_number():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.is_known_sender("573009998877@s.whatsapp.net") is False


def test_resolve_name_returns_name_for_known_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_resolve_name_returns_none_for_unknown_jid():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573009998877@s.whatsapp.net") is None


def test_normalizes_non_digit_characters_in_stored_numbers():
    sheets_client = FakeSheetsClient([("Cristian", "+57 300 111 2233")])
    roster = Roster(sheets_client)

    assert roster.resolve_name("573001112233@s.whatsapp.net") == "Cristian"


def test_caches_roster_within_ttl():
    sheets_client = FakeSheetsClient([("Cristian", "573001112233")])
    clock = {"now": 1000.0}
    roster = Roster(sheets_client, ttl_seconds=300, time_func=lambda: clock["now"])

    roster.is_known_sender("573001112233@s.whatsapp.net")
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 1

    clock["now"] += 301
    roster.is_known_sender("573001112233@s.whatsapp.net")
    assert sheets_client.read_calls == 2
