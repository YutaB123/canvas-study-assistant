"""OneDrive access via Microsoft Graph (delegated, with a stored refresh token).

Lets the assistant drop files the student sends over WhatsApp into a OneDrive folder
(which the student's laptop syncs automatically) and pull files back out to send over
WhatsApp. Uses a public-client refresh token — no client secret needed.
"""

from __future__ import annotations

import os
import time
from urllib.parse import quote

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"


class OneDriveClient:
    def __init__(
        self,
        client_id: str,
        refresh_token: str,
        tenant: str = "common",
        folder: str = "WhatsApp Files",
        http: httpx.Client | None = None,
        token_path: str | None = None,
    ):
        self.client_id = client_id
        self.refresh_token = refresh_token
        self.tenant = tenant
        self.folder = folder
        # Refresh tokens rotate on each use, so persist the latest to disk (on
        # Azure this lives in /home/data, which survives restarts).
        self.token_path = token_path
        if token_path and os.path.exists(token_path):
            try:
                saved = open(token_path).read().strip()
                if saved:
                    self.refresh_token = saved
            except OSError:
                pass
        self._http = http or httpx.Client(timeout=60.0)
        self._token: str | None = None
        self._token_exp = 0.0

    def _persist_refresh(self) -> None:
        if self.token_path:
            try:
                with open(self.token_path, "w") as f:
                    f.write(self.refresh_token)
            except OSError:
                pass

    # --- auth -----------------------------------------------------------------

    def _access_token(self) -> str:
        now = time.time()
        if self._token and now < self._token_exp - 60:
            return self._token
        url = f"https://login.microsoftonline.com/{self.tenant}/oauth2/v2.0/token"
        resp = self._http.post(
            url,
            data={
                "client_id": self.client_id,
                "grant_type": "refresh_token",
                "refresh_token": self.refresh_token,
                "scope": "Files.ReadWrite offline_access",
            },
        )
        resp.raise_for_status()
        data = resp.json()
        self._token = data["access_token"]
        self._token_exp = now + int(data.get("expires_in", 3600))
        # Microsoft rotates the refresh token — hold onto the newest one and persist it.
        if data.get("refresh_token") and data["refresh_token"] != self.refresh_token:
            self.refresh_token = data["refresh_token"]
            self._persist_refresh()
        return self._token

    def _headers(self, extra: dict | None = None) -> dict:
        h = {"Authorization": f"Bearer {self._access_token()}"}
        if extra:
            h.update(extra)
        return h

    # --- folder ---------------------------------------------------------------

    def _ensure_folder(self) -> None:
        check = self._http.get(
            f"{GRAPH}/me/drive/root:/{quote(self.folder, safe='/')}",
            headers=self._headers(),
        )
        if check.status_code == 200:
            return
        # Create the leaf folder inside its parent (handles nested paths like
        # "Documents/whatsapp" — the parent "Documents" already exists).
        if "/" in self.folder:
            parent, leaf = self.folder.rsplit("/", 1)
            url = f"{GRAPH}/me/drive/root:/{quote(parent, safe='/')}:/children"
        else:
            leaf = self.folder
            url = f"{GRAPH}/me/drive/root/children"
        self._http.post(
            url,
            headers=self._headers(),
            json={"name": leaf, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
        )

    # --- operations -----------------------------------------------------------

    def upload(self, name: str, data: bytes, content_type: str = "application/octet-stream") -> dict:
        self._ensure_folder()
        path = f"{GRAPH}/me/drive/root:/{quote(self.folder, safe='/')}/{quote(name)}:/content"
        resp = self._http.put(
            path, content=data, headers=self._headers({"Content-Type": content_type})
        )
        resp.raise_for_status()
        return resp.json()

    def list_files(self) -> list[dict]:
        path = f"{GRAPH}/me/drive/root:/{quote(self.folder, safe='/')}:/children?$select=name,size,id,file"
        resp = self._http.get(path, headers=self._headers())
        if resp.status_code == 404:
            return []  # folder not created yet
        resp.raise_for_status()
        out = []
        for it in resp.json().get("value", []):
            if "folder" in it:
                continue  # only files
            out.append({"name": it.get("name"), "size": it.get("size"), "id": it.get("id")})
        return out

    def download(self, name: str) -> tuple[bytes, str, str] | None:
        """Find a file by exact or partial name; return (bytes, content_type, real_name)."""
        files = self.list_files()
        match = next((f for f in files if f["name"].lower() == name.lower()), None)
        if match is None:
            match = next((f for f in files if name.lower() in f["name"].lower()), None)
        if match is None:
            return None
        meta = self._http.get(
            f"{GRAPH}/me/drive/items/{match['id']}", headers=self._headers()
        ).json()
        ctype = (meta.get("file") or {}).get("mimeType") or "application/octet-stream"
        content = self._http.get(
            f"{GRAPH}/me/drive/items/{match['id']}/content",
            headers=self._headers(),
            follow_redirects=True,
        )
        content.raise_for_status()
        return content.content, ctype, match["name"]
