"""Exam tracker numbers (v0.4 step 2; pure, no Anki imports).

docs/DECISIONS.md, "v0.4 exam tracker" -> "Step 2: real numbers (v0.4.0)". Plain inputs
(counts, dates, per-day step totals, rates) in, a frozen :class:`TrackerNumbers` out. Every
figure the deck screen shows is made here, each by one function whose docstring quotes its rule.

The unit is a **step**: one drill, one first Anki rating of a new card, or one review. A card
that still has to be drilled needs two steps before the exam: the drill, then its first
Anki rating, so it counts in both *Drill to go* and *New*.

All days are Anki days (``measure.anki_day``): "today" is Anki's today.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from .pacing import minutes_text, short_date

Status = Literal["green", "amber", "red", "exam"]
"""``exam``: the exam is today (neutral, no judgement)."""

STATUS_WORD: dict[Status, str] = {
    "green": "On pace",
    "amber": "Slightly behind",
    "red": "Behind",
    "exam": "Exam today",
}
STATUS_ICON: dict[Status, str] = {"green": "✓", "amber": "▲", "red": "✖", "exam": "●"}

PACE_DAYS = 7
"""Pace: the average over this many Anki days before today."""
AMBER_FACTOR_NUM, AMBER_FACTOR_DEN = 5, 4
"""Red at 25% or more over pace: amber while needed <= 1.25 x pace (exact, in integers)."""
NO_ESTIMATE_TEXT = "Est. time: not enough history yet"


@dataclass(frozen=True)
class Rates:
    """Seconds one step takes, each from Don's own data (None: no such figure)."""

    drill_s: float | None = None
    new_s: float | None = None
    review_s: float | None = None


@dataclass(frozen=True)
class TrackerNumbers:
    """Everything the display needs for one exam deck."""

    exam_date: date
    days_left: int
    """0 on the exam day."""
    status: Status
    drill: int
    new: int
    reviews: int
    done_today: int
    needed: int | None
    """Needed a day; None on the exam day."""
    pace: float
    """Average steps a day over the pace window."""
    est_seconds: float | None
    """Seconds of work left today, or None (exam day, or a rate is missing)."""

    @property
    def cards_left(self) -> int:
        return self.drill + self.new + self.reviews

    @property
    def exam_today(self) -> bool:
        return self.days_left == 0


def days_left(exam: date, today: date) -> int:
    """Calendar days from today up to the day before the exam, counting today:
    Fri Oct 23 seen on Thu Oct 15 is 8. On the exam day itself 0. Negative: passed."""
    return (exam - today).days


def reviews_horizon(exam: date, today: date) -> int:
    """N in ``prop:due<=N``: days from today to the day before the exam (overdue
    cards are included because the search is "<=")."""
    return (exam - timedelta(days=1) - today).days


def needed_a_day(cards_left: int, done_today: int, days: int) -> int:
    """``ceil((Cards left + Done today) / Days left)``: fixed at the start of the day, so
    work done today raises "done today" toward it instead of moving it. A missed day leaves
    the same cards over one day fewer, so tomorrow's number rises (there is no "overdue")."""
    return math.ceil((cards_left + done_today) / days)


def pace_window(earliest_added: date | None, today: date) -> int:
    """How many days the pace averages: the last 7 Anki days before today, or, when the
    scope's earliest note was added fewer than 7 days ago, the days since then (at least 1)."""
    if earliest_added is None:
        return PACE_DAYS
    return max(1, min(PACE_DAYS, (today - earliest_added).days))


def status_for(
    cards_left: int, done_today: int, needed: int, pace_total: int, pace_days: int
) -> Status:
    """The rule (Don, 2026-10-15: red at 25%+ over pace). ``pace = pace_total / pace_days``.

    - green "On pace": Cards left is 0, or Done today >= Needed a day, or Needed <= Pace;
    - amber "Slightly behind": Needed <= 1.25 x Pace;
    - red "Behind": otherwise (Pace 0 with cards left included).

    Needed 61, Pace 50 -> amber; 63 -> red; 50 -> green. Compared in integers, so the
    boundary at exactly 1.25 x Pace is exact."""
    if cards_left == 0 or done_today >= needed or needed * pace_days <= pace_total:
        return "green"
    if needed * pace_days * AMBER_FACTOR_DEN <= pace_total * AMBER_FACTOR_NUM:
        return "amber"
    return "red"


def estimate_seconds(
    needed: int, done_today: int, drill: int, new: int, reviews: int, rates: Rates
) -> float | None:
    """Est. time today: the steps still to take today, ``max(0, Needed a day - Done today)``,
    split in the proportions of Drill / New / Reviews, times each kind's seconds a step.
    None when a rate a non-empty kind needs is missing: a rate is never invented."""
    left = drill + new + reviews
    remaining = max(0, needed - done_today)
    if left == 0 or remaining == 0:
        return 0.0
    total = 0.0
    for count, rate in ((drill, rates.drill_s), (new, rates.new_s), (reviews, rates.review_s)):
        if count == 0:
            continue
        if rate is None:
            return None
        total += remaining * count / left * rate
    return total


def est_text(seconds: float | None) -> str:
    """ "Est. 55 min today", "Est. under 1 min today", or the no-history line."""
    if seconds is None:
        return NO_ESTIMATE_TEXT
    return f"Est. {minutes_text(seconds).removeprefix('about ')} today"


def exam_text(exam: date) -> str:
    """ "Exam · Fri Oct 23". There is no exam kind in the data."""
    return f"Exam · {short_date(exam)}"


def compute(
    *,
    exam: date,
    today: date,
    drill: int,
    new: int,
    reviews: int,
    done_today: int,
    pace_total: int,
    pace_days: int,
    rates: Rates,
) -> TrackerNumbers | None:
    """The numbers for one exam deck, or None when the exam has passed (a passed exam shows
    nothing). ``pace_total``: steps over the pace window; ``pace_days``: its length."""
    left_days = days_left(exam, today)
    if left_days < 0:
        return None
    pace = pace_total / pace_days
    cards_left = drill + new + reviews
    if left_days == 0:
        return TrackerNumbers(exam, 0, "exam", drill, new, reviews, done_today, None, pace, None)
    needed = needed_a_day(cards_left, done_today, left_days)
    return TrackerNumbers(
        exam,
        left_days,
        status_for(cards_left, done_today, needed, pace_total, pace_days),
        drill,
        new,
        reviews,
        done_today,
        needed,
        pace,
        estimate_seconds(needed, done_today, drill, new, reviews, rates),
    )


def daily_steps(
    handoffs: Iterable[tuple[int, date]], ratings: Iterable[tuple[int, date]]
) -> Counter[date]:
    """Steps taken per Anki day in one scope. ``handoffs``: (card id, day) of each card a
    Recall Drill handoff drilled. ``ratings``: (card id, day) of each counted Anki rating
    (``measure.is_counted``), all history. A step is

    - a drill: a card handed off that day (each card once a day);
    - a first Anki rating: the day of a card's first counted rating (the card was new);
    - a review: a counted rating on a day after the card's first, each card once a day
      (the card was not new at the start of the day)."""
    out: Counter[date] = Counter()
    for _cid, day in set(handoffs):
        out[day] += 1
    days_by_card: dict[int, set[date]] = {}
    for cid, day in ratings:
        days_by_card.setdefault(cid, set()).add(day)
    for days in days_by_card.values():
        first = min(days)
        out[first] += 1
        for day in days:
            if day > first:
                out[day] += 1
    return out


def pace_total(steps: Mapping[date, int], today: date, window: int) -> int:
    """Steps over the ``window`` Anki days before today."""
    return sum(steps.get(today - timedelta(days=k), 0) for k in range(1, window + 1))
