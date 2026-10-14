"""Exam dates (v0.3): inheritance, clearing, the display string."""

from __future__ import annotations

from datetime import date
from pathlib import Path

from recalldrill.exam import ExamDate, days_text, exam_line, inherited
from recalldrill.pacing import PacingSettings, load, save, settings_from_json
from recalldrill.storage import Storage

TODAY = date(2026, 10, 13)  # a Tuesday


def test_the_home_deck_wins_then_the_nearest_parent() -> None:
    dates: dict[int, date | None] = {1: date(2026, 12, 1), 2: date(2026, 10, 30), 3: None}
    # chain: deck 3 (Course::Lab::Bones), parent 2 (Course::Lab), root 1 (Course)
    assert inherited([3, 2, 1], dates.get) == ExamDate(date(2026, 10, 30), 2)
    assert inherited([2, 1], dates.get) == ExamDate(date(2026, 10, 30), 2)
    dates[3] = date(2026, 10, 23)
    assert inherited([3, 2, 1], dates.get) == ExamDate(date(2026, 10, 23), 3)
    assert inherited([3, 2, 1], lambda _d: None) is None
    assert inherited([], dates.get) is None


def test_the_display_string() -> None:
    assert exam_line(date(2026, 10, 23), TODAY) == "Exam: Fri Oct 23 (10 days)"
    assert exam_line(date(2026, 10, 14), TODAY) == "Exam: Wed Oct 14 (1 day)"
    assert exam_line(date(2026, 10, 13), TODAY) == "Exam: Tue Oct 13 (today)"
    assert exam_line(date(2026, 10, 12), TODAY) == "Exam: Mon Oct 12 (passed yesterday)"
    assert exam_line(date(2026, 10, 10), TODAY) == "Exam: Sat Oct 10 (passed 3 days ago)"
    assert exam_line(date(2026, 10, 23), TODAY, "Course::Lab") == (
        "Exam: Fri Oct 23 (10 days), set on Course::Lab"
    )
    assert days_text(date(2026, 11, 13), TODAY) == "31 days"


def test_exam_date_is_saved_with_the_pacing_and_can_be_cleared(tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    assert load(st, 5).exam_date is None
    save(st, 5, PacingSettings(exam_date=date(2026, 10, 23)))
    assert load(st, 5).exam_date == date(2026, 10, 23)
    assert load(st, 5).target_date is None  # independent of the pacing target
    # Setting a target keeps the exam; clearing the exam keeps the target.
    save(st, 5, PacingSettings(date(2026, 10, 20), exam_date=date(2026, 10, 23)))
    cleared = PacingSettings(date(2026, 10, 20), exam_date=None)
    save(st, 5, cleared)
    assert load(st, 5) == cleared and load(st, 5).exam_date is None
    # Old files have no exam_date; a bad one is ignored.
    assert settings_from_json({"target_date": "2026-10-20"}).exam_date is None
    assert settings_from_json({"exam_date": "not a date"}).exam_date is None
    assert settings_from_json({"exam_date": 5}).exam_date is None
