"""Exam dates (v0.3, pure).

docs/DECISIONS.md, "v0.3: whole-section drilling, exam dates, export".

A deck's optional ``exam_date`` lives in ``pacing.json`` next to its pacing
target (``pacing.PacingSettings.exam_date``). A card's exam date is its home
deck's, else the nearest parent deck's that has one: the same walk pacing
uses for its target date (``anki_io/waiting.deck_pacing``).
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import date

from .pacing import short_date


@dataclass(frozen=True)
class ExamDate:
    day: date
    did: int
    """The deck the date is set on (the card's home deck, or a parent)."""


def inherited(chain: Iterable[int], exam_of: Callable[[int], date | None]) -> ExamDate | None:
    """The first deck of ``chain`` (the home deck, then its parents, nearest
    first) that has an exam date."""
    for did in chain:
        day = exam_of(did)
        if day is not None:
            return ExamDate(day, did)
    return None


def days_text(exam: date, today: date) -> str:
    """ "10 days", "1 day", "today", "passed yesterday", "passed 3 days ago"."""
    n = (exam - today).days
    if n == 0:
        return "today"
    if n > 0:
        return f"{n} day" if n == 1 else f"{n} days"
    if n == -1:
        return "passed yesterday"
    return f"passed {-n} days ago"


def exam_line(exam: date, today: date, set_on: str | None = None) -> str:
    """ "Exam: Fri Oct 23 (10 days)". ``set_on``: the parent deck's name when the
    date is inherited from it."""
    text = f"Exam: {short_date(exam)} ({days_text(exam, today)})"
    return f"{text}, set on {set_on}" if set_on else text
