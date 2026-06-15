"""Web push: buzz the phone with a notification even when the app is closed.

Uses the Web Push protocol (VAPID) via pywebpush. Sending happens in a
background thread so it never slows down a reply. Dead subscriptions (the
browser unsubscribed / expired) are pruned automatically.
"""

from __future__ import annotations

import json
import threading
from typing import Any


class PushService:
    def __init__(self, store: Any, private_key: str, claim_email: str):
        # store is a PushStore; private_key is the VAPID private key PEM.
        self.store = store
        self.private_key = private_key
        self.claims = {"sub": claim_email or "mailto:admin@example.com"}

    @property
    def enabled(self) -> bool:
        return bool(self.private_key)

    def notify(self, title: str, body: str, url: str = "/chat", force: bool = False) -> None:
        """Fire a notification to every subscribed device (non-blocking).

        force=True tells the service worker to show it even if the app is open
        (used for the 'notifications are on' confirmation)."""
        if not self.enabled:
            return
        threading.Thread(
            target=self.send_sync, args=(title, body, url, force), daemon=True
        ).start()

    def send_sync(
        self, title: str, body: str, url: str = "/chat", force: bool = False
    ) -> list[dict]:
        """Send to every subscription and return a per-device result (for
        diagnostics). Prunes subscriptions the push service says are gone."""
        if not self.enabled:
            return [{"error": "push disabled (no VAPID key)"}]
        from pywebpush import webpush, WebPushException

        payload = json.dumps({"title": title, "body": body, "url": url, "force": force})
        results: list[dict] = []
        for sub in self.store.all():
            tail = (sub.get("endpoint", "") or "")[-14:]
            try:
                resp = webpush(
                    subscription_info=sub,
                    data=payload,
                    vapid_private_key=self.private_key,
                    vapid_claims=dict(self.claims),
                )
                results.append(
                    {"endpoint": tail, "status": getattr(resp, "status_code", None), "error": None}
                )
            except WebPushException as e:
                status = getattr(getattr(e, "response", None), "status_code", None)
                if status in (404, 410):
                    self.store.remove(sub.get("endpoint", ""))
                results.append({"endpoint": tail, "status": status, "error": str(e)[:140]})
            except Exception as e:
                results.append(
                    {"endpoint": tail, "status": None, "error": f"{type(e).__name__}: {str(e)[:100]}"}
                )
        return results
