"""Tests for the make-a-document (PDF) tool."""

from __future__ import annotations

from app.documents import DocumentService, render_pdf
from app.db import FileStore


class FakeSms:
    def __init__(self):
        self.sent = []

    def send(self, text, to=None, media_url=None):
        self.sent.append((text, media_url))


class FakeOneDrive:
    def __init__(self):
        self.uploaded = []

    def upload(self, name, data, content_type):
        self.uploaded.append((name, content_type, len(data)))


def test_render_pdf_returns_pdf_bytes_and_handles_unicode():
    data = render_pdf("My Title", "first line\n\nsecond — with “smart” quotes and …")
    assert data[:4] == b"%PDF"
    assert len(data) > 200


def test_make_document_sends_pdf_saves_and_copies_to_onedrive(tmp_path):
    sms = FakeSms()
    files = FileStore(tmp_path / "f.sqlite")
    od = FakeOneDrive()
    svc = DocumentService(sms=sms, files=files, public_base_url="https://app.example", onedrive=od)

    out = svc.dispatch("make_document", {
        "title": "STAT 311 Study Guide",
        "content": "point one\npoint two",
    })
    assert "sent" in out.lower()

    # Sent to WhatsApp as media.
    text, media_url = sms.sent[0]
    assert "STAT 311 Study Guide" in text
    assert media_url[0].startswith("https://app.example/file/")

    # Stored as a servable PDF.
    fid = media_url[0].rsplit("/", 1)[1]
    filename, ctype, data = files.get(fid)
    assert filename == "STAT 311 Study Guide.pdf"
    assert ctype == "application/pdf"
    assert data[:4] == b"%PDF"

    # Also copied into the OneDrive folder.
    assert od.uploaded and od.uploaded[0][0] == "STAT 311 Study Guide.pdf"


def test_make_document_works_without_onedrive(tmp_path):
    sms = FakeSms()
    svc = DocumentService(sms=sms, files=FileStore(tmp_path / "f.sqlite"),
                          public_base_url="https://app.example", onedrive=None)
    svc.dispatch("make_document", {"title": "Notes", "content": "stuff"})
    assert sms.sent and sms.sent[0][1][0].startswith("https://app.example/file/")
