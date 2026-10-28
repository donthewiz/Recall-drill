"""What the key and the menu items do. Writes go through ``CollectionOp`` so Anki refreshes the
reviewer's queue and moves on, as it does after ``@``."""

from __future__ import annotations

from aqt import dialogs, mw
from aqt.operations import CollectionOp
from aqt.utils import askUser, tooltip

from .. import rules
from ..anki_io import triage

TITLE = "Card Triage"


def set_aside_current() -> None:
    """The reviewer key (or the bar's button): set the card on screen aside."""
    reviewer = mw.reviewer
    card = reviewer.card if mw.state == "review" else None
    if card is None:
        return
    card_id = card.id

    def done(outcome: triage.SetAsideOutcome) -> None:
        tooltip(rules.tooltip_for(outcome.verdict))

    CollectionOp(mw, lambda col: triage.set_aside(col, card_id)).success(done).run_in_background()


def release_all() -> None:
    """Tools → Card Triage → Release all set-aside cards…: ask, then release in one undo step."""
    col = mw.col
    assert col is not None
    count = len(triage.set_aside_cards(col))
    if count == 0:
        tooltip(rules.TOOLTIP_NONE_SET_ASIDE)
        return
    if not askUser(rules.release_question(count), parent=mw, title=TITLE):
        return

    def done(outcome: triage.ReleaseOutcome) -> None:
        noun = "card" if outcome.released == 1 else "cards"
        tooltip(f"Released {outcome.released} set-aside {noun}. Ctrl+Z to undo.")

    CollectionOp(mw, triage.release_all).success(done).run_in_background()


def show_set_aside() -> None:
    """Tools → Card Triage → Show set-aside cards: Browse, searching the marker."""
    dialogs.open("Browser", mw, search=(triage.SEARCH,))
