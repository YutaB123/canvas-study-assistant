"""Make a document (PDF) from text and send it over WhatsApp.

The brain writes the content; this turns it into a PDF, sends it as a WhatsApp
attachment, and also drops a copy in the student's OneDrive folder.
"""

from __future__ import annotations

import re
import uuid

from fpdf import FPDF
from fpdf.enums import XPos, YPos

DOCUMENT_TOOLS = [
    {
        "name": "make_document",
        "description": "Create a document (PDF) from text and SEND it to the student over "
        "WhatsApp (also saved to their files folder). Use whenever they ask you to write "
        "something up as a file or document — a study guide, summary, notes, outline, "
        "cheat sheet, essay draft, etc. You write the full content yourself in 'content'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "title": {
                    "type": "string",
                    "description": "Short title / filename, no extension (e.g. 'STAT 311 Study Guide').",
                },
                "content": {
                    "type": "string",
                    "description": "The full document text. Plain text; blank lines between paragraphs.",
                },
            },
            "required": ["title", "content"],
        },
    }
]

# fpdf2 core fonts are latin-1; map common unicode so content doesn't get mangled.
_UNICODE = {
    "—": "-", "–": "-", "’": "'", "‘": "'",
    "“": '"', "”": '"', "…": "...", "•": "-",
    " ": " ", "→": "->", "←": "<-",
}


def _latin1(text: str) -> str:
    for k, v in _UNICODE.items():
        text = text.replace(k, v)
    return text.encode("latin-1", "replace").decode("latin-1")


def render_pdf(title: str, content: str) -> bytes:
    pdf = FPDF()
    pdf.add_page()
    pdf.set_auto_page_break(True, margin=15)
    pdf.set_font("Helvetica", "B", 16)
    pdf.multi_cell(0, 10, _latin1(title), new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(2)
    pdf.set_font("Helvetica", "", 12)
    for line in content.split("\n"):
        pdf.multi_cell(0, 7, _latin1(line) or " ", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    return bytes(pdf.output())


def _safe_name(title: str) -> str:
    name = re.sub(r"[^\w\- ]", "", title).strip() or "document"
    return f"{name}.pdf"


class DocumentService:
    def __init__(self, sms, files, public_base_url: str, onedrive=None):
        self.sms = sms
        self.files = files
        self.public_base_url = public_base_url.rstrip("/")
        self.onedrive = onedrive

    def tool_names(self) -> list[str]:
        return [t["name"] for t in DOCUMENT_TOOLS]

    def schemas(self) -> list[dict]:
        return list(DOCUMENT_TOOLS)

    def dispatch(self, name: str, tool_input: dict) -> str:
        if name != "make_document":
            return f"(unknown document tool: {name})"
        title = (tool_input.get("title") or "document").strip()
        content = tool_input.get("content") or ""
        data = render_pdf(title, content)
        filename = _safe_name(title)
        file_id = uuid.uuid4().hex
        self.files.save(file_id, filename, "application/pdf", data)
        # Also drop a copy in their OneDrive folder (so it's on the laptop too).
        if self.onedrive is not None:
            try:
                self.onedrive.upload(filename, data, "application/pdf")
            except Exception:
                pass
        self.sms.send(
            f"here's {title}:", media_url=[f"{self.public_base_url}/file/{file_id}"]
        )
        return f"created and sent {filename} ({len(data)} bytes) to them."
