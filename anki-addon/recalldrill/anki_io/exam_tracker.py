"""Read the exam tracker's inputs and make its numbers (v0.4 step 2). Read only.

docs/DECISIONS.md, "Step 2: real numbers (v0.4.0)". ``exam_tracker.py`` (pure) has the rules;
this module gathers what they need from the collection, ``pacing.json``, the history files
and the revlog, in as few reads as it can:

- one pass over the decks and ``pacing.json`` to find the exam decks and each deck's scope;
- one SQL read of the scope's cards (with their note tags);
- one revlog read per top-level deck (shared by the pace and the answer-time rates);
- one search per exam deck for the reviews (``-is:new -is:suspended prop:due<=N``).

Everything is keyed by deck id. It never writes the collection: no tag, no suspend, no due
date, no simulator.
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date
from typing import Any, cast

from anki.collection import Collection, SearchNode
from anki.decks import DeckId

from .. import history_store, pacing
from ..exam import inherited
from ..exam_tracker import (
    Rates,
    TrackerNumbers,
    compute,
    daily_steps,
    pace_total,
    pace_window,
    reviews_horizon,
)
from ..measure import RevlogRow, anki_day, is_counted, iso_ms
from ..sections import CardFacts, bucket
from ..storage import PACING, Storage
from .sections import undrillable_new
from .workload import deck_revlog, speed_for, today_for

BATCH = 500
DAY_MS = 86_400_000
BURIED_QUEUES = (-2, -3)
"""User-buried and scheduler-buried. Anki's ``prop:due`` skips them; the tracker counts them."""
DAY_NUMBER_LIMIT = 1_000_000
"""A card's ``due`` below this is a day number; above, an epoch-seconds time (intraday learning)."""


@dataclass(frozen=True)
class TrackerResult:
    day: date
    """Anki's today when the numbers were made."""
    numbers: dict[int, TrackerNumbers]
    """Per exam deck id."""


@dataclass(frozen=True)
class _CardRow:
    cid: int
    nid: int
    type: int
    queue: int
    due: int
    home: int
    """Its home deck: the original deck while it sits in a filtered deck."""
    tags: tuple[str, ...]


def _db(col: Collection) -> Any:
    db = col.db
    assert db is not None, "the collection is closed"
    return db


def exam_scopes(
    col: Collection, storage: Storage, today: date
) -> tuple[dict[int, date], dict[int, list[int]]]:
    """({exam deck id: its exam date}, {exam deck id: the home decks in its scope}).

    A deck is an exam deck when its own ``pacing.json`` entry has an ``exam_date`` that is
    today or later. Its scope is the deck and its subdecks, minus each subdeck subtree that
    has its own exam date: ``exam.inherited`` over the deck chain (nearest date wins), so the
    two screens that use exam dates can't disagree."""
    names = {int(d.id): str(d.name) for d in col.decks.all_names_and_ids()}
    by_name = {n: i for i, n in names.items()}
    raw = storage.read_json(PACING, {})
    entries = cast(dict[str, Any], raw) if isinstance(raw, dict) else {}
    exam_of: dict[int, date] = {}
    for did in names:
        day = pacing.settings_from_json(entries.get(str(did))).exam_date
        if day is not None:
            exam_of[did] = day

    def chain(did: int) -> list[int]:
        parts = names[did].split("::")
        out = [did]
        for i in range(len(parts) - 1, 0, -1):
            parent = by_name.get("::".join(parts[:i]))
            if parent is not None:
                out.append(parent)
        return out

    exams = {did: day for did, day in exam_of.items() if day >= today}
    scopes: dict[int, list[int]] = {did: [] for did in exams}
    for did in names:
        owner = inherited(chain(did), exam_of.get)
        if owner is not None and owner.did in scopes:
            scopes[owner.did].append(did)
    return exams, scopes


def _scope_rows(col: Collection, home_decks: Sequence[int]) -> dict[int, _CardRow]:
    """Every card whose home deck (its original deck while in a filtered deck) is one of
    ``home_decks``, with its note's tags."""
    if not home_decks:
        return {}
    ids = ",".join(map(str, sorted(home_decks)))
    rows = _db(col).all(
        "select c.id, c.nid, c.type, c.queue, c.due, c.did, c.odid, n.tags from cards c "
        f"join notes n on n.id = c.nid where c.did in ({ids}) or c.odid in ({ids})"
    )
    return {
        int(cid): _CardRow(
            int(cid),
            int(nid),
            int(type_),
            int(queue),
            int(due),
            int(odid) or int(did),
            tuple(str(tags).split()),
        )
        for cid, nid, type_, queue, due, did, odid, tags in rows
    }


def _handoffs(lines: Iterable[Mapping[str, Any]], rollover: int) -> list[tuple[int, date]]:
    """(card id, Anki day) of every drilled card of every handoff line (declined ones aside)."""
    out: list[tuple[int, date]] = []
    for line in lines:
        if line.get("type") != "handoff" or line.get("declined"):
            continue
        stamp = line.get("timestamp")
        ms = iso_ms(stamp) if isinstance(stamp, str) else None
        if ms is None:
            continue
        day = anki_day(ms, rollover)
        for card in cast(list[Any], line.get("cards") or []):
            cid = cast(dict[str, Any], card).get("cid") if isinstance(card, dict) else None
            if isinstance(cid, int) and not isinstance(cid, bool):
                out.append((cid, day))
    return out


def _buried_reviews(
    rows: Iterable[_CardRow], day_number: int, day_cutoff: int, horizon: int
) -> int:
    """Buried review and learning cards due on or before day ``today + horizon``."""
    n = 0
    for r in rows:
        if r.type == 0 or r.queue not in BURIED_QUEUES:
            continue
        limit = day_number + horizon if r.due < DAY_NUMBER_LIMIT else day_cutoff + horizon * 86_400
        n += r.due <= limit
    return n


def _rates(
    col: Collection, storage: Storage, top_name: str, top_revlog: Sequence[RevlogRow], now_ms: int
) -> Rates:
    """Seconds a card takes in this top-level deck: the setup panel's measured drill speed
    (``speed_for``) and the last 30 days of Don's own answer times (``revlog_times``).
    A missing figure stays None; nothing is invented."""
    speed = speed_for(col, storage, top_name)
    times = pacing.revlog_times(top_revlog, now_ms - pacing.REVLOG_DAYS * DAY_MS)
    enough = times.enough
    return Rates(
        drill_s=speed.overall_s if speed is not None else None,
        new_s=(
            times.learn_ratings_per_card * times.learn_ms / 1000
            if enough and times.learn_ms is not None
            else None
        ),
        review_s=times.review_ms / 1000 if enough and times.review_ms is not None else None,
    )


def read_trackers(col: Collection, storage: Storage, now_ms: int | None = None) -> TrackerResult:
    """The numbers of every exam deck, by deck id."""
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    today, rollover = today_for(col, now)
    exams, scopes = exam_scopes(col, storage, today)
    if not exams:
        return TrackerResult(today, {})
    rows = _scope_rows(col, [d for homes in scopes.values() for d in homes])
    owner_of: dict[int, int] = {h: did for did, homes in scopes.items() for h in homes}
    by_exam: dict[int, list[_CardRow]] = {did: [] for did in exams}
    for r in rows.values():
        by_exam[owner_of[r.home]].append(r)
    drilled = history_store.handed_off_by_addon(storage)
    undrillable = undrillable_new(
        col,
        storage,
        ((r.cid, r.type == 0, r.tags) for r in rows.values()),
        drilled,
    )
    lines = history_store.read_every_log(storage)
    handoffs = _handoffs(lines, rollover)
    # Cards a handoff actually drilled (not siblings or holdout): done once drilled.
    drilled_cards = frozenset(c for c, _day in handoffs)
    day_number = int(col.sched.today)
    day_cutoff = int(col.sched.day_cutoff)
    top_rows: dict[int, list[RevlogRow]] = {}
    out: dict[int, TrackerNumbers] = {}
    for did, exam in exams.items():
        scope = by_exam[did]
        cids = {r.cid for r in scope}
        counts = _counts(scope, drilled, undrillable, drilled_cards)
        finish_before = pacing.load(storage, did).finish_days_before
        horizon = reviews_horizon(exam, today, finish_before)
        deck_name = col.decks.name(DeckId(did))
        found = col.find_cards(
            col.build_search_string(
                SearchNode(deck=deck_name), "-is:new", "-is:suspended", f"prop:due<={horizon}"
            )
        )
        reviews = sum(1 for c in found if int(c) in cids) + _buried_reviews(
            scope, day_number, day_cutoff, horizon
        )
        top_name = deck_name.split("::")[0]
        top_did = col.decks.id_for_name(top_name)
        if top_did is None:  # can't happen: the top-level deck exists while a child does
            continue
        top = int(top_did)
        if top not in top_rows:
            top_rows[top] = deck_revlog(col, top)
        scope_rev = [r for r in top_rows[top] if r.cid in cids]
        ratings = [(r.cid, anki_day(r.id, rollover)) for r in scope_rev if is_counted(r)]
        steps = daily_steps(((c, d) for c, d in handoffs if c in cids), ratings, drilled_cards)
        earliest = min((r.nid for r in scope), default=None)
        window = pace_window(anki_day(earliest, rollover) if earliest is not None else None, today)
        numbers = compute(
            exam=exam,
            today=today,
            drill=counts.drill,
            new=counts.new,
            reviews=reviews,
            done_today=steps.get(today, 0),
            pace_total=pace_total(steps, today, window),
            pace_days=window,
            rates=_rates(col, storage, top_name, top_rows[top], now),
            finish_days_before=finish_before,
        )
        if numbers is not None:
            out[did] = numbers
    return TrackerResult(today, out)


@dataclass(frozen=True)
class _Counts:
    drill: int
    new: int


def _counts(
    scope: Sequence[_CardRow],
    drilled: set[int] | frozenset[int],
    undrillable: set[int],
    drilled_cards: set[int] | frozenset[int] = frozenset(),
) -> _Counts:
    """Drill to go and New for one scope, in cards, each card once (docs/DECISIONS.md,
    "Cards, not steps").

    - **Drill to go**: cards in the sections table's "held / waiting" bucket; can't-drill
      cards are a bucket of their own (``sections.bucket``), so they are excluded.
    - **New**: new cards that will need a first Anki rating and were **not drilled**: every
      unsuspended new card (queue new or buried) that no handoff drilled (``drilled_cards``:
      the handoff lines' ``cards``; siblings and holdout cards handed off undrilled still
      count), plus held cards the drill can't take (they go to Anki undrilled). A drilled
      card is done; a Drill-to-go card is counted once, under Drill."""
    drill = new = 0
    for r in scope:
        facts = CardFacts(r.cid, r.type == 0, r.queue == -1, r.tags, r.cid in undrillable)
        b = bucket(facts, drilled)
        if b == "held":
            drill += 1
        elif r.type == 0 and r.queue != -1:
            if r.cid not in drilled_cards:
                new += 1
        elif b == "cant_drill" and bucket(replace(facts, undrillable=False), drilled) == "held":
            new += 1
    return _Counts(drill, new)
