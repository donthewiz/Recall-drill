"""measure.py: the Anki day, counted ratings, outcomes, the Wilson interval."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta, timezone

import pytest

from recalldrill.measure import (
    Outcome,
    RevlogRow,
    anki_day,
    drilled_outcome,
    introduced_outcome,
    introduction_ms,
    is_counted,
    iso_ms,
    overlaps,
    wilson,
)

ROLLOVER = 4


def ms(y: int, mo: int, d: int, h: int = 12, mi: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp() * 1000)


def row(t: int, ease: int = 3, type_: int = 1, cid: int = 1) -> RevlogRow:
    return RevlogRow(id=t, cid=cid, ease=ease, type=type_)


def test_anki_day_subtracts_the_rollover() -> None:
    assert anki_day(ms(2026, 10, 2, 3, 59), ROLLOVER, UTC) == date(2026, 10, 1)
    assert anki_day(ms(2026, 10, 2, 4, 0), ROLLOVER, UTC) == date(2026, 10, 2)
    assert anki_day(ms(2026, 10, 2, 23, 0), ROLLOVER, UTC) == date(2026, 10, 2)
    assert anki_day(ms(2026, 10, 2, 3, 0), 0, UTC) == date(2026, 10, 2)
    # Local time: the same instant is another Anki day five hours west.
    est = timezone(timedelta(hours=-5))
    assert anki_day(ms(2026, 10, 2, 8, 0), ROLLOVER, est) == date(2026, 10, 1)


@pytest.mark.parametrize(
    ("ease", "type_", "counted"),
    [
        (1, 0, True),
        (3, 1, True),
        (4, 2, True),
        (3, 3, False),  # filtered / cram
        (0, 4, False),  # manual (set due date)
        (3, 5, False),  # rescheduled
        (0, 1, False),  # ease 0
    ],
)
def test_counted_ratings(ease: int, type_: int, counted: bool) -> None:
    assert is_counted(row(0, ease, type_)) is counted


def test_drilled_outcome_is_the_first_rating_on_a_later_day() -> None:
    t0 = ms(2026, 10, 1, 20)
    rows = [
        row(ms(2026, 10, 1, 21), 1, 0),  # same Anki day: ignored
        row(ms(2026, 10, 2, 2), 1, 0),  # 2 a.m.: still Oct 1's Anki day
        row(ms(2026, 10, 2, 9), 0, 4),  # manual: not counted
        row(ms(2026, 10, 2, 10), 3, 0),
        row(ms(2026, 10, 2, 10, 5), 1, 0),
    ]
    o = drilled_outcome(rows, t0, ROLLOVER, UTC)
    assert o == Outcome("outcome", t0, ms(2026, 10, 2, 10), 1, 3)
    assert o.again is False
    again = drilled_outcome([row(ms(2026, 10, 3, 9), 1, 0)], t0, ROLLOVER, UTC)
    assert (again.status, again.elapsed, again.again) == ("outcome", 2, True)


def test_late_and_pending() -> None:
    t0 = ms(2026, 10, 1)
    late = drilled_outcome([row(ms(2026, 10, 5), 1)], t0, ROLLOVER, UTC)
    assert (late.status, late.elapsed) == ("late", 4)
    pending = drilled_outcome([row(ms(2026, 10, 1, 18), 1)], t0, ROLLOVER, UTC)
    assert pending == Outcome("pending", t0) and pending.again is None


def test_introduced_outcome_starts_at_the_first_counted_rating() -> None:
    rows = [
        row(ms(2026, 9, 1), 0, 4),  # a manual row isn't an introduction
        row(ms(2026, 9, 2, 10), 1, 0),
        row(ms(2026, 9, 2, 10, 10), 3, 0),
        row(ms(2026, 9, 4, 9), 1, 1),
    ]
    assert introduction_ms(rows) == ms(2026, 9, 2, 10)
    o = introduced_outcome(rows, ROLLOVER, UTC)
    assert (o.status, o.t0_ms, o.elapsed, o.again) == ("outcome", ms(2026, 9, 2, 10), 2, True)
    assert introduced_outcome([], ROLLOVER, UTC) == Outcome("pending", None)
    only_day_one = introduced_outcome(rows[:3], ROLLOVER, UTC)
    assert only_day_one.status == "pending" and only_day_one.t0_ms == ms(2026, 9, 2, 10)


def test_wilson() -> None:
    lo, hi = wilson(10, 100)
    assert lo == pytest.approx(0.0552, abs=1e-3) and hi == pytest.approx(0.1744, abs=1e-3)
    assert wilson(0, 30)[0] == 0.0 and wilson(0, 30)[1] == pytest.approx(0.1135, abs=1e-3)
    assert wilson(30, 30)[1] == pytest.approx(1.0)
    assert wilson(0, 0) == (0.0, 1.0)
    assert overlaps((0.1, 0.3), (0.3, 0.5)) and not overlaps((0.1, 0.2), (0.25, 0.5))


def test_iso_ms() -> None:
    assert iso_ms("2026-10-02T12:00:00.000Z") == ms(2026, 10, 2)
    assert iso_ms("2026-10-02T12:00:00") is None  # no zone: refused
    assert iso_ms("nope") is None
