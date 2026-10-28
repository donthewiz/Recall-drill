"""Set aside and release cards on the collection. Anki is the only scheduler: nothing here
grades a card, writes a review-log row or touches ``type`` or ``due``."""

from __future__ import annotations

from dataclasses import dataclass, field

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import Card, CardId
from anki.collection import Collection, OpChanges

from .. import marker, rules
from ..rules import Verdict
from .undo import run_as_one_step

SET_ASIDE_LABEL = "Set aside card"
RELEASE_LABEL = "Release set-aside cards"
SEARCH = f"has-cd:{marker.MARKER_KEY}"
"""Finds exactly the set-aside cards (checked on Anki 26.8.1)."""


@dataclass
class SetAsideOutcome:
    verdict: Verdict
    changes: OpChanges = field(default_factory=OpChanges)
    """What changed (empty when the card was refused); the reviewer reads it to move on."""


@dataclass
class ReleaseOutcome:
    released: int
    changes: OpChanges = field(default_factory=OpChanges)


def set_aside_cards(col: Collection) -> list[CardId]:
    return list(col.find_cards(SEARCH))


def set_aside(col: Collection, card_id: CardId) -> SetAsideOutcome:
    """Set one card aside as one undo step: save its flag in ``custom_data["tri"]``, flag it red,
    tag its note ``triage``, suspend it. A card that may not be set aside is left unchanged."""
    card = col.get_card(card_id)
    data = marker.parse_custom_data(card.custom_data)
    if data is None:
        return SetAsideOutcome(Verdict.UNREADABLE)
    verdict = rules.set_aside_verdict(card.type, card.queue, marker.has_marker(data))
    if verdict is not Verdict.OK:
        return SetAsideOutcome(verdict)
    new_data = marker.with_marker(data, card.user_flag())
    if new_data is None:
        return SetAsideOutcome(Verdict.TOO_BIG)

    def work() -> None:
        card.custom_data = new_data
        col.update_card(card)
        col.set_user_flag_for_cards(rules.SET_ASIDE_FLAG, [card.id])
        col.tags.bulk_add([card.nid], rules.TAG)
        col.sched.suspend_cards([card.id])

    return SetAsideOutcome(Verdict.OK, run_as_one_step(col, SET_ASIDE_LABEL, work))


def release_all(col: Collection) -> ReleaseOutcome:
    """Release every set-aside card as one undo step.

    Only cards with the marker are touched. A card still suspended is unsuspended; its flag goes
    back to the saved value only if it is still red; the marker is removed (other keys kept); a
    note loses ``triage`` only when none of its cards still has the marker."""
    ids = set_aside_cards(col)
    if not ids:
        return ReleaseOutcome(0)
    cards = [col.get_card(i) for i in ids]

    def work() -> None:
        updated: list[Card] = []
        restore: dict[int, list[CardId]] = {}
        unsuspend: list[CardId] = []
        for card in cards:
            data = marker.parse_custom_data(card.custom_data) or {}
            if card.user_flag() == rules.SET_ASIDE_FLAG:
                restore.setdefault(marker.saved_flag(data), []).append(card.id)
            if card.queue == rules.QUEUE_SUSPENDED:
                unsuspend.append(card.id)
            card.custom_data = marker.without_marker(data)
            updated.append(card)
        # custom_data first: the later calls load the cards afresh.
        col.update_cards(updated)
        for flag, flagged in restore.items():
            if flag != rules.SET_ASIDE_FLAG:
                col.set_user_flag_for_cards(flag, flagged)
        if unsuspend:
            col.sched.unsuspend_cards(unsuspend)
        still_marked = set(col.find_notes(SEARCH))
        untag = sorted({c.nid for c in cards} - still_marked)
        if untag:
            col.tags.bulk_remove(untag, rules.TAG)

    return ReleaseOutcome(len(ids), run_as_one_step(col, RELEASE_LABEL, work))


def learn_again_count(col: Collection, card_id: CardId) -> int:
    """How many times the card was answered Again while learning (review-log ``type = 0``,
    ``ease = 1``)."""
    assert col.db is not None
    value = col.db.scalar(
        "select count() from revlog where cid = ? and type = 0 and ease = 1", card_id
    )
    return int(value or 0)
