"""The light outcomes export (v0.3, pure): 14-day cost and exam-day recall.

docs/DECISIONS.md, "v0.3: whole-section drilling, exam dates, export".

Next to ``measure.py``, which keeps every definition (Anki day, counted rating,
drilled card's ``t0`` = handoff, holdout card's ``t0`` = introduction, the
next-day outcome). This module only adds:

- **14-day cost** (:func:`window_cost`): over the counted ratings on Anki days
  ``day(t0)`` through ``day(t0) + 13``: the sum of their answer times
  (``ankiSeconds``) and the count of Agains (``ankiAgain``). ``complete`` once
  day 13 has passed. Day 14 is out. A rating earlier on day 0 than ``t0`` is in:
  the window is by Anki day, as the primary outcome is.
- **Predicted recall on exam day** (:func:`recall_on_exam`) from Anki's FSRS memory
  state: ``R = (1 + factor * t / S) ** -decay`` with ``factor = 0.9 ** (-1 /
  decay) - 1``, ``S`` the card's stability, ``decay`` the card's own, else its
  preset's (:data:`LAST_RESORT_DECAY` only when neither is known), and ``t`` the
  days from its last counted review to its exam date. A new card, a card with
  no memory state, no exam date, or an exam already past: empty, never a guess.
- The CSV (:func:`outcomes_csv`): one row per drilled card (per handoff) and
  holdout card, the rows the tuning report reads (``tuning.card_rows``).
"""

from __future__ import annotations

import csv
import io
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo

from .measure import AGAIN, RevlogRow, anki_day, counted
from .tuning import CardRow

WINDOW_DAYS = 14
"""The cost window: Anki days ``day(t0)`` through ``day(t0) + 13``."""
LAST_RESORT_DECAY = 0.1542
"""FSRS-6's default decay: used only when neither the card nor its preset gives one."""
RECALL_TARGET = 0.9
"""The retrievability at ``t == S`` by definition of the formula's factor."""


@dataclass(frozen=True)
class WindowCost:
    anki_seconds: float
    """Sum of the window's counted ratings' ``time`` (revlog milliseconds), in seconds."""
    again: int
    ratings: int
    complete: bool
    """Day ``day(t0) + 13`` has passed."""


def window_cost(
    rows: Iterable[RevlogRow],
    t0_ms: int,
    rollover_hour: int,
    now_ms: float,
    tz: tzinfo | None = None,
) -> WindowCost:
    """The card's cost over its 14-day window; ``rows`` are its revlog rows."""
    first = anki_day(t0_ms, rollover_hour, tz)
    last = first + timedelta(days=WINDOW_DAYS - 1)
    total_ms = 0
    agains = 0
    n = 0
    for r in counted(rows):
        if first <= anki_day(r.id, rollover_hour, tz) <= last:
            total_ms += r.time
            agains += r.ease == AGAIN
            n += 1
    return WindowCost(total_ms / 1000, agains, n, anki_day(now_ms, rollover_hour, tz) > last)


# ---------------------------------------------------------------------------
# Predicted recall on exam day
# ---------------------------------------------------------------------------


def decay_factor(decay: float) -> float:
    """``0.9 ** (-1 / decay) - 1``: makes ``R == 0.9`` at ``t == S``."""
    return RECALL_TARGET ** (-1 / decay) - 1


def retrievability(stability: float, days: float, decay: float) -> float | None:
    """FSRS-6 retrievability after ``days`` at ``stability`` and ``decay``; None
    for a stability or decay that isn't positive, or negative days."""
    if stability <= 0 or decay <= 0 or days < 0:
        return None
    return (1 + decay_factor(decay) * days / stability) ** -decay


@dataclass(frozen=True)
class MemoryFacts:
    """What Anki says about a card's memory (read through its API)."""

    is_new: bool
    stability: float | None
    """``card.memory_state.stability``, or None without a memory state."""
    decay: float | None = None
    """``card.decay``, or None."""
    preset_decay: float | None = None
    """The card's preset's decay (``col.compute_memory_state``), or None."""


def recall_on_exam(
    memory: MemoryFacts | None,
    last_review: date | None,
    exam: date | None,
) -> float | None:
    """The predicted recall on ``exam``; None whenever any input is missing."""
    if memory is None or memory.is_new or memory.stability is None:
        return None
    if last_review is None or exam is None:
        return None
    decay = memory.decay if memory.decay else memory.preset_decay
    return retrievability(
        memory.stability, (exam - last_review).days, decay if decay else LAST_RESORT_DECAY
    )


# ---------------------------------------------------------------------------
# The CSV
# ---------------------------------------------------------------------------

GROUPS = ("drilled", "holdout")
OUTCOME_COLUMNS = (
    "group",
    "cid",
    "nid",
    "homeDeck",
    "sessionId",
    "t0",
    "status",
    "elapsed_days",
    "ease",
    "again",
    "ankiSeconds",
    "ankiAgain",
    "complete",
    "activeMs",
    "attempts",
    "misses",
    "reveals",
    "words",
    "chunks",
    "encodeReps",
    "examDate",
    "recallOnExam",
)
"""The tuning report's CSV names for the next-day outcome (``status``, ``elapsed_days``,
``ease``, ``again``), then the new columns."""


@dataclass(frozen=True)
class OutcomeRecord:
    row: CardRow
    cost: WindowCost | None
    exam: date | None
    recall: float | None


def _local(ms: int | None, tz: tzinfo | None) -> str:
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz).isoformat(timespec="seconds")


def records(
    card_rows: Iterable[CardRow],
    revlog: Iterable[RevlogRow],
    memory: Mapping[int, MemoryFacts],
    exams: Mapping[int, date | None],
    rollover_hour: int,
    now_ms: float,
    tz: tzinfo | None = None,
) -> list[OutcomeRecord]:
    """The drilled and holdout rows with their cost and exam-day recall. ``memory`` and
    ``exams`` are by card id."""
    by_cid: dict[int, list[RevlogRow]] = defaultdict(list)
    for r in revlog:
        by_cid[r.cid].append(r)
    out: list[OutcomeRecord] = []
    for row in card_rows:
        if row.group not in GROUPS:
            continue
        t0 = row.outcome.t0_ms
        cost = (
            window_cost(by_cid.get(row.cid, ()), t0, rollover_hour, now_ms, tz)
            if t0 is not None
            else None
        )
        exam = exams.get(row.cid)
        ratings = counted(by_cid.get(row.cid, ()))
        last = anki_day(ratings[-1].id, rollover_hour, tz) if ratings else None
        out.append(OutcomeRecord(row, cost, exam, recall_on_exam(memory.get(row.cid), last, exam)))
    return out


def outcomes_csv(recs: Sequence[OutcomeRecord], tz: tzinfo | None = None) -> str:
    """The export, LF line endings, one row per record."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(OUTCOME_COLUMNS)

    def cell(v: object) -> object:
        return "" if v is None else v

    for rec in recs:
        row, o, c = rec.row, rec.row.outcome, rec.cost
        w.writerow(
            [
                cell(x)
                for x in (
                    row.group,
                    row.cid,
                    row.nid,
                    row.deck,
                    row.session_id,
                    _local(o.t0_ms, tz),
                    o.status,
                    o.elapsed,
                    o.ease,
                    None if o.again is None else int(o.again),
                    None if c is None else round(c.anki_seconds, 3),
                    None if c is None else c.again,
                    None if c is None else int(c.complete),
                    row.active_ms,
                    row.attempts,
                    row.misses,
                    row.reveals,
                    row.words,
                    row.chunks,
                    row.encode_reps,
                    None if rec.exam is None else rec.exam.isoformat(),
                    None if rec.recall is None else round(rec.recall, 4),
                )
            ]
        )
    return buf.getvalue()
