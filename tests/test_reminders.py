"""Tests for reminders (scheduling, listing, cancelling, firing)."""

from __future__ import annotations

from datetime import datetime, timezone

from apscheduler.schedulers.background import BackgroundScheduler

from app import reminders


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, text, to=None):
        self.sent.append(text)


def make_service():
    # A scheduler we don't start — jobs are stored but never auto-fire in tests.
    scheduler = BackgroundScheduler(timezone="UTC")
    sms = FakeSms()
    service = reminders.ReminderService(scheduler=scheduler, sms=sms)
    return service, sms


def test_schedule_parses_iso_with_timezone_and_stores_job():
    service, _ = make_service()
    rid = service.schedule("2026-06-10T06:59:00+00:00", "CSE 163 homework — due in 1 hr")
    listed = service.list()
    assert len(listed) == 1
    assert listed[0]["id"] == rid
    assert listed[0]["message"] == "CSE 163 homework — due in 1 hr"
    assert listed[0]["when"] == datetime(2026, 6, 10, 6, 59, tzinfo=timezone.utc)


def test_naive_time_is_treated_as_pacific():
    service, _ = make_service()
    service.schedule("2026-06-09T23:59:00", "study time")
    # 2026-06-09 23:59 Pacific (PDT, -7) == 2026-06-10 06:59 UTC.
    when = service.list()[0]["when"]
    assert when == datetime(2026, 6, 10, 6, 59, tzinfo=timezone.utc)


def test_cancel_removes_the_reminder():
    service, _ = make_service()
    rid = service.schedule("2026-06-10T06:59:00+00:00", "x")
    assert service.cancel(rid) is True
    assert service.list() == []
    assert service.cancel(rid) is False  # already gone


def test_firing_sends_the_text():
    service, sms = make_service()
    reminders.fire_reminder("CSE 163 homework — due in 1 hr")
    assert sms.sent == ["CSE 163 homework — due in 1 hr"]


# --- ToolBox integration -----------------------------------------------------

def test_tool_names_and_schemas():
    service, _ = make_service()
    names = set(service.tool_names())
    assert {"set_reminder", "list_reminders", "cancel_reminder"} == names
    schema_names = {s["name"] for s in service.schemas()}
    assert schema_names == names


def test_dispatch_set_reminder_confirms():
    service, _ = make_service()
    out = service.dispatch(
        "set_reminder",
        {"when": "2026-06-10T06:59:00+00:00", "message": "CSE 163 hw — due in 1 hr"},
    )
    assert "set" in out.lower() or "ok" in out.lower()
    assert len(service.list()) == 1


def test_dispatch_list_reminders_when_empty():
    service, _ = make_service()
    out = service.dispatch("list_reminders", {})
    assert "no reminders" in out.lower()
