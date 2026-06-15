"""Tests for the study-page maker (flashcards + practice exams)."""

from __future__ import annotations

import json
from types import SimpleNamespace

from app import study
from app.canvas import AssignmentDetail
from app.db import StudyPageStore


# --- Fakes -------------------------------------------------------------------

class FakeCanvas:
    def get_assignment_detail(self, ref):
        return AssignmentDetail(
            name="Homework 4",
            course="CSE 163 A",
            due_at=None,
            points=20,
            description="Implement merge sort and analyze its runtime.",
            html_url="",
        )


def text_block(text):
    return SimpleNamespace(type="text", text=text)


class FakeAnthropic:
    """Returns a scripted JSON payload as the model's text output."""

    def __init__(self, payload):
        self._payload = payload
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(
            stop_reason="end_turn", content=[text_block(json.dumps(self._payload))]
        )


def make_service(tmp_path, payload):
    pages = StudyPageStore(tmp_path / "s.sqlite")
    client = FakeAnthropic(payload)
    svc = study.StudyService(
        canvas=FakeCanvas(),
        client=client,
        model="claude-opus-4-8",
        pages=pages,
        public_base_url="https://app.example.com",
    )
    return svc, pages, client


# --- Rendering (pure) --------------------------------------------------------

def test_render_flashcards_includes_questions_and_answers():
    html = study.render_flashcards(
        "Homework 4 flashcards",
        [{"q": "What is merge sort?", "a": "A divide-and-conquer sort."}],
    )
    assert "Homework 4 flashcards" in html
    assert "What is merge sort?" in html
    assert "A divide-and-conquer sort." in html
    assert "<html" in html.lower()


def test_render_exam_includes_questions_and_an_answer_key():
    html = study.render_exam(
        "Homework 4 practice exam",
        [{"q": "Describe the runtime of merge sort.", "a": "O(n log n)."}],
    )
    assert "Describe the runtime of merge sort." in html
    assert "O(n log n)." in html  # answer key present (revealable)


# --- Dispatch flow -----------------------------------------------------------

def test_make_flashcards_stores_page_and_returns_link(tmp_path):
    payload = {"cards": [{"q": "What is merge sort?", "a": "A sort."}]}
    svc, pages, client = make_service(tmp_path, payload)

    out = svc.dispatch("make_flashcards", {"ref": "1:55"})

    # A link to our app was returned.
    assert "https://app.example.com/study/" in out
    page_id = out.split("/study/")[1].split()[0].strip()
    stored = pages.get(page_id)
    assert stored is not None
    assert "What is merge sort?" in stored
    # The model was asked with a forced JSON shape.
    assert "output_config" in client.calls[0]


def test_make_practice_exam_stores_page_and_returns_link(tmp_path):
    payload = {"questions": [{"q": "Runtime of merge sort?", "a": "O(n log n)."}]}
    svc, pages, _ = make_service(tmp_path, payload)

    out = svc.dispatch("make_practice_exam", {"ref": "1:55"})
    assert "/study/" in out
    page_id = out.split("/study/")[1].split()[0].strip()
    assert "Runtime of merge sort?" in pages.get(page_id)


def test_tool_names_and_schemas(tmp_path):
    svc, _, _ = make_service(tmp_path, {"cards": []})
    assert set(svc.tool_names()) == {"make_flashcards", "make_practice_exam"}
    assert {s["name"] for s in svc.schemas()} == set(svc.tool_names())
