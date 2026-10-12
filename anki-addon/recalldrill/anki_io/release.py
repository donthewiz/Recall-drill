"""Send waiting drill cards to Anki undrilled (2026-10-12): plan, then apply.

The add-on's second collection write, next to the handoff (``handoff.py``),
and built the same way: :func:`plan_release` reads fresh card state and
decides (writes nothing); :func:`apply_release`, run by the UI inside
``CollectionOp``, makes it one undo step, "Recall Drill: send undrilled", and on
any failure merges what ran into that step and undoes it.

What a release does to a deck's waiting cards (``waiting.py``):

- ``released``: the cards themselves, still new and suspended: unsuspended.
- ``released_siblings``: their notes' other suspended new cards: unsuspended.
- Both stay new and keep their new-queue positions (no reposition, no bury),
  so Anki introduces them in deck order at the deck's new/day.
- Their notes get the tag ``rd::undrilled`` (where missing).

Cards that are gone, no longer new or no longer suspended are left alone, so
planning again right after a release plans nothing.
"""

from __future__ import annotations

import logging
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, OpChanges
from anki.consts import CARD_TYPE_NEW, QUEUE_TYPE_SUSPENDED
from anki.decks import DeckId
from anki.errors import NotFoundError
from anki.notes import NoteId

from ..waiting import TAG_UNDRILLED, UNDO_LABEL, release_line
from .cards import CardSnapshot, NoteCache, has_tag, snapshot

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ReleasePlan:
    did: int
    deck: str
    released: tuple[int, ...]
    siblings: tuple[int, ...]
    tag_notes: tuple[int, ...]
    """Notes that get ``rd::undrilled`` (the ones without it)."""
    skipped: tuple[int, ...]
    """Asked-for cards that are gone, or no longer new and suspended."""
    new_per_day: int
    """The deck's new cards per day (its own limit, else its preset's)."""

    @property
    def unsuspend(self) -> tuple[int, ...]:
        return self.released + self.siblings

    @property
    def cards(self) -> int:
        return len(self.unsuspend)

    @property
    def days(self) -> int | None:
        """Days the deck's new/day spreads the cards over (None at new/day 0)."""
        if self.new_per_day <= 0:
            return None
        return math.ceil(self.cards / self.new_per_day)

    @property
    def has_changes(self) -> bool:
        return bool(self.unsuspend or self.tag_notes)


class ReleaseFailed(Exception):
    """The release raised; ``rolled_back`` says whether everything was undone."""

    def __init__(self, cause: Exception, rolled_back: bool) -> None:
        super().__init__(str(cause))
        self.cause = cause
        self.rolled_back = rolled_back


def _waiting(s: CardSnapshot) -> bool:
    return s.type == CARD_TYPE_NEW and s.queue == QUEUE_TYPE_SUSPENDED


def build_release_plan(
    did: int,
    deck: str,
    asked: Sequence[int],
    snaps: Mapping[int, CardSnapshot],
    note_cards: Mapping[int, Sequence[CardSnapshot]],
    new_per_day: int,
) -> ReleasePlan:
    """Pure: ``snaps`` holds the asked-for cards that still exist,
    ``note_cards`` every card of their notes."""
    released = tuple(c for c in asked if c in snaps and _waiting(snaps[c]))
    skipped = tuple(c for c in asked if c not in released)
    taken = set(released)
    siblings: list[int] = []
    nids: list[int] = []
    for cid in released:
        nid = snaps[cid].nid
        if nid in nids:
            continue
        nids.append(nid)
        for s in note_cards.get(nid, ()):
            if s.cid not in taken and _waiting(s):
                taken.add(s.cid)
                siblings.append(s.cid)
    tag_notes = tuple(
        n
        for n in nids
        if not any(has_tag(s.tags, TAG_UNDRILLED) for s in note_cards.get(n, ())[:1])
    )
    return ReleasePlan(
        did, deck, released, tuple(siblings), tag_notes, skipped, max(0, new_per_day)
    )


def _new_per_day(col: Collection, did: int) -> int:
    conf = col.decks.config_dict_for_deck_id(DeckId(did))
    deck = cast(Mapping[str, Any], col.decks.get(DeckId(did)) or {})
    own = deck.get("newLimit")
    if isinstance(own, int) and not isinstance(own, bool):
        return own
    return int(conf["new"]["perDay"])


def plan_release(col: Collection, did: int, cids: Iterable[int]) -> ReleasePlan:
    """What sending these waiting cards to Anki would do, read fresh. Writes nothing."""
    asked = list(dict.fromkeys(int(c) for c in cids))
    notes = NoteCache(col)
    snaps: dict[int, CardSnapshot] = {}
    for cid in asked:
        try:
            card = col.get_card(CardId(cid))
        except NotFoundError:
            continue
        snaps[cid] = snapshot(card, notes.get(card.nid))
    note_cards: dict[int, list[CardSnapshot]] = {}
    for s in snaps.values():
        if s.nid in note_cards:
            continue
        note = notes.get(s.nid)
        note_cards[s.nid] = [snapshot(c, note) for c in note.cards()]
    return build_release_plan(
        did, col.decks.name(DeckId(did)), asked, snaps, note_cards, _new_per_day(col, did)
    )


def _roll_back(col: Collection, pos: int) -> bool:
    try:
        col.merge_undo_entries(pos)
        if col.undo_status().undo != UNDO_LABEL:
            return False
        col.undo()
    except Exception:
        log.exception("Recall Drill: rolling back a failed release failed")
        return False
    return True


def _apply_steps(col: Collection, plan: ReleasePlan) -> None:
    if plan.tag_notes:
        col.tags.bulk_add([NoteId(n) for n in plan.tag_notes], TAG_UNDRILLED)
    if plan.unsuspend:
        # Only suspended cards are passed: unsuspend_cards also unburies.
        col.sched.unsuspend_cards([CardId(c) for c in plan.unsuspend])


def apply_release(col: Collection, plan: ReleasePlan) -> OpChanges:
    """Runs the plan as one undo step ("Recall Drill: send undrilled"). On
    failure, undoes what it did and raises :class:`ReleaseFailed`."""
    pos = col.add_custom_undo_entry(UNDO_LABEL)
    try:
        _apply_steps(col, plan)
        return col.merge_undo_entries(pos)
    except Exception as exc:
        raise ReleaseFailed(exc, _roll_back(col, pos)) from exc


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def describe(plan: ReleasePlan) -> str:
    """The confirmation: counts, siblings, and the days new/day spreads them over."""
    lines = [
        f"Send {_n(len(plan.released), 'drill card')} in {plan.deck} to Anki undrilled?",
        "",
        "They are unsuspended and stay new cards, in their current place in the new "
        f"queue (nothing is buried or moved). Their notes get the tag {TAG_UNDRILLED}.",
    ]
    if plan.siblings:
        lines.append(
            f"Their notes' other suspended new cards go too: {_n(len(plan.siblings), 'sibling')}."
        )
    if plan.skipped:
        lines.append(
            f"{_n(len(plan.skipped), 'card')} no longer waiting (gone, studied or "
            "unsuspended) are left alone."
        )
    days = plan.days
    if days is None:
        lines.append("This deck's new cards/day is 0: Anki won't show them until you raise it.")
    else:
        lines.append(
            f"At this deck's {plan.new_per_day} new cards/day, Anki introduces these "
            f"{_n(plan.cards, 'card')} over about {_n(days, 'day')} (with the deck's other "
            "new cards)."
        )
    lines += ["", f'Edit → Undo "{UNDO_LABEL}" reverts it.']
    return "\n".join(lines)


def history_line(plan: ReleasePlan, at_ms: float) -> dict[str, Any]:
    return release_line(plan.did, plan.released, plan.siblings, plan.tag_notes, at_ms)


def failure_text(exc: Exception) -> str:
    if isinstance(exc, ReleaseFailed) and exc.rolled_back:
        return f"Sending the cards failed, and nothing was changed: {exc.cause}"
    return (
        f"Sending the cards failed: {exc}. Some changes may have been made: "
        f'check Edit → Undo "{UNDO_LABEL}".'
    )
