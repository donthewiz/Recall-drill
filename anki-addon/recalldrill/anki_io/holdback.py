"""Hold back a deck's undrilled new cards (v0.3): plan, then apply.

The add-on's **third collection write**, next to the handoff (``handoff.py``)
and the release (``release.py``), and built the same way: :func:`plan_hold_back`
reads fresh card state and decides (writes nothing); :func:`apply_hold_back`, run
by the UI inside ``CollectionOp``, makes it one undo step, "Recall Drill: hold
back", and on any failure merges what ran into that step and undoes it.

What a hold-back does to a deck (with its subdecks):

- It suspends the deck's cards that are **new and unsuspended**: ``type`` new,
  ``queue`` new, in their home deck, not buried, and not handed off and waiting
  for Anki (a handoff or release the revlog hasn't answered yet).
- Their notes get the tag ``rd::held`` (where missing).
- It never touches a card Anki has already introduced (not new), a card in a
  filtered deck, or a buried card; and it never runs by itself.

Planning again right after a hold-back plans nothing. The handoff (``handoff.py``)
and the release (``release.py``) remove ``rd::held`` when they send the cards on.
"""

from __future__ import annotations

import logging
from collections.abc import Iterable
from dataclasses import dataclass

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, OpChanges, SearchNode
from anki.consts import CARD_TYPE_NEW, QUEUE_TYPE_NEW
from anki.decks import DeckId
from anki.notes import NoteId

from .. import deck_settings
from ..history_store import handed_off_at
from ..holdback import TAG_HELD, UNDO_LABEL, HoldBack, effective
from ..storage import Storage
from .cards import CardSnapshot, NoteCache, has_tag, read_snapshots
from .exam import deck_chain
from .revlog import waiting_for_anki

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class HoldBackPlan:
    did: int
    deck: str
    suspend: tuple[int, ...]
    tag_notes: tuple[int, ...]
    """Notes that get ``rd::held`` (the ones without it)."""
    handed_off: int = 0
    """New unsuspended cards left alone: handed off, waiting for Anki."""
    in_filtered: int = 0
    """Cards left alone: they sit in a filtered deck."""

    @property
    def cards(self) -> int:
        return len(self.suspend)

    @property
    def has_changes(self) -> bool:
        return bool(self.suspend or self.tag_notes)


class HoldBackFailed(Exception):
    """The hold-back raised; ``rolled_back`` says whether everything was undone."""

    def __init__(self, cause: Exception, rolled_back: bool) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.rolled_back = rolled_back


def hold_back_state(col: Collection, storage: Storage, did: int) -> HoldBack:
    """Whether the deck holds its new cards back: its own saved value, else the
    nearest parent's, else off."""
    return effective(deck_chain(col, did), lambda d: deck_settings.explicit_hold_back(storage, d))


def can_hold_back(s: CardSnapshot) -> bool:
    """New, unsuspended, unburied, in its home deck."""
    return s.type == CARD_TYPE_NEW and s.queue == QUEUE_TYPE_NEW and s.odid == 0


def build_hold_back_plan(
    did: int,
    deck: str,
    snaps: Iterable[CardSnapshot],
    waiting_for_anki: Iterable[int] = (),
) -> HoldBackPlan:
    """Pure: ``snaps`` are the deck's cards, read fresh; ``waiting_for_anki`` the
    handed-off cards Anki hasn't rated since."""
    waiting = frozenset(waiting_for_anki)
    suspend: list[int] = []
    tag_notes: list[int] = []
    handed = 0
    filtered = 0
    for s in snaps:
        if s.type == CARD_TYPE_NEW and s.odid != 0 and s.queue == QUEUE_TYPE_NEW:
            filtered += 1
            continue
        if not can_hold_back(s):
            continue
        if s.cid in waiting:
            handed += 1
            continue
        suspend.append(s.cid)
        if s.nid not in tag_notes and not has_tag(s.tags, TAG_HELD):
            tag_notes.append(s.nid)
    return HoldBackPlan(did, deck, tuple(suspend), tuple(tag_notes), handed, filtered)


def plan_hold_back(col: Collection, storage: Storage, did: int) -> HoldBackPlan:
    """What holding back this deck (with its subdecks) would do, read fresh. Writes
    nothing."""
    name = col.decks.name(DeckId(did))
    cids = [
        int(c)
        for c in col.find_cards(
            col.build_search_string(SearchNode(deck=name), "is:new", "-is:suspended", "-is:buried")
        )
    ]
    snaps = read_snapshots(col, cids, NoteCache(col))
    handed = {c: t for c, t in handed_off_at(storage).items() if c in set(cids)}
    return build_hold_back_plan(did, name, snaps, waiting_for_anki(col, handed))


def held_cards(col: Collection, did: int) -> list[int]:
    """The deck's (and subdecks') cards currently held back: new, suspended, with a
    ``rd::held`` note tag (exact tag)."""
    return [
        int(c)
        for c in col.find_cards(
            col.build_search_string(
                SearchNode(deck=col.decks.name(DeckId(did))),
                SearchNode(tag=TAG_HELD),
                "is:new",
                "is:suspended",
            )
        )
    ]


def _roll_back(col: Collection, pos: int) -> bool:
    try:
        col.merge_undo_entries(pos)
        if col.undo_status().undo != UNDO_LABEL:
            return False
        col.undo()
    except Exception:
        log.exception("Recall Drill: rolling back a failed hold-back failed")
        return False
    return True


def _apply_steps(col: Collection, plan: HoldBackPlan) -> None:
    if plan.tag_notes:
        col.tags.bulk_add([NoteId(n) for n in plan.tag_notes], TAG_HELD)
    if plan.suspend:
        col.sched.suspend_cards([CardId(c) for c in plan.suspend])


def apply_hold_back(col: Collection, plan: HoldBackPlan) -> OpChanges:
    """Runs the plan as one undo step ("Recall Drill: hold back"). On failure,
    undoes what it did and raises :class:`HoldBackFailed`."""
    pos = col.add_custom_undo_entry(UNDO_LABEL)
    try:
        _apply_steps(col, plan)
        return col.merge_undo_entries(pos)
    except Exception as exc:
        raise HoldBackFailed(exc, _roll_back(col, pos)) from exc


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def describe(plan: HoldBackPlan) -> str:
    """The confirmation: what is suspended and tagged, what is left alone."""
    lines = [
        f"Keep {_n(plan.cards, 'new card')} in {plan.deck} out of Anki until drilled?",
        "",
        f"They are suspended and their notes get the tag {TAG_HELD}. Drill them in the "
        "setup panel; the handoff unsuspends them, or send them to Anki undrilled "
        "(Tools → Recall Drill: waiting cards).",
        "Cards Anki has already introduced, cards in a filtered deck, buried cards and "
        "cards handed off and waiting for Anki are not touched.",
    ]
    left: list[str] = []
    if plan.handed_off:
        left.append(f"{_n(plan.handed_off, 'card')} handed off and waiting for Anki")
    if plan.in_filtered:
        left.append(f"{_n(plan.in_filtered, 'card')} in a filtered deck")
    if left:
        lines.append("Left alone now: " + ", ".join(left) + ".")
    lines += ["", f'Edit → Undo "{UNDO_LABEL}" reverts it.']
    return "\n".join(lines)


def failure_text(exc: Exception) -> str:
    if isinstance(exc, HoldBackFailed) and exc.rolled_back:
        return f"Holding the cards back failed, and nothing was changed: {exc.cause}"
    return (
        f"Holding the cards back failed: {exc}. Some changes may have been made: "
        f'check Edit → Undo "{UNDO_LABEL}".'
    )
