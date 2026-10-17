"""Rating a card through the reviewer's normal answer path (v0.1).

The reviewer (``aqt/reviewer.py``, 26.08.1) answers a card with ``_answerCard(ease)`` once it is
showing the answer (``state == "answer"``); ``_showAnswer()`` gets it there. Going through them is
the same as pressing the button: Anki's timer, the revlog row and its type, and undo all work as
usual, and the reviewer moves on to the next card by itself. Nothing is rated unless the reviewer
is still on that very card.
"""

from __future__ import annotations

from typing import Any

from aqt import mw

NOT_ON_CARD = "The reviewer is no longer on this card, so it wasn't rated."


def reviewer_card_id() -> int | None:
    """The id of the card the reviewer is showing (None when it isn't reviewing)."""
    if mw is None or getattr(mw, "state", "") != "review":  # pyright: ignore[reportUnnecessaryComparison]
        return None
    reviewer: Any = getattr(mw, "reviewer", None)
    card: Any = getattr(reviewer, "card", None)
    return int(card.id) if card is not None else None


def rate_current(card_id: int, ease: int) -> tuple[bool, str]:
    """Answer ``card_id`` with ``ease`` (1 Again, 2 Hard, 3 Good, 4 Easy) if the reviewer is on it.

    Returns ``(True, "")``, or ``(False, why)`` without rating anything."""
    if reviewer_card_id() != card_id:
        return False, NOT_ON_CARD
    reviewer: Any = mw.reviewer
    if reviewer.state == "question":
        reviewer._showAnswer()
    if reviewer.state != "answer":
        return False, NOT_ON_CARD
    reviewer._answerCard(ease)
    return True, ""
