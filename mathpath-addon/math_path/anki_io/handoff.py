"""Hand learned recipes to Anki: handoff B (may import anki, never Qt).

When a learn session ends, every recipe that reached Learned goes to Anki in one undo step
("Math Path: hand off"), as Recall Drill does (handoff B, ``anki-addon/docs/DECISIONS.md``):

1. the notes get the tag ``mp::learned``;
2. their suspended cards are unsuspended (only suspended cards are passed to Anki's unsuspend, which
   would unbury too);
3. their new cards are repositioned to the front of the new queue, in the order learned (one
   position per note; the deck's other new cards shift back);
4. their cards are buried manually, so the first Anki review is tomorrow (they return at the next
   day's rollover), not minutes after the session.

Anki stays the only scheduler: no due date or interval is ever set. Planning again right after a
handoff plans nothing.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, OpChanges
from anki.consts import (
    CARD_TYPE_NEW,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_SIBLING_BURIED,
    QUEUE_TYPE_SUSPENDED,
)
from anki.errors import NotFoundError
from anki.notes import NoteId

from ..recipe_note import TAG_LEARNED
from .undo import StepFailed, run_as_one_step

log = logging.getLogger(__name__)

UNDO_LABEL = "Math Path: hand off"

__all__ = ["StepFailed", "HandoffPlan", "plan_handoff", "apply_handoff", "UNDO_LABEL"]


@dataclass(frozen=True)
class HandoffPlan:
    nids: tuple[int, ...]
    """The notes handed off, in the order they were learned."""
    cids: tuple[int, ...]
    """Every card of those notes."""
    tag_notes: tuple[int, ...]
    """Notes that get ``mp::learned`` (the ones without it)."""
    unsuspend: tuple[int, ...]
    reposition: tuple[int, ...]
    """New cards, in learned order: they go to the front of the new queue."""
    bury: tuple[int, ...]
    missing: tuple[int, ...] = ()
    """Note ids that no longer exist: skipped."""

    @property
    def has_changes(self) -> bool:
        return bool(self.tag_notes or self.unsuspend or self.reposition or self.bury)


def plan_handoff(col: Collection, nids: Sequence[int]) -> HandoffPlan:
    """What handing these notes off would do, read fresh. Writes nothing."""
    notes: list[int] = []
    cids: list[int] = []
    tag_notes: list[int] = []
    unsuspend: list[int] = []
    reposition: list[int] = []
    bury: list[int] = []
    missing: list[int] = []
    positions: dict[int, int] = {}
    in_place = True
    for nid in dict.fromkeys(nids):
        try:
            note = col.get_note(NoteId(nid))
        except NotFoundError:
            missing.append(nid)
            continue
        notes.append(nid)
        if TAG_LEARNED not in note.tags:
            tag_notes.append(nid)
        for card in sorted(note.cards(), key=lambda c: c.ord):
            cids.append(int(card.id))
            if card.queue == QUEUE_TYPE_SUSPENDED:
                unsuspend.append(int(card.id))
            if card.type == CARD_TYPE_NEW:
                reposition.append(int(card.id))
                want = positions.setdefault(nid, len(positions))  # one position per note
                due = card.odue if card.odid else card.due
                in_place = in_place and due == want
            if card.queue not in (QUEUE_TYPE_MANUALLY_BURIED, QUEUE_TYPE_SIBLING_BURIED):
                bury.append(int(card.id))
    return HandoffPlan(
        nids=tuple(notes),
        cids=tuple(cids),
        tag_notes=tuple(tag_notes),
        unsuspend=tuple(unsuspend),
        reposition=() if in_place else tuple(reposition),
        bury=tuple(bury),
        missing=tuple(missing),
    )


def _cards(ids: Sequence[int]) -> list[CardId]:
    return [CardId(i) for i in ids]


def apply_handoff(col: Collection, plan: HandoffPlan) -> OpChanges:
    """Run the plan as one undo step: tag, unsuspend, reposition, bury. On failure, undoes what it
    did and raises :class:`~.undo.StepFailed`."""

    def work() -> None:
        if plan.tag_notes:
            col.tags.bulk_add([NoteId(n) for n in plan.tag_notes], TAG_LEARNED)
        if plan.unsuspend:
            col.sched.unsuspend_cards(_cards(plan.unsuspend))
        if plan.reposition:
            col.sched.reposition_new_cards(
                _cards(plan.reposition),
                starting_from=0,
                step_size=1,
                randomize=False,
                shift_existing=True,
            )
        if plan.bury:
            col.sched.bury_cards(_cards(plan.bury), manual=True)

    return run_as_one_step(col, UNDO_LABEL, work)
