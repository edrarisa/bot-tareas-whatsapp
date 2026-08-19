import re

from services.classifier import ClassificationResult, ClassifierError, QuotaExceededError
from handlers.task_handler import handle_webhook_payload

GROUP_JID = "120363429440515454@g.us"
OTHER_GROUP_JID = "120363999999999@g.us"
SENDER_JID = "573001112233@s.whatsapp.net"
ASSIGNEE_JID = "573004445566@s.whatsapp.net"


class FakeRoster:
    def __init__(self, known_jids: dict[str, str], sheet_ids: dict[str, str] | None = None):
        self._known = known_jids
        self._sheet_ids = sheet_ids or {}

    def is_known_sender(self, jid):
        return jid in self._known

    def resolve_name(self, jid):
        return self._known.get(jid)

    def resolve_personal_sheet_id(self, jid):
        return self._sheet_ids.get(jid)

    def same_person(self, jid_a, jid_b):
        return jid_a == jid_b


class FakeLidResolver:
    """Passthrough by default; pass a mapping to simulate real @lid -> phone
    JID resolution."""

    def __init__(self, mapping: dict[str, str] | None = None):
        self._mapping = mapping or {}

    def resolve(self, jid, group_jid):
        return self._mapping.get(jid, jid)


class FakeGroupRegistry:
    def __init__(self, mapping: dict[str, str]):
        self._mapping = mapping

    def get_client_name(self, group_jid):
        return self._mapping.get(group_jid)


class FakePersonalTaskWriter:
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
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: (_ for _ in ()).throw(AssertionError("should not classify")),
    )

    handle_webhook_payload(
        _payload("Cristian revisa el stand"), roster, lid_resolver, group_registry, task_writer
    )

    assert task_writer.appended == []


def test_ignores_message_from_unmapped_group(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    handle_webhook_payload(
        _payload("Cristian revisa el stand", group_jid=OTHER_GROUP_JID),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []


def test_ignores_own_messages(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    handle_webhook_payload(
        _payload("aviso de error", from_me=True), roster, lid_resolver, group_registry, task_writer
    )

    assert task_writer.appended == []


def test_ignores_non_task_message(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=False, descripcion=None, fecha_limite=None
        ),
    )

    handle_webhook_payload(
        _payload("jajaja buenísimo @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []


def test_saves_task_to_assignees_personal_sheet_under_client_tab(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite="2026-07-24"
        ),
    )

    handle_webhook_payload(
        _payload("revisa el stand mañana @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    saved = task_writer.appended[0]
    assert saved["sheet_id"] == "sheet-cristian"
    assert saved["client_tab"] == "clinicachia"
    assert saved["reporter"] == "Ana"
    assert saved["description"] == "Revisar el stand"
    assert saved["due_date"] == "2026-07-24"
    assert saved["due_time"] is None
    assert saved["status"] == "Pendiente"


def test_saves_task_with_due_time(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True,
            descripcion="Revisar el código de Bancamía",
            fecha_limite="2026-08-10",
            hora_limite="18:00",
        ),
    )

    handle_webhook_payload(
        _payload(
            "revisa el código de bancamía antes de las 6 pm @Cristian",
            mentioned_jids=[ASSIGNEE_JID],
        ),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    assert task_writer.appended[0]["due_time"] == "18:00"


def test_resolves_lid_mentions_and_sender_before_matching_roster(monkeypatch):
    """The real-world case that broke in production: WhatsApp sends '@lid'
    identifiers instead of phone JIDs for the sender and for mentions."""
    sender_lid = "151556578083034@lid"
    assignee_lid = "203744859922485@lid"
    roster = FakeRoster(
        {SENDER_JID: "Eduar", ASSIGNEE_JID: "Gustavo"},
        {ASSIGNEE_JID: "sheet-gustavo"},
    )
    lid_resolver = FakeLidResolver({sender_lid: SENDER_JID, assignee_lid: ASSIGNEE_JID})
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        ),
    )

    handle_webhook_payload(
        _payload(
            "revisa el stand @Gustavo",
            sender_jid=sender_lid,
            mentioned_jids=[assignee_lid],
        ),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    saved = task_writer.appended[0]
    assert saved["reporter"] == "Eduar"
    assert saved["sheet_id"] == "sheet-gustavo"


def test_self_mention_warns_instead_of_saving(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion="Avisarle a alguien", fecha_limite=None
        ),
    )
    sent = []
    monkeypatch.setattr(
        "handlers.task_handler.send_text_message", lambda group_jid, text: sent.append(text)
    )

    handle_webhook_payload(
        _payload("recuérdame @Ana avisarle a alguien", mentioned_jids=[SENDER_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "no pude identificar a quién asignar" in sent[0].lower()


def test_unresolvable_mention_warns_instead_of_saving(monkeypatch):
    unknown_jid = "573007778899@s.whatsapp.net"
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
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

    handle_webhook_payload(
        _payload("revisa el stand @alguien", mentioned_jids=[unknown_jid]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "no pude identificar a quién asignar" in sent[0].lower()


def test_warns_when_assignee_has_no_personal_sheet_configured(monkeypatch):
    roster = FakeRoster({SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"})  # no sheet_ids passed
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
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

    handle_webhook_payload(
        _payload("revisa el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "no encontré la hoja personal de cristian" in sent[0].lower()


def test_ignores_messages_with_no_mention_without_calling_classifier(monkeypatch):
    """A mention is required for a message to even be considered a possible
    task -- messages with no '@' at all should never reach the classifier
    (saves an unnecessary OpenAI call) or get saved."""
    roster = FakeRoster({SENDER_JID: "Ana"}, {SENDER_JID: "sheet-ana"})
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: (_ for _ in ()).throw(AssertionError("should not classify")),
    )

    handle_webhook_payload(
        _payload("hay que revisar el stand"), roster, lid_resolver, group_registry, task_writer
    )

    assert task_writer.appended == []


def test_ignores_classifier_errors_without_saving(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    def raise_error(text, date, **kw):
        raise ClassifierError("timeout")

    monkeypatch.setattr("handlers.task_handler.classify_message", raise_error)

    handle_webhook_payload(
        _payload("algo @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []


def test_warns_the_group_when_classifier_is_out_of_quota(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()

    def raise_quota_error(text, date, **kw):
        raise QuotaExceededError("insufficient_quota")

    monkeypatch.setattr("handlers.task_handler.classify_message", raise_quota_error)
    sent = []
    monkeypatch.setattr(
        "handlers.task_handler.send_text_message", lambda group_jid, text: sent.append(text)
    )

    handle_webhook_payload(
        _payload("algo @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert task_writer.appended == []
    assert len(sent) == 1
    assert "sin créditos" in sent[0].lower()


def test_created_at_and_classifier_date_share_the_same_moment(monkeypatch):
    """created_at (date + time, for the Sheet) and the date passed to the
    classifier (date only, for resolving 'mañana'/'el viernes') must come
    from a single `datetime.now()` call, not two separate ones that could
    disagree across a midnight boundary."""
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    captured = {}

    def fake_classify(text, date, **kw):
        captured["classify_date"] = date
        return ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        )

    monkeypatch.setattr("handlers.task_handler.classify_message", fake_classify)

    handle_webhook_payload(
        _payload("hay que revisar el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    created_at = task_writer.appended[0]["created_at"]
    assert created_at.startswith(captured["classify_date"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2} \d{2}:\d{2}", created_at)


def test_today_is_computed_using_configured_timezone(monkeypatch):
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from config import Config

    monkeypatch.setattr(Config, "TIMEZONE", "Pacific/Kiritimati")
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    captured = {}

    def fake_classify(text, date, **kw):
        captured["classify_date"] = date
        return ClassificationResult(
            es_tarea=True, descripcion="Revisar el stand", fecha_limite=None
        )

    monkeypatch.setattr("handlers.task_handler.classify_message", fake_classify)

    handle_webhook_payload(
        _payload("hay que revisar el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    expected = datetime.now(ZoneInfo("Pacific/Kiritimati")).date().isoformat()
    assert captured["classify_date"] == expected


def test_processes_multiple_messages_in_one_payload(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True, descripcion=text, fecha_limite=None
        ),
    )

    payload = {
        "data": [
            {
                "key": {"remoteJid": GROUP_JID, "participant": SENDER_JID, "fromMe": False},
                "message": {
                    "extendedTextMessage": {
                        "text": "primera tarea @Cristian",
                        "contextInfo": {"mentionedJid": [ASSIGNEE_JID]},
                    }
                },
            },
            {
                "key": {"remoteJid": GROUP_JID, "participant": SENDER_JID, "fromMe": False},
                "message": {
                    "extendedTextMessage": {
                        "text": "segunda tarea @Cristian",
                        "contextInfo": {"mentionedJid": [ASSIGNEE_JID]},
                    }
                },
            },
        ]
    }

    handle_webhook_payload(payload, roster, lid_resolver, group_registry, task_writer)

    assert len(task_writer.appended) == 2
    assert task_writer.appended[0]["description"] == "primera tarea @Cristian"
    assert task_writer.appended[1]["description"] == "segunda tarea @Cristian"


def test_sends_warning_when_sheets_write_fails(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter(fail=True)
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

    handle_webhook_payload(
        _payload("hay que revisar el stand @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(sent) == 1
    assert "no pude guardar" in sent[0].lower()


def test_passes_urgency_through_to_personal_task_writer(monkeypatch):
    roster = FakeRoster(
        {SENDER_JID: "Ana", ASSIGNEE_JID: "Cristian"},
        {ASSIGNEE_JID: "sheet-cristian"},
    )
    lid_resolver = FakeLidResolver()
    group_registry = FakeGroupRegistry({GROUP_JID: "clinicachia"})
    task_writer = FakePersonalTaskWriter()
    monkeypatch.setattr(
        "handlers.task_handler.classify_message",
        lambda text, date, **kw: ClassificationResult(
            es_tarea=True,
            descripcion="Enviar el informe",
            fecha_limite="2026-08-10",
            hora_limite=None,
            es_urgente=True,
        ),
    )

    handle_webhook_payload(
        _payload("urgente, envía el informe @Cristian", mentioned_jids=[ASSIGNEE_JID]),
        roster,
        lid_resolver,
        group_registry,
        task_writer,
    )

    assert len(task_writer.appended) == 1
    assert task_writer.appended[0]["is_urgent"] is True
