"""The exam tracker's pure rules (v0.4 step 2): docs/DECISIONS.md, "Step 2: real numbers"."""

from __future__ import annotations

import dataclasses
from datetime import date, timedelta

import pytest

from recalldrill import exam_tracker as et
from recalldrill.tracker_cache import NumbersCache, Refresher

TODAY = date(2026, 10, 15)
EXAM = date(2026, 10, 23)
NO_RATES = et.Rates()
ALL_RATES = et.Rates(drill_s=30, new_s=20, review_s=10)


def numbers(**kw: object) -> et.TrackerNumbers:
    args: dict[str, object] = {
        "exam": EXAM,
        "today": TODAY,
        "drill": 0,
        "new": 0,
        "reviews": 0,
        "done_today": 0,
        "pace_total": 0,
        "pace_days": 7,
        "rates": NO_RATES,
    }
    args.update(kw)
    n = et.compute(**args)  # type: ignore[arg-type]
    assert n is not None
    return n


# --- days -------------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("exam", "left", "horizon"),
    [
        (date(2026, 10, 23), 8, 7),  # Fri Oct 23 seen on Thu Oct 15: 8 days, counting today
        (date(2026, 10, 16), 1, 0),
        (date(2026, 10, 15), 0, -1),  # the exam day itself
        (date(2026, 10, 14), -1, -2),
    ],
)
def test_days_left_counts_today_up_to_the_day_before_the_exam(
    exam: date, left: int, horizon: int
) -> None:
    assert et.days_left(exam, TODAY) == left
    assert et.reviews_horizon(exam, TODAY) == horizon


@pytest.mark.parametrize(
    ("today", "before", "last", "passed", "days"),
    [
        (date(2026, 10, 15), 1, date(2026, 10, 22), False, 8),  # default: the day before
        (date(2026, 10, 15), 2, date(2026, 10, 21), False, 7),  # Lab 2: Oct 15-21
        (date(2026, 10, 15), 0, date(2026, 10, 22), False, 8),  # 0 is treated as 1
        (date(2026, 10, 21), 2, date(2026, 10, 21), False, 1),  # the finish date itself
        (date(2026, 10, 22), 2, date(2026, 10, 22), True, 1),  # passed: to the day before
    ],
)
def test_the_window_ends_on_the_finish_date(
    today: date, before: int, last: date, passed: bool, days: int
) -> None:
    exam = date(2026, 10, 23)
    assert et.study_window(exam, today, before) == (last, passed)
    assert et.reviews_horizon(exam, today, before) == (last - today).days
    n = et.compute(
        exam=exam,
        today=today,
        drill=10,
        new=0,
        reviews=0,
        done_today=0,
        pace_total=70,
        pace_days=7,
        rates=ALL_RATES,
        finish_days_before=before,
    )
    assert n is not None
    assert (n.days_left, n.finish_passed) == (days, passed)
    assert n.finish_date == exam - timedelta(days=max(1, before))
    assert n.needed == -(-10 // days)


def test_the_exam_day_is_unchanged_by_the_finish_setting() -> None:
    n = et.compute(
        exam=EXAM,
        today=EXAM,
        drill=1,
        new=0,
        reviews=0,
        done_today=0,
        pace_total=0,
        pace_days=7,
        rates=ALL_RATES,
        finish_days_before=3,
    )
    assert n is not None and n.status == "exam" and n.days_left == 0 and n.needed is None


def test_a_passed_exam_has_no_numbers() -> None:
    assert (
        et.compute(
            exam=TODAY - timedelta(days=1),
            today=TODAY,
            drill=5,
            new=5,
            reviews=5,
            done_today=0,
            pace_total=7,
            pace_days=7,
            rates=ALL_RATES,
        )
        is None
    )


# --- needed a day -----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("left", "done", "days", "needed"),
    [(97, 6, 8, 13), (80, 0, 8, 10), (81, 0, 8, 11), (1, 0, 8, 1), (0, 0, 8, 0), (40, 10, 1, 50)],
)
def test_needed_a_day_is_fixed_at_the_start_of_the_day(
    left: int, done: int, days: int, needed: int
) -> None:
    assert et.needed_a_day(left, done, days) == needed


def test_work_done_today_does_not_move_the_target() -> None:
    # 100 cards, 8 days: 13 a day. Doing 5 today leaves 95 and raises "done" to 5: still 13.
    assert et.needed_a_day(100, 0, 8) == et.needed_a_day(95, 5, 8) == 13


def test_a_missed_day_raises_tomorrows_number_and_there_is_no_overdue() -> None:
    today = et.compute(**kw(drill=0, new=80, reviews=0))  # type: ignore[arg-type]
    tomorrow = et.compute(**kw(drill=0, new=80, reviews=0, today=TODAY + timedelta(days=1)))  # type: ignore[arg-type]
    assert today is not None and tomorrow is not None
    assert today.cards_left == tomorrow.cards_left == 80  # nothing was done
    assert (today.days_left, tomorrow.days_left) == (8, 7)
    assert (today.needed, tomorrow.needed) == (10, 12)
    assert not any("overdue" in f.name for f in dataclasses.fields(et.TrackerNumbers))


def kw(**over: object) -> dict[str, object]:
    base: dict[str, object] = {
        "exam": EXAM,
        "today": TODAY,
        "drill": 0,
        "new": 0,
        "reviews": 0,
        "done_today": 0,
        "pace_total": 0,
        "pace_days": 7,
        "rates": NO_RATES,
    }
    base.update(over)
    return base


# --- status -----------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("needed", "pace_total", "days", "left", "done", "status"),
    [
        (61, 350, 7, 100, 0, "amber"),  # Needed 61, Pace 50: 61 <= 62.5
        (63, 350, 7, 100, 0, "red"),  # Needed 63, Pace 50
        (50, 350, 7, 100, 0, "green"),  # Needed 50, Pace 50
        (49, 350, 7, 100, 0, "green"),
        (62, 350, 7, 100, 0, "amber"),
        (63, 350, 7, 100, 0, "red"),
        (1, 0, 7, 10, 0, "red"),  # Pace 0 with cards left
        (13, 9, 7, 97, 6, "red"),  # the hand-counted scene
        (13, 0, 7, 0, 0, "green"),  # nothing left
        (13, 0, 7, 50, 13, "green"),  # Done today = Needed
        (13, 0, 7, 50, 20, "green"),  # Done today > Needed
        (13, 0, 7, 50, 12, "red"),  # one short of it
    ],
)
def test_status_rule(
    needed: int, pace_total: int, days: int, left: int, done: int, status: str
) -> None:
    assert et.status_for(left, done, needed, pace_total, days) == status


def test_the_boundary_at_exactly_1_25_times_pace() -> None:
    # Pace 4/day (28 over 7): 1.25 x 4 = 5 is amber, 6 is red; pace 8: 10 amber, 11 red.
    assert et.status_for(50, 0, 5, 28, 7) == "amber" and et.status_for(50, 0, 6, 28, 7) == "red"
    assert et.status_for(50, 0, 10, 56, 7) == "amber" and et.status_for(50, 0, 11, 56, 7) == "red"
    # A pace that is not a whole number: 9/7 a day -> 1.25 x = 1.607: 1 is green, 2 is red.
    assert et.status_for(50, 0, 1, 9, 7) == "green" and et.status_for(50, 0, 2, 9, 7) == "red"


def test_compute_sets_the_status_from_the_rule() -> None:
    n = numbers(new=97, done_today=6, pace_total=9, pace_days=7)
    assert (n.cards_left, n.needed, n.status) == (97, 13, "red")
    assert numbers(new=0).status == "green"
    # Pace 350 / 7 = 50 a day over 8 days left: the three examples through compute().
    for new, needed, status in ((400, 50, "green"), (488, 61, "amber"), (504, 63, "red")):
        n = numbers(new=new, pace_total=350)
        assert (n.needed, n.pace, n.status) == (needed, 50.0, status)


# --- exam day ---------------------------------------------------------------------------


def test_the_exam_day_has_no_needed_figure() -> None:
    n = numbers(exam=TODAY, drill=3, new=4, reviews=5, done_today=2, rates=ALL_RATES)
    assert n.exam_today and n.status == "exam" and n.days_left == 0
    assert n.needed is None and n.est_seconds is None
    assert (n.cards_left, n.done_today) == (12, 2)
    assert et.STATUS_WORD["exam"] == "Exam today"


# --- the estimate -----------------------------------------------------------------------


def test_estimate_splits_the_remaining_cards_in_the_split_proportions() -> None:
    # 7 cards left today of 100: 40 drill, 50 new, 10 reviews. A drill card costs the drill
    # plus its first day in Anki tomorrow (30 + 20 s): the count leaves that rating out, the
    # minutes don't.
    s = et.estimate_seconds(13, 6, 40, 50, 10, ALL_RATES)
    assert s == pytest.approx(7 * (40 * (30 + 20) + 50 * 20 + 10 * 10) / 100)
    # Done today beyond Needed: nothing left today.
    assert et.estimate_seconds(13, 20, 40, 50, 10, ALL_RATES) == 0.0
    assert et.estimate_seconds(0, 0, 0, 0, 0, ALL_RATES) == 0.0


@pytest.mark.parametrize(
    "rates",
    [
        et.Rates(None, 20, 10),
        et.Rates(30, None, 10),
        et.Rates(30, 20, None),
        et.Rates(),
    ],
)
def test_a_missing_rate_gives_no_estimate_never_a_made_up_one(rates: et.Rates) -> None:
    assert et.estimate_seconds(13, 6, 40, 50, 10, rates) is None
    assert et.est_text(None) == "Est. time: not enough history yet"


def test_drill_cards_need_the_new_card_rate_too() -> None:
    # Only drill cards left: their first Anki rating is part of their cost, so a missing new
    # rate means no estimate, never a drill-only figure.
    assert et.estimate_seconds(10, 0, 10, 0, 0, et.Rates(30, None, 10)) is None
    assert et.estimate_seconds(10, 0, 10, 0, 0, et.Rates(30, 20, None)) == pytest.approx(10 * 50)


def test_a_rate_nothing_needs_may_be_missing() -> None:
    # No drill cards: the drill rate isn't needed.
    assert et.estimate_seconds(10, 0, 0, 50, 50, et.Rates(None, 20, 10)) == pytest.approx(
        10 * (50 * 20 + 50 * 10) / 100
    )


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (55 * 60, "Est. 55 min today"),
        (55 * 60 + 29, "Est. 55 min today"),  # rounds half up with minutes_text
        (55 * 60 + 30, "Est. 56 min today"),
        (132, "Est. 2 min today"),
        (40, "Est. under 1 min today"),
        (0, "Est. under 1 min today"),
    ],
)
def test_estimate_text_uses_minutes_text(seconds: float, text: str) -> None:
    assert et.est_text(seconds) == text


def test_exam_text() -> None:
    assert et.exam_text(EXAM) == "Exam · Fri Oct 23"


# --- cards done and pace ----------------------------------------------------------------


def d(k: int) -> date:
    return TODAY - timedelta(days=k)


def test_daily_steps_count_a_drill_a_first_rating_and_a_review() -> None:
    handoffs = [(1, d(0)), (1, d(0)), (2, d(1)), (1, d(1))]  # card 1 drilled twice today
    ratings = [
        (5, d(0)),  # first rating today: a new-card step
        (5, d(0)),  # ...a second rating the same day: no extra step
        (6, d(1)),  # first rating yesterday
        (6, d(0)),  # review today
        (6, d(0)),  # ...twice today: counts once
        (7, d(3)),
        (7, d(3)),
    ]
    steps = et.daily_steps(handoffs, ratings)
    assert steps[d(0)] == 1 + 1 + 1  # drill of card 1, first rating of 5, review of 6
    assert steps[d(1)] == 2 + 1  # drills of 1 and 2, first rating of 6
    assert steps[d(3)] == 1
    assert sum(steps.values()) == 3 + 3 + 1


def test_a_drilled_cards_first_anki_rating_is_not_counted_again() -> None:
    """Cards, not steps: a card counts once when drilled; its next-day first rating in Anki
    adds nothing, while its later reviews still count."""
    handoffs = [(1, d(2))]  # card 1 drilled two days ago
    ratings = [
        (1, d(1)),  # its first Anki rating yesterday: already counted at the drill
        (1, d(0)),  # a review today: counts
        (2, d(1)),  # card 2 was never drilled: its first rating counts
    ]
    done = et.daily_steps(handoffs, ratings, drilled={1})
    assert done[d(2)] == 1  # the drill
    assert done[d(1)] == 1  # only card 2's first rating
    assert done[d(0)] == 1  # card 1's review
    # Without the drilled set it would be the old step count (2 yesterday).
    assert et.daily_steps(handoffs, ratings)[d(1)] == 2


def test_pace_averages_the_seven_days_before_today_not_today() -> None:
    steps = {d(0): 99, **{d(k): k for k in range(1, 8)}, d(8): 1000}
    assert et.pace_total(steps, TODAY, 7) == 28
    assert et.pace_total(steps, TODAY, 3) == 1 + 2 + 3
    assert numbers(pace_total=28, pace_days=7).pace == 4.0


@pytest.mark.parametrize(
    ("added", "window"),
    [
        (None, 7),
        (d(30), 7),
        (d(7), 7),
        (d(6), 6),
        (d(3), 3),
        (d(1), 1),
        (d(0), 1),  # added today: at least 1
    ],
)
def test_a_young_scope_averages_over_the_days_since_it_began(
    added: date | None, window: int
) -> None:
    assert et.pace_window(added, TODAY) == window


# --- the cache and the refresh rule -----------------------------------------------------


def test_cache_is_keyed_by_deck_id_and_anki_day() -> None:
    cache = NumbersCache()
    n = numbers(new=5)
    assert cache.needs_refresh(TODAY) and cache.get(1, TODAY) is None
    cache.store(TODAY, {1: n})
    assert cache.get(1, TODAY) is n and cache.for_day(TODAY) == {1: n}
    assert not cache.needs_refresh(TODAY)
    tomorrow = TODAY + timedelta(days=1)
    assert cache.get(1, tomorrow) is None and cache.for_day(tomorrow) == {}  # a new day
    assert cache.needs_refresh(tomorrow)
    cache.invalidate()
    assert cache.needs_refresh(TODAY)
    cache.started()
    assert not cache.needs_refresh(TODAY)
    cache.store(TODAY, {})  # a result with no exam deck still counts as computed
    assert cache.has_day(TODAY) and cache.for_day(TODAY) == {}


class Runner:
    def __init__(self) -> None:
        self.finishers: list[object] = []
        self.results: list[int] = []

    def run(self, finish: object) -> None:
        self.finishers.append(finish)

    def finish(self, value: int | None = 1) -> None:
        self.finishers.pop(0)(value)  # type: ignore[operator]


def test_never_more_than_one_run_and_requests_during_a_run_make_exactly_one_more() -> None:
    r = Runner()
    refresher = Refresher[int](r.run, r.results.append)
    refresher.request()
    refresher.request()
    refresher.request()
    assert refresher.runs == 1 and len(r.finishers) == 1 and refresher.running
    r.finish(10)
    assert r.results == [10] and refresher.runs == 2 and len(r.finishers) == 1  # one more
    r.finish(20)
    assert r.results == [10, 20] and refresher.runs == 2 and not refresher.running
    refresher.request()  # idle again: starts a new one
    assert refresher.runs == 3


def test_a_failed_run_does_not_redraw_and_still_runs_the_pending_request() -> None:
    r = Runner()
    refresher = Refresher[int](r.run, r.results.append)
    refresher.request()
    refresher.request()
    r.finish(None)  # the reader failed
    assert r.results == [] and refresher.runs == 2
    r.finish(5)
    assert r.results == [5]
