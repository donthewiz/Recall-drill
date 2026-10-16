"""Exam tracker numbers (v0.4 step 2; pure, no Anki imports).

docs/DECISIONS.md, "v0.4 exam tracker" -> "Step 2: real numbers (v0.4.0)". Plain inputs
(counts, dates, per-day card totals, rates) in, a frozen :class:`TrackerNumbers` out. Every
figure the deck screen shows is made here, each by one function whose docstring quotes its rule.

The unit is a **card** (Don, 2026-10-15, after "steps" read as confusing): each card left
before the exam counts once, as *Drill to go*, *New* or *Reviews*. A drilled card is done:
its first Anki rating the next day is not counted again (not in *New*, not in *Done today*,
not in the pace), but its time is part of the drill rate in the estimate, so the minutes stay
honest. (v0.4.0 counted "steps", where a card still to drill counted twice.)

All days are Anki days (``measure.anki_day``): "today" is Anki's today.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Collection, Iterable, Mapping
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
    """Seconds one card takes, each from Don's own data (None: no such figure). ``new_s``
    is a new card's first-day time in Anki (its learning ratings)."""

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
    """Average cards a day over the pace window."""
    est_seconds: float | None
    """Seconds of work left today, or None (exam day, or a rate is missing)."""
    finish_date: date | None = None
    """The day Don wants to be done: the exam date minus the deck's "finish N days before"
    (``pacing.json``, at least 1). None in older callers."""
    finish_passed: bool = False
    """The finish date has passed (the exam hasn't): the numbers count to the day before
    the exam instead."""

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


def finish_date(exam: date, finish_days_before: int) -> date:
    """The day Don wants to be done (Don, 2026-10-15): the exam date minus the deck's
    "finish N days before" setting from the setup panel's Pacing box (``pacing.json``
    ``finish_days_before``, the same number the drill pacing uses). At least 1 day before
    the exam: the exam day itself is never a study day here."""
    return exam - timedelta(days=max(1, finish_days_before))


def study_window(exam: date, today: date, finish_days_before: int = 1) -> tuple[date, bool]:
    """(the last day the numbers count to, whether the finish date has passed).

    The tracker counts down to the **finish date**. Once that has passed (and the exam
    hasn't), it counts to the day before the exam instead, so the work left still has days
    to spread over."""
    finish = finish_date(exam, finish_days_before)
    if today <= finish:
        return finish, False
    return exam - timedelta(days=1), True


def reviews_horizon(exam: date, today: date, finish_days_before: int = 1) -> int:
    """N in ``prop:due<=N``: days from today to the last day of the study window (the
    finish date, or the day before the exam once it has passed). Overdue cards are included
    because the search is "<="."""
    last, _passed = study_window(exam, today, finish_days_before)
    return (last - today).days


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
    """Est. time today: the cards still to do today, ``max(0, Needed a day - Done today)``,
    split in the proportions of Drill / New / Reviews, times each kind's seconds a card.
    A drilled card still gets its first Anki rating the next day, so a drill card costs the
    drill **plus** a new card's first day (``drill_s + new_s``): the count leaves that rating
    out, the minutes don't. None when a rate a non-empty kind needs is missing: a rate is
    never invented."""
    left = drill + new + reviews
    remaining = max(0, needed - done_today)
    if left == 0 or remaining == 0:
        return 0.0
    drill_rate = (
        rates.drill_s + rates.new_s
        if rates.drill_s is not None and rates.new_s is not None
        else None
    )
    total = 0.0
    for count, rate in ((drill, drill_rate), (new, rates.new_s), (reviews, rates.review_s)):
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
    finish_days_before: int = 1,
) -> TrackerNumbers | None:
    """The numbers for one exam deck, or None when the exam has passed (a passed exam shows
    nothing). ``pace_total``: cards done over the pace window; ``pace_days``: its length.

    *Days left* counts today up to the **finish date** (``study_window``): with "finish 2
    days before" and the exam on Fri Oct 23, Thu Oct 15 has 7 days (Oct 15-21). With the
    default 1 day before, that is the day before the exam, as in v0.4.0."""
    exam_in = days_left(exam, today)
    if exam_in < 0:
        return None
    pace = pace_total / pace_days
    cards_left = drill + new + reviews
    finish = finish_date(exam, finish_days_before)
    if exam_in == 0:
        return TrackerNumbers(
            exam, 0, "exam", drill, new, reviews, done_today, None, pace, None, finish, True
        )
    last, passed = study_window(exam, today, finish_days_before)
    left_days = (last - today).days + 1
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
        finish,
        passed,
    )


def daily_steps(
    handoffs: Iterable[tuple[int, date]],
    ratings: Iterable[tuple[int, date]],
    drilled: Collection[int] = frozenset(),
) -> Counter[date]:
    """Cards done per Anki day in one scope. ``handoffs``: (card id, day) of each card a
    Recall Drill handoff drilled. ``ratings``: (card id, day) of each counted Anki rating
    (``measure.is_counted``), all history. ``drilled``: every card a handoff drilled (any
    day). A card counts as done

    - when drilled: handed off that day (each card once a day);
    - on its first counted Anki rating (it was new), **unless it was drilled**: a drilled
      card was already counted when it was drilled, so its next-day first rating is not
      counted again;
    - as a review: a counted rating on a day after the card's first, each card once a day
      (the card was not new at the start of the day)."""
    out: Counter[date] = Counter()
    for _cid, day in set(handoffs):
        out[day] += 1
    days_by_card: dict[int, set[date]] = {}
    for cid, day in ratings:
        days_by_card.setdefault(cid, set()).add(day)
    for cid, days in days_by_card.items():
        first = min(days)
        if cid not in drilled:
            out[first] += 1
        for day in days:
            if day > first:
                out[day] += 1
    return out


def pace_total(steps: Mapping[date, int], today: date, window: int) -> int:
    """Cards done over the ``window`` Anki days before today."""
    return sum(steps.get(today - timedelta(days=k), 0) for k in range(1, window + 1))
