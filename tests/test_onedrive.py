"""Tests for the OneDrive (Microsoft Graph) client — mocked transport."""

from __future__ import annotations

import httpx

from app.onedrive import OneDriveClient


def make_od(handler, **kw):
    transport = httpx.MockTransport(handler)
    http = httpx.Client(transport=transport)
    return OneDriveClient(
        client_id="cid",
        refresh_token="seed-refresh",
        tenant="common",
        folder="WhatsApp Files",
        http=http,
        **kw,
    )


def _token_response():
    return httpx.Response(200, json={
        "access_token": "AT", "expires_in": 3600, "refresh_token": "rotated-refresh",
    })


def test_upload_puts_to_the_folder_path():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return _token_response()
        if request.method == "PUT":
            seen["url"] = str(request.url)
            seen["body"] = request.content
            return httpx.Response(201, json={"name": "notes.pdf"})
        # _ensure_folder GET — say it already exists.
        return httpx.Response(200, json={"id": "folder"})

    od = make_od(handler)
    out = od.upload("notes.pdf", b"PDFDATA", "application/pdf")
    assert out["name"] == "notes.pdf"
    assert "notes.pdf" in seen["url"]
    assert "WhatsApp" in seen["url"]
    assert seen["body"] == b"PDFDATA"


def test_refresh_token_is_rotated_and_persisted(tmp_path):
    token_file = tmp_path / "od.txt"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return _token_response()
        return httpx.Response(200, json={"id": "folder"})

    od = make_od(handler, token_path=str(token_file))
    od._access_token()
    assert od.refresh_token == "rotated-refresh"
    assert token_file.read_text() == "rotated-refresh"


def test_list_files_filters_out_folders():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return _token_response()
        return httpx.Response(200, json={"value": [
            {"name": "a.pdf", "size": 10, "id": "1"},
            {"name": "sub", "id": "2", "folder": {"childCount": 0}},
            {"name": "b.txt", "size": 5, "id": "3"},
        ]})

    names = [f["name"] for f in make_od(handler).list_files()]
    assert names == ["a.pdf", "b.txt"]


def test_download_resolves_partial_name_and_returns_bytes():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return _token_response()
        p = request.url.path
        if p.endswith("/children"):
            return httpx.Response(200, json={"value": [
                {"name": "Final Notes.pdf", "size": 9, "id": "xyz"},
            ]})
        if p.endswith("/items/xyz"):
            return httpx.Response(200, json={"file": {"mimeType": "application/pdf"}})
        if p.endswith("/items/xyz/content"):
            return httpx.Response(200, content=b"THEPDF")
        return httpx.Response(404)

    got = make_od(handler).download("final notes")  # partial, different case
    assert got is not None
    data, ctype, name = got
    assert data == b"THEPDF"
    assert ctype == "application/pdf"
    assert name == "Final Notes.pdf"


def test_download_missing_returns_none():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "login.microsoftonline.com":
            return _token_response()
        return httpx.Response(200, json={"value": []})

    assert make_od(handler).download("nope.pdf") is None
