"""Tests for casual due-date phrasing (always in Pacific time)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from app import timefmt


def at(year, month, day, hour, minute=0):
    """A UTC instant."""
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_no_due_date():
    assert timefmt.human_due(None, now=at(2026, 6, 8, 12)) == "no due date"


def test_overdue():
    due = at(2026, 6, 8, 10)
    now = at(2026, 6, 8, 12)
    assert timefmt.human_due(due, now=now) == "overdue"


def test_minutes_away():
    now = at(2026, 6, 8, 12, 0)
    due = now + timedelta(minutes=45)
    assert timefmt.human_due(due, now=now) == "in 45 min"


def test_one_hour_is_singular():
    now = at(2026, 6, 8, 12, 0)
    due = now + timedelta(hours=1, minutes=5)
    assert timefmt.human_due(due, now=now) == "in 1 hr"


def test_several_hours():
    now = at(2026, 6, 8, 12, 0)
    due = now + timedelta(hours=5)
    assert timefmt.human_due(due, now=now) == "in 5 hr"


def test_within_a_week_shows_weekday_and_pacific_time():
    # 2026-06-10 06:59 UTC == 2026-06-09 (Tue) 23:59 Pacific (PDT, UTC-7).
    due = at(2026, 6, 10, 6, 59)
    now = at(2026, 6, 8, 12)  # Mon
    assert timefmt.human_due(due, now=now) == "Tue 11:59pm"


def test_far_away_shows_month_and_day():
    due = at(2026, 7, 1, 18, 0)  # ~3 weeks out
    now = at(2026, 6, 8, 12)
    assert timefmt.human_due(due, now=now) == "Jul 1"


# --- human_when (past timestamps: announcements / inbox) ---------------------

def test_when_none_reads_recently():
    assert timefmt.human_when(None, now=at(2026, 6, 8, 12)) == "recently"


def test_when_minutes_ago():
    now = at(2026, 6, 8, 12, 0)
    assert timefmt.human_when(now - timedelta(minutes=20), now=now) == "20 min ago"


def test_when_hours_ago():
    now = at(2026, 6, 8, 12, 0)
    assert timefmt.human_when(now - timedelta(hours=5), now=now) == "5 hr ago"


def test_when_within_week_shows_weekday():
    # 3 days before Mon 2026-06-08 == Fri.
    now = at(2026, 6, 8, 12, 0)
    assert timefmt.human_when(now - timedelta(days=3), now=now) == "Fri"


def test_when_far_back_shows_month_and_day():
    now = at(2026, 6, 8, 12, 0)
    assert timefmt.human_when(at(2026, 5, 20, 18, 0), now=now) == "May 20"
