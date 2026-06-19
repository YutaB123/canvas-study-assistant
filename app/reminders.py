"""Reminders: schedule a text to arrive at a chosen time, and have it survive
restarts.

The brain figures out the actual moment (e.g. "an hour before the due date")
and calls set_reminder with an ISO timestamp and the exact text to send.

APScheduler's persistent job store keeps pending reminders across restarts. Its
jobs reference a module-level function (`fire_reminder`) by name, so on restart
they can be re-loaded and still find a live SmsClient.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from app.timefmt import PACIFIC

# The active SmsClient, set when a ReminderService is created. A persisted job
# re-imports this module and calls fire_reminder, which uses this.
_ACTIVE_SMS: Any = None


def fire_reminder(message: str) -> None:
    """The job target. Kept at module level so it's importable by the job store."""
    if _ACTIVE_SMS is not None:
        # force the buzz when we can (web channel) so a scheduled reminder
        # actually notifies even if the app is open; SmsClient ignores the kwarg.
        try:
            _ACTIVE_SMS.send(message, force=True)
        except TypeError:
            _ACTIVE_SMS.send(message)


def _parse_when(when: str) -> datetime:
    dt = datetime.fromisoformat(when)
    if dt.tzinfo is None:
        # A bare time means the student's local (UW / Pacific) time.
        dt = dt.replace(tzinfo=PACIFIC)
    return dt


REMINDER_TOOLS = [
    {
        "name": "set_reminder",
        "description": "Schedule a text to be sent at a specific time. First work "
        "out the real moment from Canvas due dates, then call this. 'when' is an "
        "ISO 8601 timestamp (include a timezone offset if you can; a bare time is "
        "treated as Pacific). 'message' is the exact text to send, e.g. "
        "'CSE 163 homework — due in 1 hr'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "when": {"type": "string", "description": "ISO 8601 time to send the reminder."},
                "message": {"type": "string", "description": "The text to send at that time."},
            },
            "required": ["when", "message"],
        },
    },
    {
        "name": "list_reminders",
        "description": "List the reminders currently scheduled, with their ids.",
        "input_schema": {"type": "object", "properties": {}},
    },
    {
        "name": "cancel_reminder",
        "description": "Cancel a scheduled reminder by its id (from list_reminders).",
        "input_schema": {
            "type": "object",
            "properties": {"id": {"type": "string"}},
            "required": ["id"],
        },
    },
]


class ReminderService:
    def __init__(self, scheduler, sms):
        self.scheduler = scheduler
        self.sms = sms
        global _ACTIVE_SMS
        _ACTIVE_SMS = sms

    # --- core operations -----------------------------------------------------

    def schedule(self, when: str, message: str) -> str:
        run_at = _parse_when(when)
        rid = uuid.uuid4().hex[:8]
        self.scheduler.add_job(
            fire_reminder,
            trigger="date",
            run_date=run_at,
            args=[message],
            id=rid,
            replace_existing=True,
            misfire_grace_time=3600,  # still fire if we were briefly down
        )
        return rid

    def list(self) -> list[dict]:
        out = []
        for job in self.scheduler.get_jobs():
            # run_date lives on the date trigger; next_run_time is only set once
            # the scheduler is running, so prefer the trigger.
            when = getattr(job.trigger, "run_date", None) or getattr(
                job, "next_run_time", None
            )
            out.append(
                {
                    "id": job.id,
                    "when": when,
                    "message": job.args[0] if job.args else "",
                }
            )
        out.sort(key=lambda r: (r["when"] is None, r["when"]))
        return out

    def cancel(self, rid: str) -> bool:
        if self.scheduler.get_job(rid) is None:
            return False
        self.scheduler.remove_job(rid)
        return True

    def clear_all(self) -> int:
        """Cancel every scheduled reminder. Returns how many were removed."""
        jobs = self.scheduler.get_jobs()
        for job in jobs:
            self.scheduler.remove_job(job.id)
        return len(jobs)

    # --- ToolBox integration -------------------------------------------------

    def tool_names(self) -> list[str]:
        return [t["name"] for t in REMINDER_TOOLS]

    def schemas(self) -> list[dict]:
        return list(REMINDER_TOOLS)

    def dispatch(self, name: str, tool_input: dict) -> str:
        if name == "set_reminder":
            rid = self.schedule(tool_input["when"], tool_input["message"])
            return f"ok, reminder set (id {rid})."
        if name == "list_reminders":
            items = self.list()
            if not items:
                return "No reminders scheduled."
            from app.timefmt import human_due

            lines = []
            for r in items:
                lines.append(f"[{r['id']}] {r['message']} — {human_due(r['when'])}")
            return "\n".join(lines)
        if name == "cancel_reminder":
            return "cancelled." if self.cancel(tool_input["id"]) else "no reminder with that id."
        return f"(unknown reminder tool: {name})"
