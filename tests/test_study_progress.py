"""Tests for study progress: flashcard boxes (spaced repetition) + quiz attempts."""

from __future__ import annotations

from app.db import StudyProgressStore


def test_flashcard_box_goes_up_when_known_and_resets_when_missed(tmp_path):
    s = StudyProgressStore(tmp_path / "p.sqlite")
    assert s.get_boxes("deck1") == {}
    assert s.rate_card("deck1", 0, True) == 1     # 0 -> 1
    assert s.rate_card("deck1", 0, True) == 2     # 1 -> 2
    assert s.rate_card("deck1", 1, False) == 0    # missed -> 0
    assert s.rate_card("deck1", 0, False) == 0    # known card missed -> back to 0
    assert s.get_boxes("deck1") == {0: 0, 1: 0}


def test_box_is_capped(tmp_path):
    s = StudyProgressStore(tmp_path / "p.sqlite")
    for _ in range(10):
        s.rate_card("d", 0, True)
    assert s.get_boxes("d")[0] == 5


def test_quiz_attempts_track_count_and_best(tmp_path):
    s = StudyProgressStore(tmp_path / "p.sqlite")
    assert s.attempts("q1") == {"count": 0, "best": 0, "list": []}
    s.add_attempt("q1", 7, 10, 3)
    s.add_attempt("q1", 9, 10, 1)
    a = s.attempts("q1")
    assert a["count"] == 2
    assert a["best"] == 9
    assert a["list"][-1] == {"score": 9, "total": 10, "missed": 1}
