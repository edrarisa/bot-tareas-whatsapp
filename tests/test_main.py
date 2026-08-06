from fastapi.testclient import TestClient

import main


def test_webhook_delegates_to_both_handlers(monkeypatch):
    task_calls = []
    spelling_calls = []

    def fake_task_handler(payload, roster, lid_resolver, sheets_client, group_jid):
        task_calls.append((payload, roster, lid_resolver, sheets_client, group_jid))

    def fake_spelling_handler(payload, roster, lid_resolver, group_jid):
        spelling_calls.append((payload, roster, lid_resolver, group_jid))

    monkeypatch.setattr(main, "handle_task_payload", fake_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert task_calls == [
        (body, "fake-roster", "fake-lid-resolver", "fake-sheets-client", "120363429440515454@g.us")
    ]
    assert spelling_calls == [
        (body, "fake-roster", "fake-lid-resolver", "120363429440515454@g.us")
    ]


def test_webhook_returns_200_even_if_task_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, sheets_client, group_jid):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", raising_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: None)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_webhook_returns_200_even_if_spelling_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, group_jid):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", lambda *a: None)
    monkeypatch.setattr(main, "handle_spelling_payload", raising_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_spelling_handler_still_runs_when_task_handler_raises(monkeypatch):
    """The two handlers are independent -- one failing must not block the other."""
    spelling_calls = []

    def raising_task_handler(payload, roster, lid_resolver, sheets_client, group_jid):
        raise RuntimeError("boom")

    def fake_spelling_handler(payload, roster, lid_resolver, group_jid):
        spelling_calls.append(payload)

    monkeypatch.setattr(main, "handle_task_payload", raising_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert spelling_calls == [body]


def test_webhook_returns_200_on_malformed_json_body(monkeypatch):
    task_calls = []
    spelling_calls = []
    monkeypatch.setattr(main, "handle_task_payload", lambda *a: task_calls.append(a))
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: spelling_calls.append(a))
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    response = client.post(
        "/webhook", content=b"not-json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200
    assert task_calls == []
    assert spelling_calls == []
