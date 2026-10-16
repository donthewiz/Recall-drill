"""Math cards (v0.6): which notes are drilled with the math answer check.

The card contract (docs/DECISIONS.md, "v0.6 math answer mode"): the note has the
tag ``rd::math`` (exact; never ``tag:rd::*``) and a field ``MathAnswer`` holding
the answer in plain keyboard form. ``rd::math::equiv`` on the note makes an
equivalent answer in another form count as right. A note tagged ``rd::math``
without a usable ``MathAnswer`` is drilled as a normal card; the setup panel counts
those.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from anki.notes import Note

from ..card_state import has_tag
from ..math_answer import usable_target
from .text import grading_text

MATH_TAG = "rd::math"
EQUIV_TAG = "rd::math::equiv"
MATH_FIELD = "MathAnswer"

MathStatus = Literal["math", "no_answer"]


@dataclass(frozen=True)
class MathCard:
    target: str
    """The ``MathAnswer`` in keyboard form (the field's plain text)."""
    equiv: bool


def math_answer_text(note: Note) -> str:
    """The ``MathAnswer`` field as plain text, "" when the note has none."""
    if MATH_FIELD not in note.keys():
        return ""
    return grading_text(note[MATH_FIELD])


def math_status(note: Note, tags: Iterable[str]) -> MathStatus | None:
    """ "math" (drilled with the math check), "no_answer" (tagged ``rd::math`` but
    no usable ``MathAnswer``: drilled as a normal card), or None (not a math note)."""
    tag_list = list(tags)
    if not has_tag(tag_list, MATH_TAG):
        return None
    text = math_answer_text(note)
    return "math" if text and usable_target(text) else "no_answer"


def math_card(note: Note, tags: Iterable[str]) -> MathCard | None:
    """The note's math answer, or None when it isn't drilled as a math card."""
    tag_list = list(tags)
    if math_status(note, tag_list) != "math":
        return None
    return MathCard(math_answer_text(note), has_tag(tag_list, EQUIV_TAG))
