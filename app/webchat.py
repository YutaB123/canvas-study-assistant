"""The web channel: a stand-in for SmsClient that talks to the browser.

The rest of the app (brain, documents, reminders) only knows how to call
`sms.send(...)`. For the web app we hand them this WebClient instead: every
"send" just appends a message to the WebChatStore, which the chat page reads
and polls. No Twilio, no phone numbers, no carrier — just your own page.
"""

from __future__ import annotations

from typing import Any


class WebClient:
    channel = "web"

    def __init__(self, store: Any, push: Any = None):
        # store is a WebChatStore (append/since/max_id/clear).
        # push is an optional PushService (notify when the app is closed).
        self.store = store
        self.push = push

    def send(
        self, text: str, to: str | None = None, media_url: list[str] | None = None
    ) -> None:
        """Deliver an assistant message to the browser by storing it (and a push)."""
        self.store.append("assistant", text or "", (media_url or [""])[0])
        if self.push is not None and (text or media_url):
            preview = (text or "sent you a file").strip()
            if len(preview) > 120:
                preview = preview[:117] + "…"
            self.push.notify("Study Assistant", preview)

    def send_typing(self, message_sid: str) -> bool:
        # The web UI shows its own typing dots while it waits for the reply.
        return False

    def download_media(self, url: str) -> tuple[bytes, str]:
        # Inbound files over the web aren't routed through here (v1).
        return b"", "application/octet-stream"

    def is_allowed(self, from_number: str) -> bool:
        # The web app authenticates with a shared secret, not a phone number.
        # Returning False keeps the dormant Twilio /sms webhook from acting.
        return False

    def validate_signature(self, url: str, form: dict, signature: str) -> bool:
        return False
