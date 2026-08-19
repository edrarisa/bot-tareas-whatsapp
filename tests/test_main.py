from fastapi.testclient import TestClient

import main


def _set_common_state():
    main.app.state.roster = "fake-roster"
    main.app.state.lid_resolver = "fake-lid-resolver"
    main.app.state.sheets_client = "fake-sheets-client"
    main.app.state.group_registry = "fake-group-registry"
    main.app.state.personal_task_writer = "fake-personal-task-writer"
    main.app.state.image_batch_buffer = "fake-image-batch-buffer"
    main.app.state.seen_spelling_messages = "fake-seen-spelling-messages"


def test_webhook_delegates_to_both_handlers(monkeypatch):
    task_calls = []
    spelling_calls = []

    def fake_task_handler(payload, roster, lid_resolver, group_registry, personal_task_writer):
        task_calls.append((payload, roster, lid_resolver, group_registry, personal_task_writer))

    def fake_spelling_handler(payload, roster, lid_resolver, group_registry, batch_buffer, seen_messages):
        spelling_calls.append(
            (payload, roster, lid_resolver, group_registry, batch_buffer, seen_messages)
        )

    monkeypatch.setattr(main, "handle_task_payload", fake_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    _set_common_state()

    client = TestClient(main.app)
    body = {"event": "messages.upsert", "data": {}}
    response = client.post("/webhook", json=body)

    assert response.status_code == 200
    assert task_calls == [
        (body, "fake-roster", "fake-lid-resolver", "fake-group-registry", "fake-personal-task-writer")
    ]
    assert spelling_calls == [
        (
            body,
            "fake-roster",
            "fake-lid-resolver",
            "fake-group-registry",
            "fake-image-batch-buffer",
            "fake-seen-spelling-messages",
        )
    ]


def test_webhook_returns_200_even_if_task_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, group_registry, personal_task_writer):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", raising_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: None)
    _set_common_state()

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_webhook_returns_200_even_if_spelling_handler_raises(monkeypatch):
    def raising_handler(payload, roster, lid_resolver, group_registry, batch_buffer, seen_messages):
        raise RuntimeError("boom")

    monkeypatch.setattr(main, "handle_task_payload", lambda *a: None)
    monkeypatch.setattr(main, "handle_spelling_payload", raising_handler)
    _set_common_state()

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200


def test_spelling_handler_still_runs_when_task_handler_raises(monkeypatch):
    """The two handlers are independent -- one failing must not block the other."""
    spelling_calls = []

    def raising_task_handler(payload, roster, lid_resolver, group_registry, personal_task_writer):
        raise RuntimeError("boom")

    def fake_spelling_handler(payload, roster, lid_resolver, group_registry, batch_buffer, seen_messages):
        spelling_calls.append(payload)

    monkeypatch.setattr(main, "handle_task_payload", raising_task_handler)
    monkeypatch.setattr(main, "handle_spelling_payload", fake_spelling_handler)
    _set_common_state()

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
    _set_common_state()

    client = TestClient(main.app)
    response = client.post(
        "/webhook", content=b"not-json", headers={"Content-Type": "application/json"}
    )

    assert response.status_code == 200
    assert task_calls == []
    assert spelling_calls == []


def test_handlers_are_dispatched_via_threadpool(monkeypatch):
    """Handlers do blocking I/O (OpenAI, Sheets, Evolution) -- they must run
    off the event loop via run_in_threadpool, not be called directly."""
    dispatched_funcs = []

    async def fake_run_in_threadpool(func, *args):
        dispatched_funcs.append(func)
        return func(*args)

    monkeypatch.setattr(main, "run_in_threadpool", fake_run_in_threadpool)
    monkeypatch.setattr(main, "handle_task_payload", lambda *a: None)
    monkeypatch.setattr(main, "handle_spelling_payload", lambda *a: None)
    _set_common_state()

    client = TestClient(main.app)
    response = client.post("/webhook", json={"event": "messages.upsert", "data": {}})

    assert response.status_code == 200
    assert main.handle_task_payload in dispatched_funcs
    assert main.handle_spelling_payload in dispatched_funcs
