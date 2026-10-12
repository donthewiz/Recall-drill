"""waiting.py: the stale rule, the once-a-day notice, the release line (pure)."""

from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pytest

from recalldrill.pacing import PacingSettings
from recalldrill.storage import Storage
from recalldrill.waiting import (
    TAG_UNDRILLED,
    WaitingCard,
    is_stale,
    load_last_shown,
    notice_due,
    notice_text,
    pacing_stale,
    release_line,
    released_cids,
    save_last_shown,
    stale_total,
    waiting_rows,
)

MON = date(2026, 10, 12)


@pytest.mark.parametrize(
    ("enabled", "last", "today", "due"),
    [
        (True, None, MON, True),  # never shown
        (True, MON - timedelta(days=1), MON, True),  # yesterday
        (True, MON, MON, False),  # already today
        (True, MON + timedelta(days=1), MON, False),  # a clock moved back
        (False, None, MON, False),  # waiting_notice off
    ],
)
def test_notice_once_per_anki_day(enabled: bool, last: date | None, today: date, due: bool) -> None:
    assert notice_due(enabled, last, today) is due


def test_last_shown_round_trip(tmp_path: Path) -> None:
    st = Storage(tmp_path, "User 1")
    assert load_last_shown(st) is None
    save_last_shown(st, MON)
    assert load_last_shown(st) == MON
    assert (tmp_path / "profiles" / "User 1" / "waiting_notice.json").exists()


def test_notice_text() -> None:
    assert notice_text(409, date(2026, 9, 28)) == (
        "Recall Drill: 409 drill cards are still suspended and waiting "
        "(oldest added Mon Sep 28). Tools → Recall Drill: waiting cards."
    )
    assert "1 drill card is still" in notice_text(1, MON)


def test_stale_by_age_and_by_pacing() -> None:
    assert not is_stale(MON - timedelta(days=7), MON, 7, None)
    assert is_stale(MON - timedelta(days=8), MON, 7, None)
    assert not pacing_stale(None, MON) and not pacing_stale(PacingSettings(), MON)
    assert pacing_stale(PacingSettings(target_date=MON - timedelta(days=1)), MON)
    # The last drill day (target - 1) was yesterday: no drill days left.
    assert pacing_stale(PacingSettings(target_date=MON), MON)
    assert not pacing_stale(PacingSettings(target_date=MON + timedelta(days=10)), MON)
    fresh = MON - timedelta(days=1)
    assert is_stale(fresh, MON, 7, PacingSettings(target_date=MON))


def test_rows_by_deck() -> None:
    cards = [
        WaitingCard(1, 10, 100, MON - timedelta(days=20)),
        WaitingCard(2, 10, 100, MON - timedelta(days=1)),
        WaitingCard(3, 11, 200, MON - timedelta(days=2)),
    ]
    pacing = {200: PacingSettings(target_date=MON - timedelta(days=3))}
    rows = waiting_rows(cards, MON, 7, pacing.get, {100: "Lab 2", 200: "Lab 1"}.__getitem__)
    assert [(r.deck, r.waiting, r.stale, r.target) for r in rows] == [
        ("Lab 1", 1, 1, MON - timedelta(days=3)),
        ("Lab 2", 2, 1, None),
    ]
    assert rows[1].oldest == MON - timedelta(days=20)
    assert stale_total(rows) == (2, MON - timedelta(days=20))
    assert stale_total([]) == (0, None)


def test_release_line() -> None:
    line = release_line(7, [1, 2], [3], [10, 11], 0)
    assert line == {
        "type": "release",
        "timestamp": "1970-01-01T00:00:00.000Z",
        "deckId": 7,
        "groups": {"released": [1, 2], "released_siblings": [3]},
        "tags": {"added": 2, "byTag": {TAG_UNDRILLED: 2}},
    }
    assert released_cids([line, {"type": "handoff", "groups": {"released": [9]}}]) == {1, 2, 3}
