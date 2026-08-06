import pytest

from services.lid_resolver import LidResolver

GROUP_JID = "120363429677992008@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"


def _fake_response(status_code=200, json_data=None):
    class FakeResponse:
        def __init__(self):
            self.status_code = status_code
            self.text = str(json_data)

        def raise_for_status(self):
            if self.status_code >= 400:
                raise RuntimeError(f"HTTP {self.status_code}")

        def json(self):
            return json_data

    return FakeResponse()


def test_returns_non_lid_jids_unchanged():
    resolver = LidResolver()
    assert resolver.resolve("573042747698@s.whatsapp.net", GROUP_JID) == "573042747698@s.whatsapp.net"


def test_resolves_lid_to_phone_jid(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["count"] += 1
        return _fake_response(
            json_data={
                "participants": [
                    {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"},
                    {"id": "203744859922485@lid", "phoneNumber": "573118964235@s.whatsapp.net"},
                ]
            }
        )

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"
    assert resolver.resolve("203744859922485@lid", GROUP_JID) == "573118964235@s.whatsapp.net"
    assert calls["count"] == 1


def test_returns_unknown_lid_unchanged(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _fake_response(json_data={"participants": []})

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("999999999999999@lid", GROUP_JID) == "999999999999999@lid"


def test_skips_participants_without_a_resolvable_phone_number(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        return _fake_response(
            json_data={
                "participants": [
                    {"id": "111111111111111@lid", "admin": None},
                    {"id": "222222222222222@lid", "phoneNumber": "573000000000@s.whatsapp.net"},
                ]
            }
        )

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("111111111111111@lid", GROUP_JID) == "111111111111111@lid"
    assert resolver.resolve("222222222222222@lid", GROUP_JID) == "573000000000@s.whatsapp.net"


def test_caches_participants_within_ttl(monkeypatch):
    calls = {"count": 0}

    def fake_get(url, headers=None, params=None, timeout=None):
        calls["count"] += 1
        return _fake_response(
            json_data={
                "participants": [
                    {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"}
                ]
            }
        )

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    clock = {"now": 1000.0}
    resolver = LidResolver(ttl_seconds=300, time_func=lambda: clock["now"])

    resolver.resolve("151556578083034@lid", GROUP_JID)
    resolver.resolve("151556578083034@lid", GROUP_JID)
    assert calls["count"] == 1

    clock["now"] += 301
    resolver.resolve("151556578083034@lid", GROUP_JID)
    assert calls["count"] == 2


def test_falls_back_to_stale_cache_when_refresh_fails(monkeypatch):
    responses = [
        _fake_response(
            json_data={
                "participants": [
                    {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"}
                ]
            }
        )
    ]

    def fake_get(url, headers=None, params=None, timeout=None):
        if responses:
            return responses.pop()
        raise RuntimeError("network down")

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    clock = {"now": 1000.0}
    resolver = LidResolver(ttl_seconds=300, time_func=lambda: clock["now"])

    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"

    clock["now"] += 301
    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"


def test_raises_when_first_load_fails(monkeypatch):
    def fake_get(url, headers=None, params=None, timeout=None):
        raise RuntimeError("network down")

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    with pytest.raises(RuntimeError):
        resolver.resolve("151556578083034@lid", GROUP_JID)


def test_caches_are_isolated_per_group(monkeypatch):
    """Resolving a LID for one group must not use another group's cached
    participants -- each group has its own participant list."""
    calls = []

    def fake_get(url, headers=None, params=None, timeout=None):
        group_jid = params["groupJid"]
        calls.append(group_jid)
        if group_jid == GROUP_JID:
            participants = [
                {"id": "151556578083034@lid", "phoneNumber": "573042747698@s.whatsapp.net"}
            ]
        else:
            participants = [
                {"id": "151556578083034@lid", "phoneNumber": "573099998877@s.whatsapp.net"}
            ]
        return _fake_response(json_data={"participants": participants})

    monkeypatch.setattr("services.lid_resolver.requests.get", fake_get)

    resolver = LidResolver()

    assert resolver.resolve("151556578083034@lid", GROUP_JID) == "573042747698@s.whatsapp.net"
    assert resolver.resolve("151556578083034@lid", OTHER_GROUP_JID) == "573099998877@s.whatsapp.net"
    assert calls == [GROUP_JID, OTHER_GROUP_JID]
