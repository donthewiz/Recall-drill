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
- It leaves alone the cards the drill can never take (``select.content_check``:
  image occlusion, marked ineligible, unmapped, empty answer; v0.3.1): they go to
  Anki as usual.
- The same plan **repairs** cards already held that are undrillable: it unsuspends
  them and removes ``rd::held`` from notes with no held card left.
- It never touches a card Anki has already introduced (not new), a card in a
  filtered deck, or a buried card; and it never runs by itself.

Planning again right after a hold-back plans nothing. The handoff (``handoff.py``)
and the release (``release.py``) remove ``rd::held`` when they send the cards on.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, OpChanges, SearchNode
from anki.consts import CARD_TYPE_NEW, QUEUE_TYPE_NEW, QUEUE_TYPE_SUSPENDED
from anki.decks import DeckId
from anki.notes import NoteId

from .. import deck_settings
from ..history_store import handed_off_at
from ..holdback import TAG_HELD, UNDO_LABEL, HoldBack, effective, holdback_line
from ..storage import Storage
from .cards import CardSnapshot, NoteCache, has_tag, read_snapshots, snapshot
from .exam import deck_chain
from .notetypes import MappingTable, load_overrides
from .revlog import waiting_for_anki
from .select import content_check

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
    left_alone: tuple[int, ...] = ()
    """New unsuspended cards the drill can't take: they go to Anki as usual."""
    left_alone_reasons: tuple[tuple[str, int], ...] = ()
    """``left_alone`` by reason (``select.IneligibleReason``), most common first."""
    release: tuple[int, ...] = ()
    """Held cards the drill can't take: unsuspended by the apply."""
    untag_notes: tuple[int, ...] = ()
    """Notes that lose ``rd::held`` (no held card left)."""

    @property
    def cards(self) -> int:
        return len(self.suspend)

    @property
    def undrillable_held(self) -> int:
        return len(self.release)

    @property
    def has_changes(self) -> bool:
        return bool(self.suspend or self.tag_notes or self.release or self.untag_notes)


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
    undrillable: Mapping[int, str] | None = None,
    held: Iterable[CardSnapshot] = (),
    note_cards: Mapping[int, Sequence[CardSnapshot]] | None = None,
) -> HoldBackPlan:
    """Pure: ``snaps`` are the deck's new unsuspended cards, read fresh;
    ``waiting_for_anki`` the handed-off cards Anki hasn't rated since.
    ``undrillable`` maps a card id to why the drill can't take it; ``held`` are the
    deck's cards currently held (new, suspended, note tagged ``rd::held``) and
    ``note_cards`` every card of their notes."""
    waiting = frozenset(waiting_for_anki)
    bad = undrillable or {}
    suspend: list[int] = []
    tag_notes: list[int] = []
    left: list[int] = []
    reasons: Counter[str] = Counter()
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
        if s.cid in bad:
            left.append(s.cid)
            reasons[bad[s.cid]] += 1
            continue
        suspend.append(s.cid)
        if s.nid not in tag_notes and not has_tag(s.tags, TAG_HELD):
            tag_notes.append(s.nid)
    release = [s.cid for s in held if s.cid in bad]
    freed = set(release)
    untag: list[int] = []
    for s in held:
        if s.cid not in freed or s.nid in untag or not has_tag(s.tags, TAG_HELD):
            continue
        cards = (note_cards or {}).get(s.nid) or [s]
        if not any(
            c.type == CARD_TYPE_NEW and c.queue == QUEUE_TYPE_SUSPENDED and c.cid not in freed
            for c in cards
        ):
            untag.append(s.nid)
    return HoldBackPlan(
        did,
        deck,
        tuple(suspend),
        tuple(tag_notes),
        handed,
        filtered,
        tuple(left),
        tuple(sorted(reasons.items(), key=lambda kv: (-kv[1], kv[0]))),
        tuple(release),
        tuple(untag),
    )


def plan_hold_back(
    col: Collection, storage: Storage, did: int, mappings: MappingTable | None = None
) -> HoldBackPlan:
    """What holding back this deck (with its subdecks) would do, read fresh. Writes
    nothing."""
    name = col.decks.name(DeckId(did))
    cids = [
        int(c)
        for c in col.find_cards(
            col.build_search_string(SearchNode(deck=name), "is:new", "-is:suspended", "-is:buried")
        )
    ]
    notes = NoteCache(col)
    snaps = read_snapshots(col, cids, notes)
    held_snaps = read_snapshots(col, held_cards(col, did), notes)
    table = mappings if mappings is not None else MappingTable(col, load_overrides(storage))
    undrillable: dict[int, str] = {}
    for s in [*snaps, *held_snaps]:
        reason, _answer = content_check(col, s, table.for_card(s.ntid, s.ord), notes)
        if reason is not None:
            undrillable[s.cid] = reason
    note_cards = {
        s.nid: [snapshot(c, notes.get(s.nid)) for c in notes.get(s.nid).cards()]
        for s in held_snaps
        if s.cid in undrillable
    }
    wanted = set(cids)
    handed = {c: t for c, t in handed_off_at(storage).items() if c in wanted}
    return build_hold_back_plan(
        did,
        name,
        snaps,
        waiting_for_anki(col, handed),
        undrillable,
        held_snaps,
        note_cards,
    )


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
    if plan.release:
        col.sched.unsuspend_cards([CardId(c) for c in plan.release])
    if plan.untag_notes:
        col.tags.bulk_remove([NoteId(n) for n in plan.untag_notes], TAG_HELD)


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
    """The confirmation: what is suspended and tagged, what is released, what is left alone."""
    lines: list[str] = []
    if plan.suspend or plan.tag_notes:
        lines += [
            f"Keep {_n(plan.cards, 'new card')} in {plan.deck} out of Anki until drilled?",
            "",
            f"They are suspended and their notes get the tag {TAG_HELD}. Drill them in the "
            "setup panel; the handoff unsuspends them, or send them to Anki undrilled "
            "(Tools → Recall Drill → More → Waiting cards).",
            "Cards Anki has already introduced, cards in a filtered deck, buried cards and "
            "cards handed off and waiting for Anki are not touched.",
        ]
    else:
        lines.append(f"Update the held cards in {plan.deck}?")
    if plan.release:
        lines += [
            "",
            f"Release {_n(plan.undrillable_held, 'held card')} the drill can't take "
            "(e.g. image occlusion): they are unsuspended and go to Anki as usual"
            + (
                f", and {_n(len(plan.untag_notes), 'note')} lose {TAG_HELD}."
                if plan.untag_notes
                else "."
            ),
        ]
    left: list[str] = []
    if plan.handed_off:
        left.append(f"{_n(plan.handed_off, 'card')} handed off and waiting for Anki")
    if plan.in_filtered:
        left.append(f"{_n(plan.in_filtered, 'card')} in a filtered deck")
    if left:
        lines.append("Left alone now: " + ", ".join(left) + ".")
    if plan.left_alone:
        why = ", ".join(f"{n} {r.replace('_', ' ')}" for r, n in plan.left_alone_reasons)
        lines.append(
            f"Left alone: {_n(len(plan.left_alone), 'card')} the drill can't take "
            f"(e.g. {plan.left_alone_reasons[0][0].replace('_', ' ')}; {why}); "
            "they go to Anki as usual."
        )
    lines += ["", f'Edit → Undo "{UNDO_LABEL}" reverts it.']
    return "\n".join(lines)


def history_line(plan: HoldBackPlan, at_ms: float) -> dict[str, Any]:
    return holdback_line(
        plan.did,
        plan.suspend,
        plan.release,
        plan.left_alone,
        plan.tag_notes,
        plan.untag_notes,
        at_ms,
    )


def failure_text(exc: Exception) -> str:
    if isinstance(exc, HoldBackFailed) and exc.rolled_back:
        return f"Holding the cards back failed, and nothing was changed: {exc.cause}"
    return (
        f"Holding the cards back failed: {exc}. Some changes may have been made: "
        f'check Edit → Undo "{UNDO_LABEL}".'
    )
