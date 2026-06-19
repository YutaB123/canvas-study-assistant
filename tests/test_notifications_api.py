"""End-to-end test of the notifications menu HTTP endpoints through the app."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from apscheduler.schedulers.background import BackgroundScheduler
from fastapi.testclient import TestClient

from app.main import AppDeps, build_app
from app.db import ChatStore, ConversationStore, StudyPageStore, NotificationStore
from app.notifications import NotificationService
from app.webchat import WebClient


class FakeCanvas:
    def get_upcoming(self, days=7):
        due = datetime.now(timezone.utc) + timedelta(hours=10)
        from app.canvas import Item
        return [Item("CSE 142", "Quiz 4", due, "1:2", "", "assignment")]


def _client(tmp_path):
    chats = ChatStore(tmp_path / "chats.sqlite")
    canvas = FakeCanvas()
    notifications = NotificationService(
        scheduler=BackgroundScheduler(timezone="UTC"),
        store=NotificationStore(tmp_path / "notif.sqlite"),
        canvas=canvas, chats=chats, push=None,
    )
    deps = AppDeps(
        sms=WebClient(chats), brain=None,
        conversation=ConversationStore(tmp_path / "c.sqlite"),
        study=StudyPageStore(tmp_path / "s.sqlite"),
        require_signature=False, validate=lambda u, f, s: True,
        chats=chats, web_chat_secret="k", canvas=canvas,
        notifications=notifications,
    )
    return TestClient(build_app(deps))


H = {"X-Chat-Key": "k"}


def test_notifications_crud_over_http(tmp_path):
    client = _client(tmp_path)

    # starts empty
    assert client.get("/chat/notifications", headers=H).json() == {"rules": []}

    # add a daily digest
    r = client.post("/chat/notifications", headers=H, json={"kind": "daily", "time": "08:00"})
    assert r.status_code == 200
    assert "every day at 8am" in r.json()["label"]

    # add a due-soon rule
    client.post("/chat/notifications", headers=H, json={"kind": "due", "hours_before": 24})
    rules = client.get("/chat/notifications", headers=H).json()["rules"]
    assert len(rules) == 2

    # toggle the first off
    first = rules[0]["id"]
    assert client.post(f"/chat/notifications/{first}/toggle", headers=H).json()["ok"] is True
    after = client.get("/chat/notifications", headers=H).json()["rules"]
    assert next(x for x in after if x["id"] == first)["enabled"] is False

    # delete it
    assert client.delete(f"/chat/notifications/{first}", headers=H).json()["ok"] is True
    assert len(client.get("/chat/notifications", headers=H).json()["rules"]) == 1


def test_notifications_rejects_bad_kind(tmp_path):
    client = _client(tmp_path)
    r = client.post("/chat/notifications", headers=H, json={"kind": "hourly"})
    assert r.status_code == 400


def test_notifications_requires_auth(tmp_path):
    client = _client(tmp_path)
    assert client.get("/chat/notifications").status_code == 401
