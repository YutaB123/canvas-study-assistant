"""A small local memory: the recent conversation, and generated study pages.

Plain SQLite via the standard library. Single user (the whitelist guarantees
that), so no per-user keys are needed.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path


class ConversationStore:
    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS conversation (
                id      INTEGER PRIMARY KEY AUTOINCREMENT,
                role    TEXT NOT NULL,
                content TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def save(self, role: str, content: str) -> None:
        self._db.execute(
            "INSERT INTO conversation (role, content) VALUES (?, ?)",
            (role, content),
        )
        self._db.commit()

    def recent(self, limit: int = 12) -> list[dict]:
        rows = self._db.execute(
            "SELECT role, content FROM conversation ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        # Pulled newest-first for the LIMIT; hand back oldest-first.
        return [{"role": r, "content": c} for r, c in reversed(rows)]

    def clear(self) -> None:
        """Forget the whole conversation."""
        self._db.execute("DELETE FROM conversation")
        self._db.commit()


class StudyPageStore:
    """Stores generated flashcard / exam pages, served later at /study/{id}."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS study_page (
                id    TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                html  TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def save(self, page_id: str, title: str, html: str) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO study_page (id, title, html) VALUES (?, ?, ?)",
            (page_id, title, html),
        )
        self._db.commit()

    def get(self, page_id: str) -> str | None:
        row = self._db.execute(
            "SELECT html FROM study_page WHERE id = ?", (page_id,)
        ).fetchone()
        return row[0] if row else None

    def clear(self) -> None:
        """Delete all generated study pages."""
        self._db.execute("DELETE FROM study_page")
        self._db.commit()


class WebChatStore:
    """The visible transcript for the web chat app — what the browser shows.

    Every message (yours and the assistant's, including document links and
    reminders) lands here with an incrementing id, so the page can load the
    history and poll for anything new (like a reminder firing later).
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS web_chat (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                role      TEXT NOT NULL,
                text      TEXT NOT NULL,
                media_url TEXT NOT NULL DEFAULT ''
            )
            """
        )
        self._db.commit()

    def append(self, role: str, text: str, media_url: str = "") -> int:
        cur = self._db.execute(
            "INSERT INTO web_chat (role, text, media_url) VALUES (?, ?, ?)",
            (role, text, media_url),
        )
        self._db.commit()
        return int(cur.lastrowid)

    def since(self, after_id: int = 0) -> list[dict]:
        rows = self._db.execute(
            "SELECT id, role, text, media_url FROM web_chat WHERE id > ? ORDER BY id",
            (after_id,),
        ).fetchall()
        return [
            {"id": i, "role": r, "text": t, "media_url": m} for i, r, t, m in rows
        ]

    def max_id(self) -> int:
        row = self._db.execute("SELECT COALESCE(MAX(id), 0) FROM web_chat").fetchone()
        return int(row[0])

    def clear(self) -> None:
        self._db.execute("DELETE FROM web_chat")
        self._db.commit()


class PushStore:
    """Browser push subscriptions, so the app can notify you when it's closed."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS push_sub (
                endpoint TEXT PRIMARY KEY,
                p256dh   TEXT NOT NULL,
                auth     TEXT NOT NULL
            )
            """
        )
        self._db.commit()

    def save(self, subscription: dict) -> None:
        keys = subscription.get("keys", {})
        self._db.execute(
            "INSERT OR REPLACE INTO push_sub (endpoint, p256dh, auth) VALUES (?, ?, ?)",
            (subscription.get("endpoint", ""), keys.get("p256dh", ""), keys.get("auth", "")),
        )
        self._db.commit()

    def all(self) -> list[dict]:
        rows = self._db.execute(
            "SELECT endpoint, p256dh, auth FROM push_sub"
        ).fetchall()
        return [
            {"endpoint": e, "keys": {"p256dh": p, "auth": a}} for e, p, a in rows
        ]

    def remove(self, endpoint: str) -> None:
        self._db.execute("DELETE FROM push_sub WHERE endpoint = ?", (endpoint,))
        self._db.commit()

    def clear(self) -> None:
        self._db.execute("DELETE FROM push_sub")
        self._db.commit()


class FileStore:
    """Temporarily holds a file's bytes so it can be fetched at a public URL
    (Twilio needs a reachable media_url; the web app links to the same route)."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.execute(
            """
            CREATE TABLE IF NOT EXISTS outbound_file (
                id           TEXT PRIMARY KEY,
                filename     TEXT NOT NULL,
                content_type TEXT NOT NULL,
                data         BLOB NOT NULL
            )
            """
        )
        self._db.commit()

    def save(self, file_id: str, filename: str, content_type: str, data: bytes) -> None:
        self._db.execute(
            "INSERT OR REPLACE INTO outbound_file (id, filename, content_type, data) "
            "VALUES (?, ?, ?, ?)",
            (file_id, filename, content_type, data),
        )
        self._db.commit()

    def get(self, file_id: str) -> tuple[str, str, bytes] | None:
        row = self._db.execute(
            "SELECT filename, content_type, data FROM outbound_file WHERE id = ?",
            (file_id,),
        ).fetchone()
        return (row[0], row[1], row[2]) if row else None
