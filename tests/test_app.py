"""Tests for the FastAPI app (the /sms webhook and friends)."""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import AppDeps, build_app
from app.db import ConversationStore, StudyPageStore, FileStore


class FakeSms:
    def __init__(self, my_number="+12065559876", channel="sms", typing_ok=True):
        self.my_number = my_number
        self.channel = channel
        self.typing_ok = typing_ok
        self.sent = []
        self.media_sent = []
        self.typing_calls = []

    def is_allowed(self, frm):
        from app.sms import numbers_match
        return numbers_match(frm, self.my_number)

    def send(self, text, to=None, media_url=None):
        self.sent.append(text)
        if media_url:
            self.media_sent.append((text, media_url))

    def send_typing(self, message_sid):
        self.typing_calls.append(message_sid)
        return self.typing_ok

    def download_media(self, url):
        return (b"FILEBYTES", "image/jpeg")


class FakeOneDrive:
    folder = "WhatsApp Files"

    def __init__(self, files=None):
        self.uploaded = []
        self._files = files or []  # list of {"name":...}

    def upload(self, name, data, content_type):
        self.uploaded.append({"name": name, "data": data, "content_type": content_type})
        self._files.append({"name": name})
        return {"name": name}

    def list_files(self):
        return list(self._files)

    def download(self, query):
        for f in self._files:
            if query.lower() in f["name"].lower():
                return (b"OUT", "application/pdf", f["name"])
        return None


class FakeBrain:
    def __init__(self, reply="hw4 is due tue 11:59pm"):
        self.reply = reply
        self.seen = []

    def respond(self, user_text, history=None):
        self.seen.append((user_text, history))
        return self.reply


def make_client(tmp_path, require_signature=False):
    sms = FakeSms()
    brain = FakeBrain()
    conversation = ConversationStore(tmp_path / "c.sqlite")
    study = StudyPageStore(tmp_path / "s.sqlite")
    deps = AppDeps(
        sms=sms,
        brain=brain,
        conversation=conversation,
        study=study,
        require_signature=require_signature,
        validate=lambda url, form, sig: True,
    )
    app = build_app(deps)
    return TestClient(app), sms, brain, conversation, study


def test_health(tmp_path):
    client, *_ = make_client(tmp_path)
    assert client.get("/health").json() == {"ok": True}


def test_incoming_text_from_me_gets_a_reply(tmp_path):
    client, sms, brain, conversation, _ = make_client(tmp_path)
    resp = client.post(
        "/sms",
        data={"Body": "what's due this week?", "From": "+12065559876"},
    )
    assert resp.status_code == 200
    # Background work ran: brain answered and the reply was texted back.
    assert brain.seen[0][0] == "what's due this week?"
    assert sms.sent == ["hw4 is due tue 11:59pm"]
    # The exchange was remembered.
    contents = [t["content"] for t in conversation.recent()]
    assert "what's due this week?" in contents
    assert "hw4 is due tue 11:59pm" in contents


def _whatsapp_client(tmp_path, typing_ok=True):
    sms = FakeSms(channel="whatsapp", typing_ok=typing_ok)
    brain = FakeBrain()
    deps = AppDeps(
        sms=sms, brain=brain,
        conversation=ConversationStore(tmp_path / "c.sqlite"),
        study=StudyPageStore(tmp_path / "s.sqlite"),
        require_signature=False, validate=lambda u, f, s: True,
    )
    return TestClient(build_app(deps)), sms, brain


def test_whatsapp_shows_typing_indicator(tmp_path):
    client, sms, brain = _whatsapp_client(tmp_path)
    client.post(
        "/sms",
        data={"Body": "what's due?", "From": "+12065559876", "MessageSid": "SMabc123"},
    )
    # The 'typing…' animation was triggered for the inbound message, no filler text.
    assert sms.typing_calls == ["SMabc123"]
    assert sms.sent == ["hw4 is due tue 11:59pm"]


def test_typing_falls_back_to_text_when_unsupported(tmp_path):
    client, sms, brain = _whatsapp_client(tmp_path, typing_ok=False)
    client.post(
        "/sms",
        data={"Body": "hi", "From": "+12065559876", "MessageSid": "SMabc"},
    )
    # Native indicator refused → a quick "on it" text shows instead, plus the reply.
    assert "on it 🤔" in sms.sent
    assert "hw4 is due tue 11:59pm" in sms.sent


def test_no_typing_without_a_message_sid(tmp_path):
    client, sms, brain = _whatsapp_client(tmp_path)
    client.post("/sms", data={"Body": "hi", "From": "+12065559876"})
    assert sms.typing_calls == []


class FakeReminders:
    def __init__(self):
        self.cleared = 0

    def clear_all(self):
        self.cleared += 1
        return 3


def _client_with_reminders(tmp_path):
    from app.main import AppDeps, build_app
    from fastapi.testclient import TestClient

    sms = FakeSms()
    brain = FakeBrain()
    conversation = ConversationStore(tmp_path / "c.sqlite")
    study = StudyPageStore(tmp_path / "s.sqlite")
    reminders = FakeReminders()
    deps = AppDeps(
        sms=sms, brain=brain, conversation=conversation, study=study,
        require_signature=False, validate=lambda u, f, s: True, reminders=reminders,
    )
    return TestClient(build_app(deps)), sms, brain, conversation, study, reminders


def test_clear_clears_only_the_chat(tmp_path):
    client, sms, brain, conversation, study, reminders = _client_with_reminders(tmp_path)
    conversation.save("user", "old message")
    study.save("p1", "Flashcards", "<html>cards</html>")

    resp = client.post("/sms", data={"Body": "CLEAR", "From": "+12065559876"})
    assert resp.status_code == 200
    # Chat wiped; study pages and reminders left alone; brain not consulted.
    assert conversation.recent() == []
    assert study.get("p1") is not None
    assert reminders.cleared == 0
    assert brain.seen == []
    assert sms.sent and "chat" in sms.sent[0].lower()


def test_clear_reminders_clears_only_reminders(tmp_path):
    client, sms, brain, conversation, study, reminders = _client_with_reminders(tmp_path)
    conversation.save("user", "keep me")

    client.post("/sms", data={"Body": "clear reminders", "From": "+12065559876"})
    assert reminders.cleared == 1
    assert conversation.recent() != []  # chat untouched
    assert brain.seen == []
    assert "reminder" in sms.sent[0].lower()


def test_clear_all_wipes_everything(tmp_path):
    client, sms, brain, conversation, study, reminders = _client_with_reminders(tmp_path)
    conversation.save("user", "old")
    study.save("p1", "T", "<html>x</html>")

    client.post("/sms", data={"Body": "clear all", "From": "+12065559876"})
    assert conversation.recent() == []
    assert study.get("p1") is None
    assert reminders.cleared == 1
    assert brain.seen == []
    assert "everything" in sms.sent[0].lower()


def _client_with_onedrive(tmp_path, files=None):
    sms = FakeSms()
    brain = FakeBrain()
    onedrive = FakeOneDrive(files=files)
    deps = AppDeps(
        sms=sms, brain=brain,
        conversation=ConversationStore(tmp_path / "c.sqlite"),
        study=StudyPageStore(tmp_path / "s.sqlite"),
        files=FileStore(tmp_path / "f.sqlite"),
        onedrive=onedrive, public_base_url="https://app.example",
        require_signature=False, validate=lambda u, f, s: True,
    )
    return TestClient(build_app(deps)), sms, brain, onedrive


def test_incoming_file_is_saved_to_onedrive(tmp_path):
    client, sms, brain, onedrive = _client_with_onedrive(tmp_path)
    resp = client.post("/sms", data={
        "From": "+12065559876", "Body": "",
        "NumMedia": "1",
        "MediaUrl0": "https://api.twilio.com/media/abc",
        "MediaContentType0": "image/jpeg",
    })
    assert resp.status_code == 200
    assert len(onedrive.uploaded) == 1
    assert onedrive.uploaded[0]["data"] == b"FILEBYTES"
    assert onedrive.uploaded[0]["name"].endswith(".jpg")
    assert brain.seen == []  # a file shouldn't go to the brain
    assert sms.sent and "saved" in sms.sent[0].lower()


def test_files_command_lists_the_folder(tmp_path):
    client, sms, *_ = _client_with_onedrive(tmp_path, files=[{"name": "essay.docx"}])
    client.post("/sms", data={"From": "+12065559876", "Body": "files"})
    assert sms.sent and "essay.docx" in sms.sent[0]


def test_send_command_delivers_the_file_as_media(tmp_path):
    client, sms, brain, _ = _client_with_onedrive(tmp_path, files=[{"name": "notes.pdf"}])
    client.post("/sms", data={"From": "+12065559876", "Body": "send notes.pdf"})
    assert sms.media_sent, "should have sent a file as media"
    text, media_url = sms.media_sent[0]
    assert "notes.pdf" in text
    assert media_url[0].startswith("https://app.example/file/")
    assert brain.seen == []


def test_serve_file_route_returns_bytes(tmp_path):
    client, sms, brain, _ = _client_with_onedrive(tmp_path, files=[{"name": "notes.pdf"}])
    client.post("/sms", data={"From": "+12065559876", "Body": "send notes.pdf"})
    _, media_url = sms.media_sent[0]
    path = media_url[0].split("https://app.example")[1]
    resp = client.get(path)
    assert resp.status_code == 200
    assert resp.content == b"OUT"


def test_get_me_my_grade_falls_through_to_brain(tmp_path):
    # "get ..." without a filename-looking arg should NOT be treated as a file request.
    client, sms, brain, _ = _client_with_onedrive(tmp_path)
    client.post("/sms", data={"From": "+12065559876", "Body": "get me my grade"})
    assert brain.seen and brain.seen[0][0] == "get me my grade"


def test_text_from_a_stranger_is_ignored(tmp_path):
    client, sms, brain, *_ = make_client(tmp_path)
    resp = client.post("/sms", data={"Body": "hi", "From": "+19999999999"})
    assert resp.status_code == 200
    assert sms.sent == []
    assert brain.seen == []


def test_prior_conversation_is_passed_as_history(tmp_path):
    client, sms, brain, conversation, _ = make_client(tmp_path)
    conversation.save("user", "what's due?")
    conversation.save("assistant", "hw4 for 163")
    client.post("/sms", data={"Body": "what's that asking?", "From": "+12065559876"})
    _, history = brain.seen[0]
    assert {"role": "user", "content": "what's due?"} in history
    assert {"role": "assistant", "content": "hw4 for 163"} in history


def test_bad_signature_is_rejected(tmp_path):
    sms = FakeSms()
    brain = FakeBrain()
    deps = AppDeps(
        sms=sms,
        brain=brain,
        conversation=ConversationStore(tmp_path / "c.sqlite"),
        study=StudyPageStore(tmp_path / "s.sqlite"),
        require_signature=True,
        validate=lambda url, form, sig: False,  # always reject
    )
    client = TestClient(build_app(deps))
    resp = client.post(
        "/sms",
        data={"Body": "hi", "From": "+12065559876"},
        headers={"X-Twilio-Signature": "bogus"},
    )
    assert resp.status_code == 403
    assert brain.seen == []


def test_study_page_served_when_present(tmp_path):
    client, sms, brain, conversation, study = make_client(tmp_path)
    study.save("abc123", "Flashcards", "<html><body>cards</body></html>")
    resp = client.get("/study/abc123")
    assert resp.status_code == 200
    assert "cards" in resp.text


def test_missing_study_page_is_404(tmp_path):
    client, *_ = make_client(tmp_path)
    assert client.get("/study/nope").status_code == 404
