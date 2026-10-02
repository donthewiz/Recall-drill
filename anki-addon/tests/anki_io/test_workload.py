"""anki_io/workload.py on a scratch collection: Anki's FSRS simulator (new facts
on 26.08.1), the revlog fallback, what pacing counts, and the pacing section.

**Facts checked here** (docs/DECISIONS.md, "Pacing (Phase 6)"):

- ``simulate_fsrs_review`` returns ``days_to_simulate`` entries per list;
  ``daily_time_cost`` is seconds; index 0 is today (its new cards are today's).
- Suspended new cards are not simulated; ``deck_size`` adds new cards.
- The total cost grows with ``new_limit``.
- Its per-rating times come from the searched cards' revlog: the same deck
  costs more with slow ratings than with fast ones, and with no revlog it uses
  fsrs-rs's built-in defaults (a few ratings barely move it: each time is
  blended with the default by ``n / (50 + n)``).
"""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import pytest
from anki.cards import FSRSMemoryState
from anki.collection import Collection
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.decks import DeckId
from anki_fixtures import BQE, add_bqe_model, add_bqe_note, add_note, deck, model

from recalldrill import history_store, pacing
from recalldrill.addon_config import DEFAULT_CONFIG
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.panel import options_for, read_panel
from recalldrill.anki_io.select import Scope, SelectOptions, select_cards
from recalldrill.anki_io.workload import (
    anki_load,
    read_pacing,
    simulate,
    simulator_ratings,
    simulator_request,
    speed_for,
    today_for,
)
from recalldrill.engine.jscompat import js_iso_string
from recalldrill.storage import Storage

# FSRS-6's default parameters (what an unoptimized preset would use).
P6 = [
    0.212, 1.2931, 2.3065, 8.2956, 6.4133, 0.8334, 3.0194, 0.001, 1.8722, 0.1666, 0.796,
    1.4835, 0.0614, 0.2629, 1.6483, 0.6014, 1.8729, 0.5425, 0.0912, 0.0658, 0.1542,
]  # fmt: skip
DAY_MS = 86_400_000


def _set_params(col: Collection, did: int, params: list[float] = P6) -> None:
    conf = col.decks.config_dict_for_deck_id(DeckId(did))
    conf["fsrsParams6"] = params
    col.decks.update_config(conf)


def _review_deck(
    col: Collection,
    name: str,
    *,
    reviews: int = 60,
    suspended_new: int = 40,
    rating_ms: int | None = 8000,
    ratings_per_card: tuple[tuple[int, int], ...] = ((0, 3), (0, 3), (1, 3)),
    ago_days: int = 10,
) -> int:
    """``reviews`` review cards (S 5, D 5, due over the next 5 days), each with
    ``ratings_per_card`` revlog rows (type, ease) of ``rating_ms``, plus
    ``suspended_new`` suspended new cards."""
    did = int(deck(col, name))
    m = model(col, "Basic")
    rid = int(time.time() * 1000) - ago_days * DAY_MS
    db = col.db
    assert db is not None
    for i in range(reviews):
        note = add_note(col, m, DeckId(did), {"Front": f"{name} q{i}", "Back": "a"})
        card = note.cards()[0]
        card.type = CARD_TYPE_REV
        card.queue = QUEUE_TYPE_REV
        card.ivl = 5
        card.due = col.sched.today + 1 + i % 5
        card.reps = len(ratings_per_card)
        card.factor = 2500
        card.memory_state = FSRSMemoryState(stability=5.0, difficulty=5.0)
        col.update_card(card)
        if rating_ms is None:
            continue
        for type_, ease in ratings_per_card:
            rid += 1000
            db.execute(
                "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
                "values (?, ?, 0, ?, 1, 0, 2500, ?, ?)",
                rid,
                card.id,
                ease,
                rating_ms,
                type_,
            )
    for i in range(suspended_new):
        add_note(col, m, DeckId(did), {"Front": f"{name} n{i}", "Back": "b"})
    new = col.find_cards(f'deck:"{name}" is:new')
    if new:
        col.sched.suspend_cards(new)
    return did


def _cost(col: Collection, did: int, *, new_limit: int = 5, deck_size: int = 40) -> float:
    req = simulator_request(col, did, new_limit=new_limit, deck_size=deck_size, days=20)
    assert req is not None
    return sum(simulate(col, req).cost_s)


# ---------------------------------------------------------------------------
# The simulator: facts
# ---------------------------------------------------------------------------


def test_request_comes_from_the_preset(col: Collection) -> None:
    did = _review_deck(col, "Bio")
    assert simulator_request(col, did, new_limit=5, deck_size=3, days=20) is None  # no params
    _set_params(col, did)
    req = simulator_request(col, did, new_limit=5, deck_size=3, days=20)
    assert req is not None
    assert list(req.params) == pytest.approx(P6)
    assert req.desired_retention == pytest.approx(0.9)
    assert (req.new_limit, req.deck_size, req.days_to_simulate) == (5, 3, 20)
    assert (req.review_limit, req.max_interval) == (200, 36500)
    assert (req.learning_step_count, req.relearning_step_count) == (2, 1)  # 1m 10m / 10m
    assert req.search == 'deck:"Bio"' or "Bio" in req.search
    assert not req.HasField("suspend_after_lapse_count")  # leech action: tag only
    col.set_config("fsrs", False)
    assert simulator_request(col, did, new_limit=5, deck_size=3, days=20) is None


def test_response_shape_units_and_new_limit(col: Collection) -> None:
    did = _review_deck(col, "Bio")
    _set_params(col, did)
    req = simulator_request(col, did, new_limit=5, deck_size=40, days=20)
    assert req is not None
    sim = simulate(col, req)
    assert len(sim.cost_s) == len(sim.reviews) == len(sim.new) == 20
    assert sim.new[:4] == (5, 5, 5, 5)  # index 0 is today: new cards from day 0
    assert sum(sim.new) == 40  # the 40 suspended new cards came in through deck_size only
    # Seconds, not ms: 8 s ratings give a few seconds to a few minutes per card-day.
    day = 1
    per_rating = sim.cost_s[day] / max(1, sim.reviews[day] + sim.new[day])
    assert 1 < per_rating < 120
    # The total grows with new_limit.
    totals = [_cost(col, did, new_limit=n) for n in (0, 5, 10)]
    assert totals[0] < totals[1] <= totals[2]
    # deck_size 0: the suspended new cards aren't simulated.
    req0 = simulator_request(col, did, new_limit=5, deck_size=0, days=20)
    assert req0 is not None and sum(simulate(col, req0).new) == 0


def test_time_cost_comes_from_my_revlog(col: Collection) -> None:
    fast = _review_deck(col, "Fast", rating_ms=2000)
    slow = _review_deck(col, "Slow", rating_ms=60_000)
    none = _review_deck(col, "None", rating_ms=None)
    thin = _review_deck(col, "Thin", reviews=60, rating_ms=None)
    # Thin: three 60 s ratings on one card, nothing else.
    db = col.db
    assert db is not None
    cid = col.find_cards('deck:"Thin" -is:new')[0]
    for k in range(3):
        db.execute(
            "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
            "values (?, ?, 0, 3, 1, 0, 2500, 60000, 1)",
            int(time.time() * 1000) - DAY_MS + k,
            cid,
        )
    for did in (fast, slow, none, thin):
        _set_params(col, did)
    c_fast, c_slow, c_none, c_thin = (_cost(col, d) for d in (fast, slow, none, thin))
    assert c_fast < c_none < c_slow
    assert c_slow > 2 * c_fast
    # A few ratings barely move it off the defaults: why the panel needs 50 of each.
    assert abs(c_thin - c_none) < 0.25 * (c_slow - c_none)
    assert simulator_ratings(col, 'deck:"Slow"') == (120, 60)
    assert simulator_ratings(col, 'deck:"None"') == (0, 0)


# ---------------------------------------------------------------------------
# Anki minutes: simulator, else revlog, else none
# ---------------------------------------------------------------------------


def test_anki_load_uses_the_simulator_with_enough_of_my_ratings(col: Collection) -> None:
    did = _review_deck(col, "Bio")
    _set_params(col, did)
    today, _ = today_for(col)
    days = [today + timedelta(days=i) for i in range(5)]
    load = anki_load(col, did, today=today, new_per_day=5, deck_size=40, drill_days=days)
    assert load.source == "simulator" and not load.fallback_reason
    req = simulator_request(col, did, new_limit=5, deck_size=40, days=5 + 14)
    assert req is not None
    sim = simulate(col, req)
    assert load.tomorrow_s == pytest.approx(sim.cost_s[1], rel=0.25)  # its own random draws
    assert load.peak_date is not None and load.peak_date > today
    assert "FSRS simulator, your review times (180 ratings" in load.note


def test_anki_load_falls_back_to_the_revlog_without_params(col: Collection) -> None:
    did = _review_deck(col, "Bio", ago_days=5)
    today, _ = today_for(col)
    days = [today + timedelta(days=i) for i in range(3)]
    load = anki_load(col, did, today=today, new_per_day=4, deck_size=40, drill_days=days)
    assert load.source == "revlog"
    assert "no FSRS parameters" in load.fallback_reason
    assert "180 ratings" in load.note
    # 12 reviews due tomorrow x 8 s, plus today's 4 handed-off cards x 2 learning ratings x 8 s.
    assert load.tomorrow_s == pytest.approx(12 * 8 + 4 * 2 * 8)


def test_anki_load_skips_the_simulator_when_it_would_use_defaults(col: Collection) -> None:
    did = _review_deck(col, "Bio", ratings_per_card=((1, 3),), reviews=30)  # 30 reviews only
    _set_params(col, did)
    today, _ = today_for(col)
    load = anki_load(col, did, today=today, new_per_day=4, deck_size=10, drill_days=[today])
    assert load.source == "none"
    assert "default answer times" in load.fallback_reason and "0 learning and 30 review" in (
        load.fallback_reason
    )
    assert load.note == pacing.NO_ANKI_ESTIMATE


def test_anki_load_none_without_data(col: Collection) -> None:
    did = _review_deck(col, "Med Term", reviews=0, rating_ms=None)
    today, _ = today_for(col)
    load = anki_load(col, did, today=today, new_per_day=10, deck_size=40, drill_days=[today])
    assert load.source == "none" and load.note == pacing.NO_ANKI_ESTIMATE


# ---------------------------------------------------------------------------
# What pacing counts (select.py)
# ---------------------------------------------------------------------------


def _med_term(col: Collection) -> tuple[int, int]:
    add_bqe_model(col)
    did = deck(col, "Med Term::Ch 3")
    for i in range(6):
        add_bqe_note(col, did, f"term{i}", f"meaning {i}")
    add_bqe_note(col, did, "drilled", "x", tags=["rd::drilled"])
    add_bqe_note(col, did, "held", "y", tags=["rd::holdout"])
    col.sched.suspend_cards(col.find_cards('deck:"Med Term"'))
    m = col.models.by_name(BQE)
    assert m is not None
    return int(did), int(m["id"])


def test_pace_counts_remaining_and_siblings(col: Collection) -> None:
    did, ntid = _med_term(col)
    table = MappingTable(col, {})
    everything = select_cards(col, Scope(deck_id=did), SelectOptions(), table)
    # 6 notes x 2 cards, minus the two tagged notes; classes off or capped don't matter.
    assert (everything.pace_remaining, everything.pace_suspended) == (12, 12)
    assert everything.pace_siblings == 0
    reverse = SelectOptions(card_ords={ntid: frozenset({1})}, max_cards=2, enabled=frozenset())
    sel = select_cards(col, Scope(deck_id=did), reverse, table)
    assert (sel.pace_remaining, sel.pace_siblings) == (6, 6)  # the Normal cards: siblings
    assert sel.picked == []
    # An unsuspended new card still counts (class new); a reviewed one doesn't.
    cids = col.find_cards('deck:"Med Term" card:2 -tag:rd::*')
    col.sched.unsuspend_cards(cids[:1])
    col.sched.set_due_date(cids[1:2], "1")
    sel = select_cards(col, Scope(deck_id=did), reverse, table)
    assert (sel.pace_remaining, sel.pace_suspended) == (5, 4)


# ---------------------------------------------------------------------------
# The pacing section, end to end
# ---------------------------------------------------------------------------


def _panel(col: Collection, st: Storage, did: int, ntid: int) -> Any:
    draft: Any = {"card_ords": {str(ntid): [1]}}
    options = options_for(
        draft, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )
    return read_panel(col, st, Scope(deck_id=did), options, draft, did, DEFAULT_CONFIG), draft


def test_read_pacing(col: Collection, tmp_path: Path) -> None:
    did, ntid = _med_term(col)
    st = Storage(tmp_path / "user_files", "User 1")
    today, _ = today_for(col)
    data, draft = _panel(col, st, did, ntid)

    view = read_pacing(col, st, did, data.selection, data.card_shapes, None, draft, DEFAULT_CONFIG)
    assert view.pace.status == "no_target"

    # Two weeks out, every day a drill day, finish 1 day early: 13 days for 6 cards.
    every_day = frozenset(range(7))
    pacing.save(st, did, pacing.PacingSettings(today + timedelta(days=14), every_day, 1))
    view = read_pacing(col, st, did, data.selection, data.card_shapes, None, draft, DEFAULT_CONFIG)
    assert view.pace.status == "ok" and view.pace.remaining == 6
    assert (view.pace.days_left, view.pace.per_day, view.pace.today_n) == (14, 1, 1)
    assert view.drill_s is None and view.drill_source == pacing.NO_DRILL_ESTIMATE
    assert view.anki.source == "none"  # all new: no ratings of mine yet
    assert view.planned == pacing.PlannedNew(1, 1, 0)  # its Normal sibling goes too
    assert view.warning is None
    assert view.line().startswith("Today: 1 card, drill time: no estimate yet.")

    # A session that completed today moves the first drill day to tomorrow.
    line = {"type": "session", "finishedAt": js_iso_string(time.time() * 1000)}
    st.append_jsonl(history_store.history_name(str(did)), line)
    view = read_pacing(col, st, did, data.selection, data.card_shapes, None, draft, DEFAULT_CONFIG)
    assert view.pace.done_today and view.pace.today_n == 0 and view.pace.days_left == 13

    # Tight: 6 cards in one day, over a new/day limit of 5 (B: drilled + siblings).
    pacing.save(st, did, pacing.PacingSettings(today + timedelta(days=2), every_day, 1))
    conf = col.decks.config_dict_for_deck_id(DeckId(did))
    conf["new"]["perDay"] = 5
    col.decks.update_config(conf)
    view = read_pacing(col, st, did, data.selection, data.card_shapes, None, draft, DEFAULT_CONFIG)
    assert view.pace.per_day == 6 and view.planned == pacing.PlannedNew(6, 6, 0)
    assert view.warning is not None and "Anki holds back 7" in view.warning

    # Under A: the drilled cards against the review limit's room.
    conf["rev"]["perDay"] = 2
    col.decks.update_config(conf)
    cfg_a = replace(DEFAULT_CONFIG, handoff_mode="A")
    view = read_pacing(col, st, did, data.selection, data.card_shapes, None, draft, cfg_a)
    assert view.warning is not None and "room for 2" in view.warning

    # Target passed.
    pacing.save(st, did, pacing.PacingSettings(today - timedelta(days=1)))
    view = read_pacing(col, st, did, data.selection, data.card_shapes, None, draft, DEFAULT_CONFIG)
    assert view.pace.status == "target_passed"


def test_drill_speed_from_the_history(col: Collection, tmp_path: Path) -> None:
    did, ntid = _med_term(col)
    other = int(deck(col, "Anatomy"))
    st = Storage(tmp_path / "user_files", "User 1")

    def session(day: int, target: int, ms: int) -> dict[str, Any]:
        return {
            "type": "session",
            "finishedAt": js_iso_string(time.time() * 1000 - day * DAY_MS),
            "activeMs": ms * 2,
            "cards": [{"chunks": 0}, {"chunks": 0}],
            "anki": [
                {"cid": 1, "did": target, "activeMs": ms},
                {"cid": 2, "did": target, "activeMs": ms},
            ],
        }

    for d in (1, 2):
        st.append_jsonl(history_store.history_name(str(did)), session(d, did, 20_000))
    for d in (3, 4, 5):
        st.append_jsonl(history_store.history_name(str(other)), session(d, other, 50_000))
    speed = speed_for(col, st, "Med Term")
    assert speed is not None and speed.scope == "all" and speed.sessions == 5
    st.append_jsonl(history_store.history_name(str(did)), session(0, did, 30_000))
    speed = speed_for(col, st, "Med Term")
    assert speed is not None and speed.scope == "deck" and speed.full_s == 20.0
    assert speed.source() == "your pace, last 3 timed sessions"
    data, _ = _panel(col, st, did, ntid)
    assert data.drillable == 8  # the tagged notes' Reverse cards are selectable too
    assert data.drill_seconds == pytest.approx(8 * 20.0)
    assert data.estimate_text() == "about 3 min"


def test_today_for_uses_the_rollover(col: Collection) -> None:
    today, rollover = today_for(col)
    assert rollover == col.get_preferences().scheduling.rollover
    assert isinstance(today, date)
