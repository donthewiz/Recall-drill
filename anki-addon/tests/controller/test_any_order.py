"""The controller and drill view for any-order list cards (2026-10-12)."""

from __future__ import annotations

from typing import Any

from controller_support import make, source

from recalldrill.drill_view import ANY_ORDER_NOTE, card_html

DECK: list[Any] = [
    {"front": "Name the types", "back": "skeletal, cardiac, smooth", "anyOrder": True},
    {"front": "heart", "back": "cardi"},
]


def test_view_and_note_follow_the_card() -> None:
    h = make(DECK, encodeReps=1)
    h.ctrl.start()
    view = h.ctrl.view()
    assert view.item_id == 0 and view.any_order is True
    assert ANY_ORDER_NOTE in card_html(view, lambda s: s)
    # Typed in another order, the answer is right.
    h.ctrl.submit("smooth, skeletal, cardiac")
    assert h.ctrl.view().feedback is not None
    assert h.ctrl.view().feedback.verdict == "exact"  # type: ignore[union-attr]
    h.ctrl.dwell_elapsed()
    view = h.ctrl.view()
    assert view.item_id == 1 and view.any_order is False
    assert ANY_ORDER_NOTE not in card_html(view, lambda s: s)


def test_an_edit_recomputes_any_order() -> None:
    h = make(DECK, encodeReps=2, sources=[source(0), source(1)])
    h.ctrl.start()
    # Prompt-only edit (progress kept): the tag now says Sequence.
    assert h.ctrl.begin_edit() is not None
    h.ctrl.apply_card_edit("Name the types", "skeletal, cardiac, smooth", "", None, False)
    assert h.ctrl.state["items"][0].get("anyOrder") is False
    # An answer that is no longer a list drops the key (and restarts the card).
    assert h.ctrl.begin_edit() is not None
    h.ctrl.apply_card_edit("Name the types", "skeletal and cardiac", "", None, None)
    assert "anyOrder" not in h.ctrl.state["items"][0]
    assert h.ctrl.begin_edit() is not None
    h.ctrl.apply_card_edit("Name the types", "skeletal, cardiac, smooth", "", None, True)
    assert h.ctrl.state["items"][0].get("anyOrder") is True
    # Without a recomputed value the edit keeps it, as the engine does.
    assert h.ctrl.begin_edit() is not None
    h.ctrl.apply_card_edit("Name the types", "skeletal, cardiac, smooth", "")
    assert h.ctrl.state["items"][0].get("anyOrder") is True

