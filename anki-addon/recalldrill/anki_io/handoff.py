"""Hand a finished session to Anki: plan it (pure, over fresh snapshots), then
apply it as one undo step. Also tomorrow's load forecast and the dialog text.

When a session is complete (every card ``finalDone``), its cards go to Anki in
one confirmed, undoable step, and Anki owns their scheduling from then on.
Struggles carry over as note tags (they show in the Browser and sync).

Groups (``docs/DECISIONS.md``, "Handoff (Phase 4)"):

- ``drilled_new``: drilled cards that are new now (``type == 0``), suspended
  or not. **A**: unsuspend, ``set_due_date("1")``. **B**: unsuspend, reposition
  to the front of the new queue in drill order, bury (manual).
- ``drilled_scheduled``: every other drilled card (learning, review,
  relearning; suspended leeches and red-flagged repair cards too). Unsuspended
  if suspended; its schedule is never changed. If it's due today or overdue it
  is buried, so its first Anki rating comes tomorrow, not minutes after the drill.
- ``siblings`` (``handoff_siblings``): the notes' other cards that weren't in
  the session and are new and suspended: unsuspended, repositioned right after
  the drilled cards, buried. The same for A and B.
- ``holdout``: empty until Phase 5.

``reposition_new_cards`` gives one position **per note**, in the order the
notes first appear in the list, to the cards it's given (a note's cards share
it). So siblings in the same call would share their drilled card's position;
they get a second call that starts right after the drilled cards' notes.

Every action is only planned where it changes something, so planning again
right after a handoff plans nothing.

Writes happen only in :func:`apply_handoff`, which the UI runs inside
``aqt.operations.CollectionOp``. Each backend call is its own transaction, so
on any failure the calls already made are merged into the handoff's undo entry
and undone: nothing is left half-applied.
"""

from __future__ import annotations

import logging
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, cast

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, OpChanges, SearchNode
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_SIBLING_BURIED,
    QUEUE_TYPE_SUSPENDED,
)
from anki.decks import DeckId
from anki.errors import NotFoundError
from anki.notes import NoteId

from ..addon_config import AddonConfig, HandoffMode
from ..engine.history import card_trouble_score
from ..engine.jscompat import js_iso_string
from ..engine.types import DrillItem
from ..sessions import saved_sources
from .cards import RED_FLAG, CardSnapshot, NoteCache, has_tag, snapshot

log = logging.getLogger(__name__)

UNDO_LABEL = "Recall Drill handoff"
TAG_DRILLED = "rd::drilled"
TAG_HARD = "rd::hard"
TAG_FINAL_MISS = "rd::final-miss"
TAG_LONG = "rd::long"
REPLACED_TAGS = (TAG_HARD, TAG_FINAL_MISS)
"""Tags a handoff also removes from its notes when they no longer qualify."""
HARD_SEARCH = "tag:rd::hard"
"""An exact tag search (``tag:rd::*`` would also match the anki-cards ``rd::drill::*`` tags)."""

INTRADAY_DUE = 1_000_000_000
"""A learning card's ``due`` above this is an epoch-seconds time, else a day number."""
DAY_SECS = 86_400
TOMORROW_DUE_QUERY = "(prop:due=1 OR (is:learn prop:due<1))"
"""Reviews due tomorrow, plus learning cards due by then."""
LOAD_FACTOR = 1.5
"""Warn when tomorrow's reviews are more than this times the 7-day average."""

_DAYS = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


@dataclass(frozen=True)
class HandoffSettings:
    mode: HandoffMode = "B"
    siblings: bool = True
    hard_threshold: int = 3
    clear_flag: bool = True
    tag_long: bool = False

    @classmethod
    def from_config(cls, cfg: AddonConfig) -> HandoffSettings:
        return cls(
            mode=cfg.handoff_mode,
            siblings=cfg.handoff_siblings,
            hard_threshold=cfg.hard_threshold,
            clear_flag=cfg.clear_flag_on_handoff,
            tag_long=cfg.tag_long,
        )


@dataclass(frozen=True)
class DrilledCard:
    """A session card, with what the drill learned about it."""

    cid: int
    nid: int
    ord: int
    struggle: int
    """Misses + reveals + Final-check misses (``card_trouble_score``)."""
    final_misses: int
    chunked: bool


@dataclass(frozen=True)
class HandoffInput:
    """What :func:`build_plan` needs from the collection, read just before."""

    session_id: str
    drilled: tuple[DrilledCard, ...]
    """In drill order (the session's item order)."""
    snapshots: Mapping[int, CardSnapshot]
    """Every drilled card still in the collection, and every card of their notes."""
    note_cards: Mapping[int, tuple[int, ...]]
    """Note id -> all its card ids."""
    missing: tuple[int, ...]
    today: int
    day_cutoff: int
    """When the next day starts (epoch seconds, ``col.sched.day_cutoff``)."""


@dataclass(frozen=True)
class Reposition:
    """One ``reposition_new_cards`` call: one position per note, from ``start``."""

    cids: tuple[int, ...]
    start: int


@dataclass(frozen=True)
class HandoffPlan:
    session_id: str
    mode: HandoffMode
    drilled: tuple[DrilledCard, ...]
    """The drilled cards still in the collection, in drill order."""
    drilled_new: tuple[int, ...]
    drilled_scheduled: tuple[int, ...]
    siblings: tuple[int, ...]
    holdout: tuple[int, ...]
    missing: tuple[int, ...]
    # Actions, in the order apply_handoff runs them.
    tag_add: Mapping[str, tuple[int, ...]]
    """Tag -> note ids that get it."""
    tag_remove: Mapping[str, tuple[int, ...]]
    clear_flags: tuple[int, ...]
    unsuspend: tuple[int, ...]
    set_due: tuple[int, ...]
    reposition: tuple[Reposition, ...]
    """The front of the new queue: B's drilled new cards, then the siblings
    (empty when they hold those positions already)."""
    bury: tuple[int, ...]
    hard: frozenset[int]
    """Drilled cards at or over the hard threshold."""
    hard_threshold: int
    snapshots: Mapping[int, CardSnapshot]
    today: int
    day_cutoff: int

    @property
    def cards(self) -> int:
        return len(self.drilled_new) + len(self.drilled_scheduled)

    @property
    def tags_added(self) -> int:
        return sum(len(v) for v in self.tag_add.values())

    @property
    def tags_removed(self) -> int:
        return sum(len(v) for v in self.tag_remove.values())

    @property
    def front(self) -> tuple[int, ...]:
        """The new cards that join the front of the new queue: B's drilled new
        cards, then the siblings."""
        return (self.drilled_new if self.mode == "B" else ()) + self.siblings

    @property
    def buried_scheduled(self) -> tuple[int, ...]:
        bury = set(self.bury)
        return tuple(c for c in self.drilled_scheduled if c in bury)

    @property
    def schedule_actions(self) -> int:
        moved = sum(len(r.cids) for r in self.reposition)
        return len(self.unsuspend) + len(self.set_due) + moved + len(self.bury)

    @property
    def has_changes(self) -> bool:
        return bool(
            self.schedule_actions or self.clear_flags or self.tags_added or self.tags_removed
        )


class HandoffFailed(Exception):
    """:func:`apply_handoff` failed. ``rolled_back``: what it had done is undone."""

    def __init__(self, cause: Exception, rolled_back: bool) -> None:
        super().__init__(str(cause) or type(cause).__name__)
        self.cause = cause
        self.rolled_back = rolled_back


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------


def drilled_cards(saved: Mapping[str, Any]) -> tuple[DrilledCard, ...]:
    """The session's cards with their struggle, in drill order. Raises
    ``ValueError`` unless every card is ``finalDone``."""
    items = cast(list[DrillItem], saved.get("items") or [])
    if not items or not all(it.get("finalDone") for it in items):
        raise ValueError("the session isn't complete: only a finished session is handed off")
    sources = saved_sources(saved)
    out: list[DrilledCard] = []
    for it in sorted(items, key=lambda i: i["id"]):
        s = sources[it["id"]]
        out.append(
            DrilledCard(
                cid=s.cid,
                nid=s.nid,
                ord=s.ord,
                struggle=card_trouble_score(it),
                final_misses=it.get("finalMisses", 0),
                chunked=bool(it["chunks"]),
            )
        )
    return tuple(out)


def is_buried(s: CardSnapshot) -> bool:
    return s.queue in (QUEUE_TYPE_SIBLING_BURIED, QUEUE_TYPE_MANUALLY_BURIED)


def due_in_days(s: CardSnapshot, today: int, day_cutoff: int) -> int:
    """Days until a scheduled card is due (its home deck's due while it sits in
    a filtered deck): 0 or less is due today or overdue."""
    due = s.odue if s.odid and s.odue else s.due
    if s.type in (CARD_TYPE_LRN, CARD_TYPE_RELEARNING) and due > INTRADAY_DUE:
        return 0 if due < day_cutoff else 1 + (due - day_cutoff) // DAY_SECS
    return due - today


def note_positions(
    groups: Sequence[Sequence[int]], snaps: Mapping[int, CardSnapshot]
) -> tuple[tuple[Reposition, ...], dict[int, int]]:
    """The calls that put ``groups`` at the front of the new queue, one after
    the other, and the position each card gets (one per note)."""
    steps: list[Reposition] = []
    where: dict[int, int] = {}
    start = 0
    for group in groups:
        if not group:
            continue
        notes = list(dict.fromkeys(snaps[c].nid for c in group))
        for c in group:
            where[c] = start + notes.index(snaps[c].nid)
        steps.append(Reposition(tuple(group), start))
        start += len(notes)
    return tuple(steps), where


def build_plan(inp: HandoffInput, settings: HandoffSettings) -> HandoffPlan:
    snaps = inp.snapshots
    drilled = tuple(d for d in inp.drilled if d.cid in snaps)
    drilled_new = tuple(d.cid for d in drilled if snaps[d.cid].type == CARD_TYPE_NEW)
    drilled_scheduled = tuple(d.cid for d in drilled if snaps[d.cid].type != CARD_TYPE_NEW)

    in_session = {d.cid for d in inp.drilled}
    notes = list(dict.fromkeys(snaps[d.cid].nid for d in drilled))
    siblings: list[int] = []
    if settings.siblings:
        for nid in notes:
            others = sorted(
                (snaps[c] for c in inp.note_cards.get(nid, ()) if c not in in_session),
                key=lambda s: s.ord,
            )
            siblings += [
                s.cid for s in others if s.type == CARD_TYPE_NEW and s.queue == QUEUE_TYPE_SUSPENDED
            ]

    handed = drilled_new + drilled_scheduled + tuple(siblings)
    unsuspend = tuple(c for c in handed if snaps[c].queue == QUEUE_TYPE_SUSPENDED)
    if settings.mode == "A":
        set_due = drilled_new
        front = tuple(siblings)
    else:
        set_due = ()
        front = drilled_new + tuple(siblings)
    steps, where = note_positions(
        [drilled_new if settings.mode == "B" else (), tuple(siblings)], snaps
    )
    in_place = all(snaps[c].new_position == p for c, p in where.items())
    reposition = () if in_place else steps
    due_now = tuple(
        c for c in drilled_scheduled if due_in_days(snaps[c], inp.today, inp.day_cutoff) <= 0
    )
    bury = tuple(c for c in front + due_now if not is_buried(snaps[c]))
    clear_flags = (
        tuple(d.cid for d in drilled if snaps[d.cid].flags == RED_FLAG)
        if settings.clear_flag
        else ()
    )

    hard = frozenset(d.cid for d in drilled if d.struggle >= settings.hard_threshold)
    tag_add: dict[str, list[int]] = {}
    tag_remove: dict[str, list[int]] = {}
    for nid in notes:
        cards = [d for d in drilled if snaps[d.cid].nid == nid]
        tags = snaps[cards[0].cid].tags
        want = {
            TAG_DRILLED: True,
            TAG_HARD: any(d.cid in hard for d in cards),
            TAG_FINAL_MISS: any(d.final_misses > 0 for d in cards),
        }
        if settings.tag_long:
            want[TAG_LONG] = any(d.chunked for d in cards)
        for tag, on in want.items():
            present = has_tag(tags, tag)
            if on and not present:
                tag_add.setdefault(tag, []).append(nid)
            elif not on and present and tag in REPLACED_TAGS:
                tag_remove.setdefault(tag, []).append(nid)

    return HandoffPlan(
        session_id=inp.session_id,
        mode=settings.mode,
        drilled=drilled,
        drilled_new=drilled_new,
        drilled_scheduled=drilled_scheduled,
        siblings=tuple(siblings),
        holdout=(),
        missing=inp.missing,
        tag_add={t: tuple(n) for t, n in tag_add.items()},
        tag_remove={t: tuple(n) for t, n in tag_remove.items()},
        clear_flags=clear_flags,
        unsuspend=unsuspend,
        set_due=set_due,
        reposition=reposition,
        bury=bury,
        hard=hard,
        hard_threshold=settings.hard_threshold,
        snapshots=snaps,
        today=inp.today,
        day_cutoff=inp.day_cutoff,
    )


def reviews_tomorrow(plan: HandoffPlan) -> tuple[int, ...]:
    """The handed-off cards that are reviews tomorrow: A's drilled new cards
    (due tomorrow) and drilled scheduled cards due by tomorrow (the ones due
    today are buried until then)."""
    sched = tuple(
        c
        for c in plan.drilled_scheduled
        if due_in_days(plan.snapshots[c], plan.today, plan.day_cutoff) <= 1
    )
    return (plan.set_due if plan.mode == "A" else ()) + sched


# ---------------------------------------------------------------------------
# Collection: read, then apply
# ---------------------------------------------------------------------------


def read_input(col: Collection, saved: Mapping[str, Any]) -> HandoffInput:
    """A fresh snapshot of every session card (Don may have reviewed on his
    phone or edited since the session started) and of their notes' other cards."""
    drilled = drilled_cards(saved)
    notes = NoteCache(col)
    snaps: dict[int, CardSnapshot] = {}
    missing: list[int] = []
    for d in drilled:
        try:
            card = col.get_card(CardId(d.cid))
        except NotFoundError:
            missing.append(d.cid)
            continue
        snaps[d.cid] = snapshot(card, notes.get(card.nid))
    note_cards: dict[int, tuple[int, ...]] = {}
    for nid in dict.fromkeys(s.nid for s in list(snaps.values())):
        cids = tuple(int(c) for c in col.card_ids_of_note(NoteId(nid)))
        note_cards[nid] = cids
        for cid in cids:
            if cid not in snaps:
                snaps[cid] = snapshot(col.get_card(CardId(cid)), notes.get(nid))
    addon = cast(Mapping[str, Any], saved["addon"])
    return HandoffInput(
        session_id=str(addon["sessionId"]),
        drilled=drilled,
        snapshots=snaps,
        note_cards=note_cards,
        missing=tuple(missing),
        today=col.sched.today,
        day_cutoff=col.sched.day_cutoff,
    )


def plan_handoff(
    col: Collection, saved: Mapping[str, Any], settings: HandoffSettings
) -> HandoffPlan:
    """What a handoff of this finished session would do, read fresh. Writes nothing."""
    return build_plan(read_input(col, saved), settings)


def _cids(ids: Iterable[int]) -> list[CardId]:
    return [CardId(i) for i in ids]


def _apply_steps(col: Collection, plan: HandoffPlan) -> None:
    for tag, nids in plan.tag_add.items():
        col.tags.bulk_add([NoteId(n) for n in nids], tag)
    for tag, nids in plan.tag_remove.items():
        col.tags.bulk_remove([NoteId(n) for n in nids], tag)
    if plan.clear_flags:
        col.set_user_flag_for_cards(0, _cids(plan.clear_flags))
    if plan.unsuspend:
        # restore_buried_and_suspended_cards: only ever pass suspended cards,
        # or it unburies too.
        col.sched.unsuspend_cards(_cids(plan.unsuspend))
    if plan.set_due:
        col.sched.set_due_date(_cids(plan.set_due), "1")
    for step in plan.reposition:
        col.sched.reposition_new_cards(
            _cids(step.cids),
            starting_from=step.start,
            step_size=1,
            randomize=False,
            shift_existing=True,
        )
    if plan.bury:
        col.sched.bury_cards(_cids(plan.bury), manual=True)


def _roll_back(col: Collection, pos: int) -> bool:
    """Merge what ran into the handoff's undo entry and undo it."""
    try:
        col.merge_undo_entries(pos)
        if col.undo_status().undo != UNDO_LABEL:
            return False
        col.undo()
    except Exception:
        log.exception("Recall Drill: rolling back a failed handoff failed")
        return False
    return True


def apply_handoff(col: Collection, plan: HandoffPlan) -> OpChanges:
    """Runs the plan as one undo step ("Recall Drill handoff"): tags, flags,
    unsuspend, then set-due or reposition, then bury. On failure, undoes what
    it did and raises :class:`HandoffFailed`."""
    pos = col.add_custom_undo_entry(UNDO_LABEL)
    try:
        _apply_steps(col, plan)
        return col.merge_undo_entries(pos)
    except Exception as exc:
        raise HandoffFailed(exc, _roll_back(col, pos)) from exc


# ---------------------------------------------------------------------------
# Tomorrow's load
# ---------------------------------------------------------------------------


def next_day_start(now: datetime, rollover_hour: int) -> datetime:
    """When Anki's next day starts: today at the rollover hour, or tomorrow's if
    that's past. Drilling at 1 AM with a 4 AM rollover, that's the same morning."""
    start = now.replace(hour=rollover_hour, minute=0, second=0, microsecond=0)
    return start if now < start else start + timedelta(days=1)


def format_when(dt: datetime) -> str:
    """ "Sat Oct 3, 4:00 AM" (English names, whatever the locale)."""
    hour = dt.hour % 12 or 12
    ampm = "AM" if dt.hour < 12 else "PM"
    return f"{_DAYS[dt.weekday()]} {_MONTHS[dt.month - 1]} {dt.day}, {hour}:{dt.minute:02d} {ampm}"


def spill(new_cards: int, limit: int) -> int:
    """Handed-off new cards that don't fit in tomorrow's new/day limit."""
    return max(0, new_cards - max(0, limit))


@dataclass(frozen=True)
class Forecast:
    mode: HandoffMode
    deck_id: int
    deck_name: str
    available_from: datetime
    reviews: int
    """Reviews due tomorrow in the deck, with the handoff."""
    reviews_added: int
    """Of those, handed-off cards the plain search doesn't count yet."""
    review_limit: int
    avg_reviews_7d: float
    """The deck's average of ``prop:due=1`` … ``prop:due=7``."""
    new_cards: int
    """Handed-off new cards joining the front of the deck's new queue."""
    new_limit: int
    new_spill: int
    collection_reviews: int

    @property
    def warnings(self) -> tuple[str, ...]:
        out: list[str] = []
        if self.new_spill:
            out.append(
                f"{_n(self.new_cards, 'new card')} tomorrow, over the deck's new/day limit "
                f"of {self.new_limit}: {self.new_spill} spill to the following day."
            )
        if self.reviews > self.review_limit:
            out.append(
                f"{_n(self.reviews, 'review')} due tomorrow, over the deck's review limit "
                f"of {self.review_limit}."
            )
        if self.reviews > LOAD_FACTOR * self.avg_reviews_7d:
            out.append(
                f"{_n(self.reviews, 'review')} due tomorrow: more than {LOAD_FACTOR:g}× "
                f"this deck's average over the next 7 days ({self.avg_reviews_7d:.1f})."
            )
        return tuple(out)

    def to_json(self) -> dict[str, Any]:
        return {
            "deckId": self.deck_id,
            "deckName": self.deck_name,
            "availableFrom": self.available_from.isoformat(timespec="minutes"),
            "reviews": self.reviews,
            "reviewsAdded": self.reviews_added,
            "reviewLimit": self.review_limit,
            "avgReviews7d": round(self.avg_reviews_7d, 2),
            "newCards": self.new_cards,
            "newLimit": self.new_limit,
            "newSpill": self.new_spill,
            "collectionReviews": self.collection_reviews,
            "warnings": list(self.warnings),
        }


def top_deck_for(col: Collection, plan: HandoffPlan, fallback: int | None = None) -> int | None:
    """The top-level deck of the deck holding most of the drilled cards."""
    homes = Counter(plan.snapshots[c].home_did for c in plan.drilled_new + plan.drilled_scheduled)
    did = homes.most_common(1)[0][0] if homes else fallback
    if did is None:
        return None
    parents = col.decks.parents(DeckId(did))
    return int(parents[0]["id"]) if parents else did


def _limit(deck: Mapping[str, Any], key: str, preset: int) -> int:
    """The deck's own limit override (deck options' "This deck"), else the preset's."""
    v = deck.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else preset


def forecast(
    col: Collection, plan: HandoffPlan, top_deck_id: int, now: datetime | None = None
) -> Forecast:
    """Tomorrow's load in ``top_deck_id`` (with subdecks) after this handoff."""
    did = DeckId(top_deck_id)
    name = col.decks.name(did)
    deck = SearchNode(deck=name)

    def find(*terms: str | SearchNode) -> set[int]:
        return {int(c) for c in col.find_cards(col.build_search_string(*terms))}

    planned = plan.drilled_new + plan.drilled_scheduled + plan.siblings
    in_deck = find(deck, f"cid:{','.join(map(str, planned))}") if planned else set[int]()
    handoff_reviews = set(reviews_tomorrow(plan))
    base = find(deck, TOMORROW_DUE_QUERY)
    added = (handoff_reviews & in_deck) - base
    days = [len(find(deck, f"prop:due={d}")) for d in range(1, 8)]

    conf = col.decks.config_dict_for_deck_id(did)
    deck_dict = cast(Mapping[str, Any], col.decks.get(did) or {})
    new_limit = _limit(deck_dict, "newLimit", int(conf["new"]["perDay"]))
    review_limit = _limit(deck_dict, "reviewLimit", int(conf["rev"]["perDay"]))
    new_cards = sum(1 for c in plan.front if c in in_deck)
    rollover = col.get_preferences().scheduling.rollover
    return Forecast(
        mode=plan.mode,
        deck_id=top_deck_id,
        deck_name=name,
        available_from=next_day_start(now or datetime.now(), rollover),
        reviews=len(base) + len(added),
        reviews_added=len(added),
        review_limit=review_limit,
        avg_reviews_7d=sum(days) / 7,
        new_cards=new_cards,
        new_limit=new_limit,
        new_spill=spill(new_cards, new_limit),
        collection_reviews=len(find(TOMORROW_DUE_QUERY) | handoff_reviews),
    )


# ---------------------------------------------------------------------------
# What the dialog says, and the history line
# ---------------------------------------------------------------------------


def _n(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


def first_review_wording(mode: HandoffMode, when: str) -> str:
    if mode == "A":
        return f"become review cards due from {when} (no learning steps)"
    return f"stay new, front of the queue, available from {when}"


@dataclass(frozen=True)
class HandoffText:
    headline: str
    lines: tuple[str, ...]
    forecast: tuple[str, ...]
    warnings: tuple[str, ...]

    def plain(self) -> str:
        parts = [self.headline, "", *self.lines]
        if self.forecast:
            parts += ["", *self.forecast]
        parts += [f"⚠ {w}" for w in self.warnings]
        return "\n".join(parts)


def _tag_breakdown(plan: HandoffPlan) -> str:
    bits = [f"{t} +{len(n)}" for t, n in plan.tag_add.items()]
    bits += [f"{t} −{len(n)}" for t, n in plan.tag_remove.items()]
    return f" ({', '.join(bits)})" if bits else ""


def describe(plan: HandoffPlan, fc: Forecast | None, when: datetime) -> HandoffText:
    """The confirmation dialog's text. ``when``: the next day's start."""
    w = format_when(when)
    if plan.drilled_new:
        headline = (
            f"Hand off {_n(plan.cards, 'card')}: tag, unsuspend, "
            f"{first_review_wording(plan.mode, w)}."
        )
    else:
        headline = f"Hand off {_n(plan.cards, 'card')}: tag, unsuspend; they keep their schedule."
    lines: list[str] = []
    sched = len(plan.drilled_scheduled)
    if plan.drilled_new and sched:
        lines.append(
            f"{_n(sched, 'card')} already scheduled in Anki "
            f"{'keeps its' if sched == 1 else 'keep their'} schedule."
        )
    buried = len(plan.buried_scheduled)
    if buried:
        lines.append(
            f"{_n(buried, 'scheduled card')} due today "
            f"{'is' if buried == 1 else 'are'} buried until {w}."
        )
    if plan.missing:
        lines.append(f"{_n(len(plan.missing), 'card')} from the session no longer exist: skipped.")
    after = "right after the drilled cards" if plan.mode == "B" else "at the front of the new queue"
    sib = len(plan.siblings)
    lines.append(
        f"Siblings: {sib}"
        + (
            f" (suspended new cards of the same notes): unsuspended, queued {after}, "
            f"available from {w}."
            if sib
            else "."
        )
    )
    lines.append(f"Tags: +{plan.tags_added} / −{plan.tags_removed}{_tag_breakdown(plan)}.")
    if plan.clear_flags:
        lines.append(f"Red flag cleared on {_n(len(plan.clear_flags), 'card')}.")

    fc_lines: list[str] = []
    if fc is not None:
        fc_lines.append(f"Tomorrow in {fc.deck_name} (from {format_when(fc.available_from)}):")
        fc_lines.append(
            f"• New cards: {fc.new_cards} from this handoff join the front of the new queue "
            f"(new/day {fc.new_limit})."
        )
        added = f", {fc.reviews_added} from this handoff" if fc.reviews_added else ""
        fc_lines.append(
            f"• Reviews: {fc.reviews} due{added} (review limit {fc.review_limit}; "
            f"7-day average {fc.avg_reviews_7d:.1f})."
        )
        fc_lines.append(f"• Whole collection: {_n(fc.collection_reviews, 'review')} due tomorrow.")
    return HandoffText(
        headline=headline,
        lines=tuple(lines),
        forecast=tuple(fc_lines),
        warnings=fc.warnings if fc is not None else (),
    )


def handoff_line(plan: HandoffPlan, fc: Forecast | None, at_ms: float) -> dict[str, Any]:
    """The ``type: "handoff"`` history line for an applied plan."""
    by_tag: dict[str, dict[str, int]] = {}
    for tag, nids in plan.tag_add.items():
        by_tag.setdefault(tag, {"added": 0, "removed": 0})["added"] = len(nids)
    for tag, nids in plan.tag_remove.items():
        by_tag.setdefault(tag, {"added": 0, "removed": 0})["removed"] = len(nids)
    return {
        "type": "handoff",
        "sessionId": plan.session_id,
        "mode": plan.mode,
        "timestamp": js_iso_string(at_ms),
        "groups": {
            "drilled_new": list(plan.drilled_new),
            "drilled_scheduled": list(plan.drilled_scheduled),
            "siblings": list(plan.siblings),
            "holdout": list(plan.holdout),
            "missing": list(plan.missing),
        },
        "actions": {
            "unsuspended": list(plan.unsuspend),
            "setDue": list(plan.set_due),
            "repositioned": [{"cids": list(r.cids), "start": r.start} for r in plan.reposition],
            "buried": list(plan.bury),
            "flagsCleared": list(plan.clear_flags),
        },
        "tags": {"added": plan.tags_added, "removed": plan.tags_removed, "byTag": by_tag},
        "hardThreshold": plan.hard_threshold,
        "cards": [
            {
                "cid": d.cid,
                "nid": d.nid,
                "ord": d.ord,
                "struggle": d.struggle,
                "finalMisses": d.final_misses,
                "chunked": d.chunked,
                "hard": d.cid in plan.hard,
            }
            for d in plan.drilled
        ],
        "forecast": fc.to_json() if fc is not None else None,
    }


DONE_MESSAGE = 'Handed off. Edit → Undo "Recall Drill handoff" reverts it.'
STILL_PENDING = "The session is still waiting for its handoff."


def failure_text(exc: Exception) -> str:
    """What the UI says when :func:`apply_handoff` (or the op around it) fails."""
    if isinstance(exc, HandoffFailed):
        if exc.rolled_back:
            return (
                "The handoff failed, and what it had done was undone: nothing changed in "
                f"Anki. {STILL_PENDING}\n\n{exc}"
            )
        return (
            "The handoff failed partway, and undoing it failed too. Check Edit → Undo: "
            f'"{UNDO_LABEL}" reverts what it did. {STILL_PENDING}\n\n{exc}'
        )
    return f"The handoff failed: {exc}. {STILL_PENDING}"
