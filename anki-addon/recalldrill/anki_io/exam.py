"""Read a deck's exam date (v0.3). Read only.

``exam.py`` (pure) has the rules. A card's exam date is its home deck's, else
the nearest parent deck's that has one, from ``pacing.json``.
"""

from __future__ import annotations

from datetime import date

from anki.collection import Collection
from anki.decks import DeckId

from .. import pacing
from ..exam import ExamDate, inherited
from ..storage import Storage


def deck_chain(col: Collection, did: int) -> list[int]:
    """The deck, then its parents, nearest first."""
    decks = [col.decks.get(DeckId(did)), *reversed(col.decks.parents(DeckId(did)))]
    return [int(d["id"]) for d in decks if d is not None]


def exam_for_deck(col: Collection, storage: Storage, did: int) -> ExamDate | None:
    """The exam date that applies to cards whose home deck is ``did``."""

    def exam_of(d: int) -> date | None:
        return pacing.load(storage, d).exam_date

    return inherited(deck_chain(col, did), exam_of)


def inherited_exam(col: Collection, storage: Storage, did: int) -> ExamDate | None:
    """The date ``did`` would inherit from a parent, ignoring its own."""
    chain = deck_chain(col, did)
    return inherited(chain[1:], lambda d: pacing.load(storage, d).exam_date)
