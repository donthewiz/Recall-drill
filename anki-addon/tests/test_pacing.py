"""pacing.py: drill days, today's N and its edge cases, the ceiling warning, the
drill-speed medians and the revlog fallback's arithmetic (pure)."""

from __future__ import annotations

from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import pytest

from recalldrill.engine.jscompat import js_iso_string
from recalldrill.measure import RevlogRow
from recalldrill.pacing import (
    NO_ANKI_ESTIMATE,
    NO_DRILL_ESTIMATE,
    AnkiLoad,
    Pace,
    PacingSettings,
    PacingView,
    PlannedNew,
    ceiling_warning,
    completed_today,
    compute_pace,
    drill_days,
    drill_speed,
    holdout_share,
    load,
    minutes_text,
    planned_new,
    revlog_load,
    revlog_times,
    save,
    settings_from_json,
    short_date,
    timed_session,
)
from recalldrill.storage import PACING, Storage

# Fri Oct 2 2026; the target (an exam) is Fri Oct 16, so the last drill day is Thu Oct 15.
TODAY = date(2026, 10, 2)
EXAM = PacingSettings(date(2026, 10, 16))


def ms(y: int, mo: int, d: int, h: int = 12) -> int:
    return int(datetime(y, mo, d, h, tzinfo=UTC).timestamp() * 1000)


# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


def test_settings_json_round_trip_and_storage(tmp_path: Path) -> None:
    st = Storage(tmp_path, "p")
    assert load(st, 7) == PacingSettings()  # nothing saved: no target, Mon-Fri, 1 day early
    s = PacingSettings(date(2026, 11, 3), frozenset({0, 2, 4}), 2)
    save(st, 7, s)
    save(st, 8, PacingSettings())
    assert load(st, 7) == s and load(st, 8) == PacingSettings()
    assert st.read_json(PACING, {})["7"] == {
        "target_date": "2026-11-03",
        "drill_weekdays": [0, 2, 4],
        "finish_days_before": 2,
    }


@pytest.mark.parametrize(
    "raw",
    [None, [], {"target_date": "soon"}, {"drill_weekdays": "weekdays"}, {"finish_days_before": -1}],
)
def test_bad_settings_take_defaults(raw: Any) -> None:
    s = settings_from_json(raw)
    assert s.target_date is None or isinstance(s.target_date, date)
    assert s.drill_weekdays == frozenset(range(5)) and s.finish_days_before == 1


def test_bad_weekdays_are_dropped() -> None:
    assert settings_from_json({"drill_weekdays": [0, 7, True, "1", 6]}).drill_weekdays == {0, 6}


# ---------------------------------------------------------------------------
# Drill days and today's N
# ---------------------------------------------------------------------------


def test_drill_days_are_weekdays_through_the_day_before_the_target() -> None:
    days = drill_days(TODAY, EXAM, done_today=False)
    assert [d.day for d in days] == [2, 5, 6, 7, 8, 9, 12, 13, 14, 15]
    assert date(2026, 10, 16) not in days  # finish one day early


def test_today_counts_unless_a_session_completed_today() -> None:
    assert drill_days(TODAY, EXAM, done_today=True)[0] == date(2026, 10, 5)


def test_finish_days_before_and_custom_weekdays() -> None:
    s = PacingSettings(date(2026, 10, 16), frozenset({1, 3}), 3)  # Tue/Thu, done by Tue 13
    assert [d.day for d in drill_days(TODAY, s, False)] == [6, 8, 13]


def test_todays_n_is_ceil_remaining_over_days_left() -> None:
    p = compute_pace(TODAY, EXAM, 57, done_today=False)
    assert (p.status, p.days_left, p.per_day, p.today_n) == ("ok", 10, 6, 6)
    assert p.drills_today
    assert p.headline() == "Today: 6 cards. 57 left over 10 drill days."
    assert compute_pace(TODAY, EXAM, 60, False).per_day == 6
    assert compute_pace(TODAY, EXAM, 61, False).per_day == 7


def test_no_target() -> None:
    p = compute_pace(TODAY, PacingSettings(), 40, False)
    assert p.status == "no_target" and p.today_n == 0 and p.per_day == 0


def test_edge_target_passed() -> None:
    p = compute_pace(date(2026, 10, 17), EXAM, 12, False)
    assert p.status == "target_passed" and p.today_n == 0
    assert (
        p.headline() == "The target date (Fri Oct 16) has passed: 12 cards left. Pick a new date."
    )


def test_edge_today_not_a_drill_day() -> None:
    saturday = date(2026, 10, 3)
    p = compute_pace(saturday, EXAM, 45, False)
    assert p.status == "ok" and not p.drills_today and p.today_n == 0
    assert p.days_left == 9 and p.per_day == 5
    assert (
        p.headline()
        == "Today: not a drill day; next: Mon Oct 5, 5 cards. 45 left over 9 drill days."
    )


def test_edge_done_today() -> None:
    p = compute_pace(TODAY, EXAM, 45, True)
    assert p.today_n == 0 and p.per_day == 5
    assert p.headline().startswith("Today: done (a session finished today); next: Mon Oct 5")


def test_edge_zero_remaining() -> None:
    p = compute_pace(TODAY, EXAM, 0, False)
    assert p.status == "done" and p.today_n == 0 and p.per_day == 0
    assert p.headline() == "Nothing left to drill before Fri Oct 16."


def test_edge_no_drill_days_left_with_cards_remaining() -> None:
    """The day before the exam is past the last drill day (finish 1 day early)."""
    p = compute_pace(date(2026, 10, 16), EXAM, 8, False)
    assert p.status == "behind" and p.days_left == 0 and p.today_n == 0
    assert p.headline() == "Behind: 8 cards, no drill days left before Fri Oct 16."
    # Same when the only drill day left is today and it's already done.
    p = compute_pace(date(2026, 10, 15), EXAM, 8, True)
    assert p.status == "behind" and "Behind: 8 cards, no drill days left" in p.headline()


def test_no_weekday_ticked_is_behind() -> None:
    p = compute_pace(TODAY, PacingSettings(date(2026, 10, 16), frozenset()), 5, False)
    assert p.status == "behind"


def test_completed_today_reads_the_session_lines_on_the_anki_day() -> None:
    def line(at: int, type_: str = "session") -> dict[str, Any]:
        return {"type": type_, "finishedAt": js_iso_string(at)}

    # Rollover 4: 2 AM on Oct 3 is still Anki day Oct 2.
    assert completed_today([line(ms(2026, 10, 3, 2))], TODAY, 4, UTC)
    assert not completed_today([line(ms(2026, 10, 3, 5))], TODAY, 4, UTC)
    assert not completed_today([line(ms(2026, 10, 2, 3))], TODAY, 4, UTC)  # Oct 1's day
    assert not completed_today([line(ms(2026, 10, 2, 12), "handoff")], TODAY, 4, UTC)
    assert not completed_today([{"type": "session"}], TODAY, 4, UTC)


# ---------------------------------------------------------------------------
# Tomorrow's new cards and the ceiling
# ---------------------------------------------------------------------------


def test_holdout_share() -> None:
    assert holdout_share(10, 0) == 0
    assert holdout_share(10, 15) == 2  # 10 * 15 / 85 = 1.76
    assert holdout_share(10, 50) == 10
    assert holdout_share(0, 20) == 0


def test_planned_new() -> None:
    assert planned_new(10, 1.0, 15, "B") == PlannedNew(10, 10, 2)
    assert planned_new(10, 1.0, 15, "A") == PlannedNew(10, 10, 0)  # holdout share: B only
    assert planned_new(10, 0.5, 0, "B", siblings_on=False) == PlannedNew(10, 0, 0)
    assert planned_new(10, 1.0, 15, "B").total == 22


def test_ceiling_b_warns_with_the_number_held_back() -> None:
    w = ceiling_warning("B", PlannedNew(12, 12, 2), 20, 0, 200)
    assert w == (
        "Tomorrow: 26 new cards (12 drilled + 12 siblings + 2 holdout), over the deck's "
        "new/day limit of 20: Anki holds back 6."
    )
    assert ceiling_warning("B", PlannedNew(10, 10, 0), 20, 0, 200) is None
    assert ceiling_warning("B", PlannedNew(0, 0, 0), 0, 0, 0) is None


def test_ceiling_a_uses_the_room_in_the_review_limit() -> None:
    w = ceiling_warning("A", PlannedNew(15, 15, 0), 0, 190, 200)
    assert w == (
        "Tomorrow: 15 drilled cards become reviews, with room for 10 under the review "
        "limit of 200 (190 already due): Anki holds back 5."
    )
    assert ceiling_warning("A", PlannedNew(10, 99, 0), 0, 190, 200) is None  # siblings: new
    assert "room for 0" in str(ceiling_warning("A", PlannedNew(3, 0, 0), 0, 250, 200))


# ---------------------------------------------------------------------------
# Drill speed
# ---------------------------------------------------------------------------


def session(
    finished: int, cards: list[tuple[int, int]], active: int | None = None
) -> dict[str, Any]:
    """``cards``: (chunks, active ms) per card."""
    line: dict[str, Any] = {
        "type": "session",
        "finishedAt": js_iso_string(finished),
        "cards": [{"chunks": c} for c, _ in cards],
        "anki": [{"cid": i, "did": 1, "activeMs": a} for i, (_, a) in enumerate(cards)],
    }
    total = sum(a for _, a in cards) if active is None else active
    if total:
        line["activeMs"] = total
    return line


def test_timed_session_needs_active_time() -> None:
    assert timed_session(session(ms(2026, 10, 1), [(0, 30_000)])) is not None
    old = session(ms(2026, 10, 1), [(0, 30_000)])
    del old["activeMs"]  # a line from before Phase 6
    assert timed_session(old) is None
    assert timed_session({"type": "handoff", "activeMs": 5}) is None


def test_drill_speed_medians_by_shape_in_the_deck() -> None:
    deck = [session(ms(2026, 9, d), [(0, 20_000), (0, 40_000), (3, 120_000)]) for d in (1, 2, 3)]
    s = drill_speed(deck, deck)
    assert s is not None and s.scope == "deck" and s.sessions == 3
    assert (s.full_s, s.chunked_s) == (30.0, 120.0)
    assert s.seconds(2, 5) == 2 * 120 + 5 * 30
    assert s.source() == "your pace, last 3 timed sessions"


def test_drill_speed_uses_the_last_ten() -> None:
    old = [session(ms(2026, 8, d), [(0, 500_000)]) for d in range(1, 11)]
    new = [session(ms(2026, 9, d), [(0, 10_000)]) for d in range(1, 11)]
    s = drill_speed(new + old, [])
    assert s is not None and s.sessions == 10 and s.full_s == 10.0


def test_drill_speed_falls_back_to_all_decks_then_none() -> None:
    deck = [session(ms(2026, 9, 1), [(0, 20_000)])]
    other = [session(ms(2026, 9, d), [(0, 60_000)]) for d in (2, 3, 4)]
    s = drill_speed(deck, deck + other)
    assert s is not None and s.scope == "all" and s.sessions == 4
    assert "all decks" in s.source()
    assert drill_speed(deck, deck) is None


def test_missing_shape_takes_the_overall_median() -> None:
    deck = [session(ms(2026, 9, d), [(0, 20_000), (0, 40_000)]) for d in (1, 2, 3)]
    s = drill_speed(deck, deck)
    assert s is not None and s.chunked_s is None
    assert s.per_card(True) == s.overall_s == 30.0


# ---------------------------------------------------------------------------
# The revlog fallback
# ---------------------------------------------------------------------------


def rows(type_: int, times: list[int], cid0: int = 0, at: int = 10_000) -> list[RevlogRow]:
    return [RevlogRow(at + i, cid0 + i, 3, type_, time=t) for i, t in enumerate(times)]


def test_revlog_times_and_load_arithmetic() -> None:
    review = rows(1, [4000, 6000, 8000]) + rows(2, [10_000], cid0=50)
    # Two new cards, three learning ratings each (their steps), median 7 s.
    learn = rows(0, [6000, 7000, 8000], cid0=100) + rows(0, [6000, 7000, 8000], cid0=100)
    old = [RevlogRow(1, 999, 3, 1, time=99_000)]  # before the window
    ignored = [RevlogRow(20_000, 998, 0, 1, time=5000), RevlogRow(20_001, 997, 3, 4, time=5000)]
    t = revlog_times(review + learn + old + ignored, since_ms=5_000)
    assert (t.review_ms, t.learn_ms, t.ratings) == (7000, 7000, 10)
    assert t.learn_ratings_per_card == 2.0  # cids 100..102 twice: 6 ratings over 3 cards
    assert not t.enough
    secs = revlog_load(t, [10, 0, 3], [5, 0, 0])
    assert secs == [10 * 7 + 5 * 2.0 * 7, 0.0, 3 * 7]


def test_revlog_load_with_one_kind_missing() -> None:
    t = revlog_times(rows(1, [2000] * 60), 0)
    assert t.enough and t.learn_ms is None
    assert revlog_load(t, [1], [1]) == [2.0 + 1 * 1.0 * 2.0]


def test_anki_load_peak() -> None:
    load_ = AnkiLoad.from_days("simulator", [60, 300, 600, 600, 120], date(2026, 10, 3), "x")
    assert (load_.tomorrow_s, load_.peak_s, load_.peak_date) == (60, 600, date(2026, 10, 5))
    assert AnkiLoad.from_days("simulator", [], TODAY, "x").source == "none"


# ---------------------------------------------------------------------------
# The panel's line
# ---------------------------------------------------------------------------


def test_line_with_every_figure() -> None:
    pace = compute_pace(TODAY, EXAM, 57, False)
    view = PacingView(
        pace,
        drill_s=540,
        drill_source="your pace, last 8 timed sessions",
        anki=AnkiLoad.from_days(
            "simulator", [360, 840, 300], date(2026, 10, 3), "FSRS simulator, x"
        ),
    )
    assert view.line() == (
        "Today: 6 cards, about 9 min drilling (your pace) + about 6 min in Anki tomorrow "
        "(FSRS simulator). Peak: about 14 min on Sun Oct 4. 57 left over 10 drill days."
    )
    assert view.sources() == (
        "Drill time: your pace, last 8 timed sessions. Anki time: FSRS simulator, x."
    )


def test_line_without_estimates() -> None:
    view = PacingView(compute_pace(TODAY, EXAM, 57, False))
    assert view.line() == (
        "Today: 6 cards, drill time: no estimate yet. 57 left over 10 drill days."
    )
    assert NO_DRILL_ESTIMATE in view.sources() and NO_ANKI_ESTIMATE in view.sources()


def test_line_on_an_off_day_and_edge_cases() -> None:
    off = PacingView(compute_pace(date(2026, 10, 3), EXAM, 45, False), drill_s=100)
    assert off.line().startswith("Today: not a drill day; next Mon Oct 5: 5 cards, about 2 min")
    behind = PacingView(Pace("behind", 8, (), date(2026, 10, 16), date(2026, 10, 16)))
    assert behind.line() == "Behind: 8 cards, no drill days left before Fri Oct 16."


def test_minutes_and_dates() -> None:
    assert minutes_text(20) == "under 1 min" and minutes_text(89) == "about 1 min"
    assert minutes_text(90) == "about 2 min"
    assert short_date(date(2026, 10, 5)) == "Mon Oct 5"
