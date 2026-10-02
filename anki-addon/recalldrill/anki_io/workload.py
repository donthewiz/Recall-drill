"""Time figures from the collection: Anki's FSRS simulator, the revlog fallback,
the drill-speed history, and the pacing section's data. Read only, except
for what Anki's own simulator writes (below).

docs/DECISIONS.md, "Pacing (Phase 6)". The arithmetic is in ``pacing.py``
(pure); this module reads what it needs.

**Anki minutes** (the review time the planned cards add, and the daily load):

1. **FSRS simulator** (``col._backend.simulate_fsrs_review``, the one behind the
   deck options' FSRS "Simulator"). Checked on 26.08.1
   (``tests/anki_io/test_workload.py``): the request takes the preset's FSRS
   params, desired retention, ``search``, ``deck_size`` (new cards to add on
   top of the search's unsuspended new cards), ``new_limit``, ``review_limit``,
   ``days_to_simulate``, the step counts and the rest of the preset; the
   response's ``daily_time_cost`` is **seconds** per day and index 0 is
   **today**. Its per-rating times come from the revlog of the searched cards,
   each blended with fsrs-rs's built-in defaults by ``n / (50 + n)`` (no revlog:
   the defaults alone), so the figure is shown only when the deck has at least
   :data:`.pacing.MIN_RATINGS` learning and as many review ratings of Don's.
   Suspended new cards aren't in the simulation, so the scope's remaining
   suspended new cards (and their siblings) are passed as ``deck_size``.
   Anki's simulator computes and **stores** a memory state for any searched
   review card that lacks one (e.g. a card handed off with ``set_due_date``),
   exactly as the deck options' Simulator does.
2. **Revlog fallback**: the median ``time`` of Don's review and learning
   ratings over the last 30 days in the top-level deck, times the
   ``prop:due=N`` counts and the planned new cards.
3. Neither: "no estimate yet".
"""

from __future__ import annotations

import time
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, cast

from anki import scheduler_pb2
from anki.collection import Collection, SearchNode
from anki.decks import DeckId

from .. import history_store
from ..addon_config import AddonConfig
from ..engine.items import chunk_text, min_words_for
from ..engine.types import DeckItem, ItemOverrides
from ..launch import resolved
from ..measure import RevlogRow, anki_day
from ..pacing import (
    MIN_RATINGS,
    NO_ANKI_ESTIMATE,
    NO_DRILL_ESTIMATE,
    REVLOG_DAYS,
    SIMULATE_EXTRA_DAYS,
    AnkiLoad,
    DrillSpeed,
    PacingView,
    ceiling_warning,
    completed_today,
    compute_pace,
    drill_speed,
    planned_new,
    revlog_load,
    revlog_times,
)
from ..pacing import load as load_pacing
from ..storage import Storage
from .handoff import TOMORROW_DUE_QUERY
from .revlog import read_revlog
from .select import Selection

SIM_MAX_MILLIS = 1_200_000
"""fsrs-rs counts a rating's time only when ``0 < time < 1,200,000`` ms."""


def _db(col: Collection) -> Any:
    db = col.db
    assert db is not None, "the collection is closed"
    return db


def top_level(col: Collection, did: int) -> tuple[int, str] | None:
    """(id, name) of the deck's top-level deck, or None when the deck is gone."""
    if col.decks.get(DeckId(did), default=False) is None:
        return None
    parents = col.decks.parents(DeckId(did))
    top = parents[0] if parents else col.decks.get(DeckId(did))
    assert top is not None
    return int(top["id"]), str(top["name"])


def _limit(deck: Mapping[str, Any], key: str, preset: int) -> int:
    """The deck's own limit override (deck options' "This deck"), else the preset's."""
    v = deck.get(key)
    return v if isinstance(v, int) and not isinstance(v, bool) else preset


@dataclass(frozen=True)
class DeckLimits:
    new_per_day: int
    reviews_per_day: int


def deck_limits(col: Collection, did: int) -> DeckLimits:
    conf = col.decks.config_dict_for_deck_id(DeckId(did))
    deck = cast(Mapping[str, Any], col.decks.get(DeckId(did)) or {})
    return DeckLimits(
        _limit(deck, "newLimit", int(conf["new"]["perDay"])),
        _limit(deck, "reviewLimit", int(conf["rev"]["perDay"])),
    )


def _deck_search(col: Collection, did: int) -> str:
    return col.build_search_string(SearchNode(deck=col.decks.name(DeckId(did))))


def _count(col: Collection, *terms: str | SearchNode) -> int:
    return len(col.find_cards(col.build_search_string(*terms)))


# ---------------------------------------------------------------------------
# 1. The FSRS simulator
# ---------------------------------------------------------------------------


def fsrs_params(conf: Mapping[str, Any]) -> list[float]:
    """The preset's FSRS parameters (FSRS-6, else FSRS-5, else the old key), or []."""
    for key in ("fsrsParams6", "fsrsParams5", "fsrsWeights"):
        v = conf.get(key)
        if isinstance(v, list) and v:
            return [float(x) for x in cast(list[Any], v)]
    return []


def simulator_request(
    col: Collection, did: int, *, new_limit: int, deck_size: int, days: int
) -> scheduler_pb2.SimulateFsrsReviewRequest | None:
    """The deck options' Simulator request for ``did`` (and its subdecks), or None
    when FSRS is off or the preset has no FSRS parameters."""
    if not col.get_config("fsrs", False):
        return None
    conf = col.decks.config_dict_for_deck_id(DeckId(did))
    params = fsrs_params(conf)
    if not params:
        return None
    limits = deck_limits(col, did)
    lapse = conf["lapse"]
    req = scheduler_pb2.SimulateFsrsReviewRequest(
        params=params,
        desired_retention=float(conf.get("desiredRetention", 0.9)),
        deck_size=max(0, deck_size),
        days_to_simulate=max(1, days),
        new_limit=max(0, new_limit),
        review_limit=limits.reviews_per_day,
        max_interval=int(conf["rev"].get("maxIvl", 36500)),
        search=_deck_search(col, did),
        new_cards_ignore_review_limit=bool(col.get_config("newCardsIgnoreReviewLimit", False)),
        easy_days_percentages=[float(x) for x in conf.get("easyDaysPercentages") or [1.0] * 7],
        review_order=cast(Any, int(conf.get("reviewOrder", 0))),
        historical_retention=float(conf.get("sm2Retention", 0.9)),
        learning_step_count=len(conf["new"].get("delays") or []),
        relearning_step_count=len(lapse.get("delays") or []),
    )
    if int(lapse.get("leechAction", 1)) == 0:  # 0 = suspend the leech
        req.suspend_after_lapse_count = int(lapse.get("leechFails", 8))
    return req


@dataclass(frozen=True)
class SimulatedDays:
    """``daily_*`` from the response; index 0 is today."""

    cost_s: tuple[float, ...]
    reviews: tuple[int, ...]
    new: tuple[int, ...]


def simulate(col: Collection, req: scheduler_pb2.SimulateFsrsReviewRequest) -> SimulatedDays:
    r = col._backend.simulate_fsrs_review(req)  # pyright: ignore[reportPrivateUsage]
    return SimulatedDays(
        tuple(float(x) for x in r.daily_time_cost),
        tuple(int(x) for x in r.daily_review_count),
        tuple(int(x) for x in r.daily_new_count),
    )


def simulator_ratings(col: Collection, search: str) -> tuple[int, int]:
    """(learning, review) ratings of the searched cards whose time fsrs-rs uses for
    its per-rating costs (its ``Learning`` and ``Review`` states)."""
    cids = col.find_cards(search)
    learn = review = 0
    db = _db(col)
    ids = [int(c) for c in cids]
    for i in range(0, len(ids), 500):
        batch = ",".join(map(str, ids[i : i + 500]))
        for type_, n in db.all(
            "select type, count() from revlog where cid in ("
            + batch
            + f") and time > 0 and time < {SIM_MAX_MILLIS} and ease between 1 and 4"
            " and type in (0, 1) group by type"
        ):
            if int(type_) == 0:
                learn += int(n)
            else:
                review += int(n)
    return learn, review


# ---------------------------------------------------------------------------
# 2. The revlog fallback
# ---------------------------------------------------------------------------


def due_counts(col: Collection, did: int, days: int) -> list[int]:
    """``prop:due=1`` … ``prop:due=days`` in the deck (index 0 is tomorrow)."""
    deck = SearchNode(deck=col.decks.name(DeckId(did)))
    first = _count(col, deck, TOMORROW_DUE_QUERY)
    return [first] + [_count(col, deck, f"prop:due={d}") for d in range(2, days + 1)]


def deck_revlog(col: Collection, top_did: int) -> list[RevlogRow]:
    return read_revlog(col, (int(c) for c in col.find_cards(_deck_search(col, top_did))))


# ---------------------------------------------------------------------------
# Anki minutes: 1, else 2, else none
# ---------------------------------------------------------------------------


def anki_load(
    col: Collection,
    did: int,
    *,
    today: date,
    new_per_day: int,
    deck_size: int,
    drill_days: Sequence[date],
    now_ms: int | None = None,
) -> AnkiLoad:
    """Tomorrow's and the peak day's minutes in Anki for ``did`` with
    ``new_per_day`` planned new cards on each drill day's handoff."""
    days = len(drill_days) + SIMULATE_EXTRA_DAYS
    reason = ""
    req = simulator_request(col, did, new_limit=new_per_day, deck_size=deck_size, days=days)
    if req is None:
        reason = "FSRS simulator not used: FSRS is off or the preset has no FSRS parameters."
    else:
        learn, review = simulator_ratings(col, req.search)
        if learn < MIN_RATINGS or review < MIN_RATINGS:
            reason = (
                "FSRS simulator not used: it would fall back on Anki's default answer times "
                f"(you have {learn} learning and {review} review ratings here; "
                f"it needs {MIN_RATINGS} of each)."
            )
        else:
            try:
                sim = simulate(col, req)
            except Exception as exc:  # the panel must still open
                reason = f"FSRS simulator failed ({exc})."
            else:
                return AnkiLoad.from_days(
                    "simulator",
                    sim.cost_s[1:],
                    today + timedelta(days=1),
                    f"FSRS simulator, your review times ({learn + review} ratings in this deck)",
                )

    top = top_level(col, did)
    if top is not None:
        now = now_ms if now_ms is not None else int(time.time() * 1000)
        times = revlog_times(deck_revlog(col, top[0]), now - REVLOG_DAYS * 86_400_000)
        if times.enough:
            handoff_days = {d + timedelta(days=1) for d in drill_days}
            coming = [today + timedelta(days=i + 1) for i in range(days)]
            new_by_day = [new_per_day if d in handoff_days else 0 for d in coming]
            seconds = revlog_load(times, due_counts(col, top[0], days), new_by_day)
            return AnkiLoad.from_days(
                "revlog",
                seconds,
                today + timedelta(days=1),
                f"your answer times, last {REVLOG_DAYS} days in {top[1]} "
                f"({times.ratings} ratings): reviews already due plus the planned new cards",
                reason,
            )
    return AnkiLoad("none", note=NO_ANKI_ESTIMATE, fallback_reason=reason)


# ---------------------------------------------------------------------------
# Drill speed
# ---------------------------------------------------------------------------


def line_top(col: Collection, line: Mapping[str, Any], cache: dict[int, str | None]) -> str | None:
    """The top-level deck most of a session line's cards came from."""
    dids: Counter[int] = Counter()
    for a in cast(list[Any], line.get("anki") or []):
        did = cast(dict[str, Any], a).get("did") if isinstance(a, dict) else None
        if isinstance(did, int) and not isinstance(did, bool):
            dids[did] += 1
    if not dids:
        return None
    did = dids.most_common(1)[0][0]
    if did not in cache:
        top = top_level(col, did)
        cache[did] = top[1] if top is not None else None
    return cache[did]


def speed_for(col: Collection, storage: Storage, top_name: str | None) -> DrillSpeed | None:
    """Drill speed in ``top_name`` (else every deck), from every history log."""
    lines = [x for x in history_store.read_every_log(storage) if x.get("type") == "session"]
    cache: dict[int, str | None] = {}
    deck = [x for x in lines if top_name is not None and line_top(col, x, cache) == top_name]
    return drill_speed(deck, lines)


def shapes(
    deck_items: Sequence[DeckItem],
    overrides: Sequence[ItemOverrides],
    chunk_difficulty: float,
    min_words: int,
) -> list[bool]:
    """Per card: drilled in chunks (True) or whole, as the session would build it."""
    out: list[bool] = []
    for i, item in enumerate(deck_items):
        o: ItemOverrides = overrides[i] if i < len(overrides) else {}
        chunks = chunk_text(item["back"], chunk_difficulty, min_words_for(o, min_words))
        out.append(chunks is not None)
    return out


def shape_counts(card_shapes: Sequence[bool], n: int) -> tuple[int, int]:
    """(chunked, whole) among the next ``n`` cards: the first ``n`` shapes, scaled
    at their own mix when ``n`` is larger."""
    if n <= 0:
        return 0, 0
    if not card_shapes:
        return 0, n
    if n <= len(card_shapes):
        chunked = sum(card_shapes[:n])
        return chunked, n - chunked
    chunked = round(n * sum(card_shapes) / len(card_shapes))
    return chunked, n - chunked


@dataclass(frozen=True)
class DrillEstimate:
    seconds: float | None
    source: str


def drill_estimate(speed: DrillSpeed | None, card_shapes: Sequence[bool], n: int) -> DrillEstimate:
    if speed is None:
        return DrillEstimate(None, NO_DRILL_ESTIMATE)
    chunked, whole = shape_counts(card_shapes, n)
    return DrillEstimate(speed.seconds(chunked, whole), speed.source())


# ---------------------------------------------------------------------------
# The pacing section
# ---------------------------------------------------------------------------


def today_for(col: Collection, now_ms: int | None = None) -> tuple[date, int]:
    """(Anki's today, the rollover hour)."""
    rollover = col.get_preferences().scheduling.rollover
    now = now_ms if now_ms is not None else int(time.time() * 1000)
    return anki_day(now, rollover), rollover


def read_pacing(
    col: Collection,
    storage: Storage,
    did: int,
    selection: Selection,
    card_shapes: Sequence[bool],
    speed: DrillSpeed | None,
    settings_draft: Mapping[str, Any],
    cfg: AddonConfig,
    now_ms: int | None = None,
) -> PacingView:
    """The Pacing section for deck ``did`` (deck scopes only)."""
    today, rollover = today_for(col, now_ms)
    history = history_store.read_all(storage, str(did))
    pace = compute_pace(
        today,
        load_pacing(storage, did),
        selection.pace_remaining,
        completed_today(history, today, rollover),
    )
    if pace.status != "ok":
        return PacingView(pace)
    n = pace.per_day
    est = drill_estimate(speed, card_shapes, n)
    remaining = max(1, selection.pace_remaining)
    ratio = selection.pace_siblings / remaining
    holdout_pct = resolved(cast(Any, settings_draft), cfg)["holdoutPct"]
    planned = planned_new(n, ratio, holdout_pct, cfg.handoff_mode, cfg.handoff_siblings)
    deck_size = selection.pace_suspended + (selection.pace_siblings if cfg.handoff_siblings else 0)
    load = anki_load(
        col,
        did,
        today=today,
        new_per_day=planned.total,
        deck_size=deck_size,
        drill_days=pace.days,
        now_ms=now_ms,
    )
    # The ceiling, like the Phase 4 forecast, is the top-level deck's.
    top = top_level(col, did)
    ceiling_did = top[0] if top is not None else did
    limits = deck_limits(col, ceiling_did)
    reviews_tomorrow = _count(
        col, SearchNode(deck=col.decks.name(DeckId(ceiling_did))), TOMORROW_DUE_QUERY
    )
    warning = ceiling_warning(
        cfg.handoff_mode, planned, limits.new_per_day, reviews_tomorrow, limits.reviews_per_day
    )
    return PacingView(pace, est.seconds, est.source, load, warning, planned)
