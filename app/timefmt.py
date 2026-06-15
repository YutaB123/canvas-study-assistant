"""Casual, human phrasing of due dates — always shown in Pacific time.

Kept tiny and pure so it's easy to test and reuse (tools + reminders).
"""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

PACIFIC = ZoneInfo("America/Los_Angeles")


def _clock(dt_local: datetime) -> str:
    """e.g. '11:59pm', '9am'."""
    hour = dt_local.hour % 12 or 12
    ampm = "am" if dt_local.hour < 12 else "pm"
    if dt_local.minute:
        return f"{hour}:{dt_local.minute:02d}{ampm}"
    return f"{hour}{ampm}"


def human_due(due_at: datetime | None, now: datetime | None = None) -> str:
    if due_at is None:
        return "no due date"
    if now is None:
        now = datetime.now(timezone.utc)

    delta = due_at - now
    seconds = delta.total_seconds()

    if seconds < 0:
        return "overdue"

    minutes = int(seconds // 60)
    if minutes < 60:
        return f"in {minutes} min"

    hours = int(seconds // 3600)
    if hours < 24:
        return f"in {hours} hr"

    local = due_at.astimezone(PACIFIC)
    if seconds < 7 * 24 * 3600:
        return f"{local:%a} {_clock(local)}"

    # %-d isn't portable on Windows; build the day number by hand.
    return f"{local:%b} {local.day}"


def human_when(when: datetime | None, now: datetime | None = None) -> str:
    """Casual phrasing of a PAST timestamp — for announcements and inbox messages."""
    if when is None:
        return "recently"
    if now is None:
        now = datetime.now(timezone.utc)

    seconds = (now - when).total_seconds()
    if seconds < 0:
        # Future timestamp — fall back to due-style phrasing.
        return human_due(when, now)

    minutes = int(seconds // 60)
    if minutes < 60:
        return f"{max(minutes, 1)} min ago"

    hours = int(seconds // 3600)
    if hours < 24:
        return f"{hours} hr ago"

    local = when.astimezone(PACIFIC)
    if seconds < 7 * 24 * 3600:
        return f"{local:%a}"

    return f"{local:%b} {local.day}"
