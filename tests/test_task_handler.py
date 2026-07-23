from services.classifier import ClassificationResult, ClassifierError
from handlers.task_handler import handle_webhook_payload

GROUP_JID = "120363429440515454@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"
SENDER_JID = "573001112233@s.whatsapp.net"
ASSIGNEE_JID = "573004445566@s.whatsapp.net"


class FakeRoster:
    def __init__(self, known_jids: dict[str, str]):
        self._known = known_jids

    def is_known_sender(self, jid):
        return jid in self._known

    def resolve_name(self, jid):
        return self._known.get(jid)

    def same_person(self, jid_a, jid_b):
        return jid_a == jid_b


class FakeSheetsClient:
    def __init__(self, fail=False):
        self.fail = fail
        self.appended = []

    def append_task(self, **kwargs):
        if self.fail:
            raise RuntimeError("sheets down")
        self.appended.append(kwargs)


def _payload(text, sender_jid=SENDER_JID, mentioned_jids=None, group_jid=GROUP_JID, from_me=False):
    return {
        "data": {
            "key": {"remoteJid": group_jid, "participant": sender_jid, "fromMe": from_me},
            "message": {
                "extendedTextMessage": {
                    "text": text,
                    "contextInfo": {"mentionedJid": mentioned_jids or []},
                }
            }
            if mentioned_jids
            else {"conversation": text},
        }
    }


def test_ignores_message_from_unknown_sender(monkeypatch):
    roster = FakeRoster({})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: (_ for _ in ()).throw(AssertionError("should not classify")),
    )

    handle_webhook_payload(_payload("Cristian revisa el stand"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended == []


def test_ignores_message_from_other_group(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()

    handle_webhook_payload(
        _payload("Cristian revisa el stand", group_jid=OTHER_GROUP_JID),
        roster,
        sheets_client,
        GROUP_JID,
    )

    assert sheets_client.appended == []


def test_ignores_own_messages(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()

    handle_webhook_payload(
        _payload("aviso de error", from_me=True), roster, sheets_client, GROUP_JID
    )

    assert sheets_client.appended == []


def test_ignores_non_task_message(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=False, descripcion=None, fecha_limite=None
        ),
    )

    handle_webhook_payload(_payload("jajaja buenísimo"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended == []


def test_saves_task_with_assignee_from_mention(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite="2026-07-24"
        ),
    )

    handle_webhook_payload(
        _payload("revisa el stand mañana @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        sheets_client,
        GROUP_JID,
    )

    assert len(sheets_client.appended) == 1
    saved = sheets_client.appended[0]
    assert saved["reporter"] == "Ana"
    assert saved["description"] == "Revisar el stand"
    assert saved["assignee"] == "Cristian"
    assert saved["due_date"] == "2026-07-24"
    assert saved["status"] == "Pendiente"


def test_self_mention_does_not_self_assign(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Avisarle a alguien", fecha_limite=None
        ),
    )

    handle_webhook_payload(
        _payload("recuérdame @Ana avisarle a alguien", mentioned_jids=[SENDER_JID]),
        roster,
        sheets_client,
        GROUP_JID,
    )

    assert sheets_client.appended[0]["assignee"] == "Sin asignar"


def test_unresolvable_mention_falls_back_to_unassigned(monkeypatch):
    unknown_jid = "573007778899@s.whatsapp.net"
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )

    handle_webhook_payload(
        _payload("revisa el stand @alguien", mentioned_jids=[unknown_jid]),
        roster,
        sheets_client,
        GROUP_JID,
    )

    assert sheets_client.appended[0]["assignee"] == "Sin asignar"


def test_saves_task_as_unassigned_when_no_mention(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )

    handle_webhook_payload(_payload("hay que revisar el stand"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended[0]["assignee"] == "Sin asignar"


def test_ignores_classifier_errors_without_saving(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient()

    def raise_error(text, date, **kw):
        raise ClassifierError("timeout")

    monkeypatch.setattr("handlers.task_handler.classify_message", raise_error)

    handle_webhook_payload(_payload("algo"), roster, sheets_client, GROUP_JID)

    assert sheets_client.appended == []


def test_sends_warning_when_sheets_write_fails(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"})
    sheets_client = FakeSheetsClient(fail=True)
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.task_handler.send_text_message", lambda group_jid, text: sent.append(text)
    )

    handle_webhook_payload(_payload("hay que revisar el stand"), roster, sheets_client, GROUP_JID)

    assert len(sent) == 1
    assert "no pude guardar" in sent[0].lower()
