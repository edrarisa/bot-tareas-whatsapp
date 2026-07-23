from fastapi.testclient import TestClient

import main


def test_webhook_delegates_to_task_handler(monkeypatch):
    received = []

    def fake_handler(payload, roster, sheets_client, group_jid):
        received.append((payload, roster, sheets_client, group_jid))

    monkeypatch.setattr(main, "handle_webhook_payload", fake_handler)
    main.app.state.roster = "fake-roster"
    main.app.state.sheets_client = "fake-sheets-client"
    monkeypatch.setattr(main.Config, "WHATSAPP_GROUP_JID", "120363429440515454@g.us")

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert len(received) == 1
    assert received[0][0] == body
    assert received[0][1] == "fake-roster"
    assert received[0][2] == "fake-sheets-client"
    assert received[0][3] == "120363429440515454@g.us"
