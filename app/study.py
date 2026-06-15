"""The study-page maker: turn an assignment or reading into flashcards or a
practice exam, publish it as a small web page, and hand back a link.

Generating the cards/questions is its own Claude call (separate from the
conversational brain) using a forced JSON shape, so the result is structured.
The page is rendered with a tiny self-contained HTML template (flip a card /
reveal an answer) and stored to be served at /study/{id}.
"""

from __future__ import annotations

import json
import uuid

from jinja2 import Template

# --- HTML templates (self-contained, no external assets) ---------------------

_PAGE_CSS = """
  :root { color-scheme: light dark; }
  body { font-family: -apple-system, system-ui, sans-serif; max-width: 640px;
         margin: 0 auto; padding: 24px; line-height: 1.5; }
  h1 { font-size: 1.3rem; }
  .card { border: 1px solid #8884; border-radius: 12px; padding: 16px;
          margin: 12px 0; cursor: pointer; }
  .card .a { display: none; margin-top: 10px; color: #2a7; }
  .card.show .a { display: block; }
  .hint { color: #8889; font-size: .85rem; }
"""

_FLASHCARDS_TEMPLATE = Template(
    autoescape=True,
    source="""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title><style>{{ css }}</style></head>
<body>
<h1>{{ title }}</h1>
<p class="hint">tap a card to flip it</p>
{% for c in cards %}
<div class="card" onclick="this.classList.toggle('show')">
  <div class="q">{{ c.q }}</div>
  <div class="a">{{ c.a }}</div>
</div>
{% endfor %}
</body></html>"""
)

_EXAM_TEMPLATE = Template(
    autoescape=True,
    source="""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{{ title }}</title><style>{{ css }}</style></head>
<body>
<h1>{{ title }}</h1>
<p class="hint">try each one, then tap to reveal the answer</p>
{% for c in cards %}
<div class="card" onclick="this.classList.toggle('show')">
  <div class="q">{{ loop.index }}. {{ c.q }}</div>
  <div class="a">{{ c.a }}</div>
</div>
{% endfor %}
</body></html>"""
)


def render_flashcards(title: str, cards: list[dict]) -> str:
    return _FLASHCARDS_TEMPLATE.render(title=title, cards=cards, css=_PAGE_CSS)


def render_exam(title: str, cards: list[dict]) -> str:
    return _EXAM_TEMPLATE.render(title=title, cards=cards, css=_PAGE_CSS)


# --- Tool schemas ------------------------------------------------------------

STUDY_TOOLS = [
    {
        "name": "make_flashcards",
        "description": "Make flashcards from an assignment or reading and return a "
        "link to a web page. Pass the assignment ref (from get_upcoming / "
        "search_assignments), e.g. '1:55'. Optionally set 'count'.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Assignment ref 'courseId:assignmentId'."},
                "count": {"type": "integer", "description": "Roughly how many cards (default 10)."},
            },
            "required": ["ref"],
        },
    },
    {
        "name": "make_practice_exam",
        "description": "Make a short practice exam from an assignment or reading and "
        "return a link to a web page. Pass the assignment ref.",
        "input_schema": {
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Assignment ref 'courseId:assignmentId'."},
                "count": {"type": "integer", "description": "Roughly how many questions (default 8)."},
            },
            "required": ["ref"],
        },
    },
]

_FLASHCARD_SCHEMA = {
    "type": "object",
    "properties": {
        "cards": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                "required": ["q", "a"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["cards"],
    "additionalProperties": False,
}

_EXAM_SCHEMA = {
    "type": "object",
    "properties": {
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"q": {"type": "string"}, "a": {"type": "string"}},
                "required": ["q", "a"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["questions"],
    "additionalProperties": False,
}


class StudyService:
    def __init__(self, canvas, client, model: str, pages, public_base_url: str):
        self.canvas = canvas
        self.client = client
        self.model = model
        self.pages = pages
        self.public_base_url = public_base_url.rstrip("/")

    def tool_names(self) -> list[str]:
        return [t["name"] for t in STUDY_TOOLS]

    def schemas(self) -> list[dict]:
        return list(STUDY_TOOLS)

    def dispatch(self, name: str, tool_input: dict) -> str:
        if name == "make_flashcards":
            return self._make(tool_input, kind="flashcards")
        if name == "make_practice_exam":
            return self._make(tool_input, kind="exam")
        return f"(unknown study tool: {name})"

    # --- internals -----------------------------------------------------------

    def _source(self, ref: str) -> tuple[str, str]:
        detail = self.canvas.get_assignment_detail(ref)
        source_text = f"{detail.name}\n\n{detail.description}".strip()
        return detail.name, source_text

    def _generate(self, instruction: str, source: str, schema: dict) -> dict:
        response = self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": f"{instruction}\n\nSource material:\n{source}",
                }
            ],
            output_config={"format": {"type": "json_schema", "schema": schema}},
        )
        text = next(
            (b.text for b in response.content if getattr(b, "type", None) == "text"),
            "{}",
        )
        return json.loads(text)

    def _make(self, tool_input: dict, kind: str) -> str:
        ref = tool_input["ref"]
        count = int(tool_input.get("count") or (10 if kind == "flashcards" else 8))
        name, source = self._source(ref)

        if kind == "flashcards":
            data = self._generate(
                f"Make about {count} flashcards (question/answer pairs) to study this. "
                "Keep questions focused and answers concise.",
                source,
                _FLASHCARD_SCHEMA,
            )
            cards = data.get("cards", [])
            title = f"{name} — flashcards"
            html = render_flashcards(title, cards)
            note = "made you some flashcards"
        else:
            data = self._generate(
                f"Write a {count}-question practice exam covering this material, "
                "with a short answer for each question.",
                source,
                _EXAM_SCHEMA,
            )
            cards = data.get("questions", [])
            title = f"{name} — practice exam"
            html = render_exam(title, cards)
            note = "here's a practice exam"

        page_id = uuid.uuid4().hex
        self.pages.save(page_id, title, html)
        link = f"{self.public_base_url}/study/{page_id}"
        return f"{note}: {link}"
