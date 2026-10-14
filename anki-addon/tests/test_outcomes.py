"""The light outcomes export (v0.3), pure: the 14-day cost window, the exam-day recall
formula and its empty cases, the CSV, and the atomic write."""

from __future__ import annotations

import csv
import io
import math
import os
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import pytest

from recalldrill.measure import Outcome, RevlogRow
from recalldrill.outcomes import (
    LAST_RESORT_DECAY,
    OUTCOME_COLUMNS,
    MemoryFacts,
    WindowCost,
    decay_factor,
    outcomes_csv,
    recall_on_exam,
    records,
    retrievability,
    window_cost,
)
from recalldrill.storage import OUTCOMES, Storage
from recalldrill.tuning import CardRow

ROLLOVER = 4


def ms(y: int, mo: int, d: int, h: int = 12, mi: int = 0) -> int:
    return int(datetime(y, mo, d, h, mi, tzinfo=UTC).timestamp() * 1000)


def rating(at: int, ease: int = 3, type_: int = 1, time: int = 5000, cid: int = 1) -> RevlogRow:
    return RevlogRow(at, cid, ease, type_, 0, time)


T0 = ms(2026, 10, 13, 20)  # Anki day Oct 13


def cost(rows: list[RevlogRow], now: int = ms(2026, 12, 1), t0: int = T0) -> WindowCost:
    return window_cost(rows, t0, ROLLOVER, now, UTC)


# -- the 14-day cost window ----------------------------------------------------------------


def test_window_edges_day_0_through_day_13() -> None:
    rows = [
        rating(ms(2026, 10, 13, 9), time=1000),  # day 0, before t0: in (the window is by Anki day)
        rating(ms(2026, 10, 14, 5), ease=1, time=2000),  # day 1 (after the 4 AM rollover)
        rating(ms(2026, 10, 26, 3, 59), time=4000),  # still Anki day Oct 25 = day 12
        rating(ms(2026, 10, 26, 12), ease=1, time=8000),  # Oct 26 = day 13: the last day in
        rating(ms(2026, 10, 27, 3, 59), time=16000),  # still Oct 26: in
        rating(ms(2026, 10, 27, 4, 0), ease=1, time=32000),  # Oct 27 = day 14: out
        rating(ms(2026, 11, 20), time=64000),  # long after: out
    ]
    c = cost(rows)
    assert c.ratings == 5 and c.again == 2
    assert c.anki_seconds == (1000 + 2000 + 4000 + 8000 + 16000) / 1000
    assert c.complete


def test_before_day_0_is_out() -> None:
    # 3 AM Oct 13 still belongs to Anki day Oct 12, the day before day 0.
    assert cost([rating(ms(2026, 10, 13, 3))]).ratings == 0
    assert cost([rating(ms(2026, 10, 13, 4))]).ratings == 1


def test_only_counted_ratings_are_summed() -> None:
    rows = [
        rating(ms(2026, 10, 14), type_=3, time=9000),  # filtered-deck / cram
        rating(ms(2026, 10, 14, 13), type_=4, ease=0, time=9000),  # manual
        rating(ms(2026, 10, 14, 14), type_=5, time=9000),  # rescheduled
        rating(ms(2026, 10, 14, 15), ease=0, time=9000),  # ease 0
        rating(ms(2026, 10, 14, 16), type_=0, time=3000),  # learn
        rating(ms(2026, 10, 15), type_=2, ease=1, time=1000),  # relearn
    ]
    c = cost(rows)
    assert (c.ratings, c.again, c.anki_seconds) == (2, 1, 4.0)
    assert (cost([]).ratings, cost([]).anki_seconds, cost([]).again) == (0, 0.0, 0)


def test_complete_once_day_13_has_passed() -> None:
    rows = [rating(ms(2026, 10, 14))]
    # Day 13 is Oct 26; it is over at 4 AM on Oct 27.
    assert not cost(rows, now=ms(2026, 10, 14)).complete
    assert not cost(rows, now=ms(2026, 10, 26, 12)).complete
    assert not cost(rows, now=ms(2026, 10, 27, 3, 59)).complete
    assert cost(rows, now=ms(2026, 10, 27, 4, 0)).complete


# -- predicted recall on exam day ------------------------------------------------------------


def test_the_formula_against_two_hand_computed_values() -> None:
    # (1) With decay 0.5 the factor is 0.9^-2 - 1 = 19/81. For S = 10 and t = 30:
    #     R = (1 + 19/81 * 3)^-0.5 = (46/27)^-0.5 = sqrt(27/46) = 0.766131...
    assert decay_factor(0.5) == pytest.approx(19 / 81, abs=1e-12)
    assert retrievability(10, 30, 0.5) == pytest.approx(math.sqrt(27 / 46), abs=1e-12)
    assert retrievability(10, 30, 0.5) == pytest.approx(0.766131, abs=1e-6)
    # (2) Whatever the decay, t == S gives exactly 0.9, and t == 0 gives 1.
    assert retrievability(5, 5, 0.1542) == pytest.approx(0.9, abs=1e-12)
    assert retrievability(12.5, 12.5, 0.8) == pytest.approx(0.9, abs=1e-12)
    assert retrievability(5, 0, 0.1542) == 1.0


def test_retrievability_refuses_nonsense() -> None:
    assert retrievability(0, 5, 0.5) is None
    assert retrievability(-1, 5, 0.5) is None
    assert retrievability(5, -1, 0.5) is None
    assert retrievability(5, 5, 0) is None


LAST = date(2026, 10, 14)
EXAM = date(2026, 10, 24)  # 10 days later


def test_recall_on_exam_and_its_empty_cases() -> None:
    mem = MemoryFacts(is_new=False, stability=10, decay=0.5)
    r = recall_on_exam(mem, LAST, date(2026, 11, 13))  # t = 30
    assert r == pytest.approx(math.sqrt(27 / 46))
    # The card's own decay wins over its preset's, which wins over the last resort.
    both = MemoryFacts(False, 10, decay=0.5, preset_decay=0.1)
    assert recall_on_exam(both, LAST, date(2026, 11, 13)) == pytest.approx(math.sqrt(27 / 46))
    preset = MemoryFacts(False, 10, decay=None, preset_decay=0.5)
    assert recall_on_exam(preset, LAST, date(2026, 11, 13)) == pytest.approx(math.sqrt(27 / 46))
    last_resort = MemoryFacts(False, 10)
    expected = retrievability(10, 10, LAST_RESORT_DECAY)
    assert LAST_RESORT_DECAY == 0.1542
    assert recall_on_exam(last_resort, LAST, EXAM) == pytest.approx(expected or 0)
    # Never a guess: no state, a new card, no exam date, no review, an exam in the past.
    assert recall_on_exam(None, LAST, EXAM) is None
    assert recall_on_exam(MemoryFacts(False, None, 0.5), LAST, EXAM) is None
    assert recall_on_exam(MemoryFacts(True, 10, 0.5), LAST, EXAM) is None
    assert recall_on_exam(mem, LAST, None) is None
    assert recall_on_exam(mem, None, EXAM) is None
    assert recall_on_exam(mem, LAST, LAST - timedelta(days=1)) is None
    assert recall_on_exam(mem, LAST, LAST) == 1.0  # exam the day of the last review


# -- the CSV and the atomic write -----------------------------------------------------------------


def card_row(group: str, cid: int, outcome: Outcome, **kw: object) -> CardRow:
    return CardRow(group=group, cid=cid, deck="Lab 2::Bones", top="Lab 2", outcome=outcome, **kw)  # type: ignore[arg-type]


def test_the_csv_columns_and_rows() -> None:
    assert OUTCOME_COLUMNS == (
        "group", "cid", "nid", "homeDeck", "sessionId", "t0", "status", "elapsed_days", "ease",
        "again", "ankiSeconds", "ankiAgain", "complete", "activeMs", "attempts", "misses",
        "reveals", "words", "chunks", "encodeReps", "examDate", "recallOnExam",
    )  # fmt: skip
    t0 = ms(2026, 10, 13, 20)
    revlog = [
        rating(ms(2026, 10, 14, 9), ease=1, time=4000, cid=1),
        rating(ms(2026, 10, 20, 9), ease=3, time=6000, cid=1),
        rating(ms(2026, 10, 14, 9), ease=3, time=2500, cid=2),  # the holdout card's intro
        rating(ms(2026, 10, 15, 9), ease=3, time=1500, cid=2),
    ]
    drilled = card_row(
        "drilled",
        1,
        Outcome("outcome", t0, ms(2026, 10, 14, 9), 1, 1),
        nid=11,
        session_id="s1",
        words=5,
        chunks=2,
        encode_reps=3,
        attempts=9,
        misses=2,
        reveals=1,
        active_ms=42_000,
    )
    held = card_row(
        "holdout", 2, Outcome("outcome", ms(2026, 10, 14, 9), ms(2026, 10, 15, 9), 1, 3)
    )
    not_yet = card_row("holdout", 3, Outcome("pending", None))
    other = card_row("baseline", 4, Outcome("pending", None))
    memory = {1: MemoryFacts(False, 10, 0.5), 2: MemoryFacts(True, None)}
    exams = {1: date(2026, 11, 19), 2: date(2026, 11, 19)}
    recs = records(
        [drilled, held, not_yet, other], revlog, memory, exams, ROLLOVER, ms(2026, 12, 1), UTC
    )
    assert [r.row.cid for r in recs] == [1, 2, 3]  # baseline rows are not exported
    text = outcomes_csv(recs, UTC)
    assert "\r" not in text and text.endswith("\n")
    parsed = list(csv.DictReader(io.StringIO(text)))
    assert len(parsed) == 3
    a, b, c = parsed
    assert a["group"] == "drilled" and a["cid"] == "1" and a["nid"] == "11"
    assert a["homeDeck"] == "Lab 2::Bones" and a["sessionId"] == "s1"
    assert a["t0"] == "2026-10-13T20:00:00+00:00"
    assert (a["status"], a["elapsed_days"], a["ease"], a["again"]) == ("outcome", "1", "1", "1")
    assert (a["ankiSeconds"], a["ankiAgain"], a["complete"]) == ("10.0", "1", "1")
    assert (a["activeMs"], a["attempts"], a["misses"], a["reveals"]) == ("42000", "9", "2", "1")
    assert (a["words"], a["chunks"], a["encodeReps"]) == ("5", "2", "3")
    assert a["examDate"] == "2026-11-19"
    # last counted review Oct 20, exam Nov 19: t = 30, S = 10, decay 0.5
    assert a["recallOnExam"] == "0.7661"
    # The holdout card: its t0 is its introduction; no drill columns; a new card has no recall.
    assert b["group"] == "holdout" and b["t0"] == "2026-10-14T09:00:00+00:00"
    assert (b["ankiSeconds"], b["ankiAgain"]) == ("4.0", "0")
    assert b["activeMs"] == b["attempts"] == b["words"] == b["recallOnExam"] == ""
    assert b["examDate"] == "2026-11-19"
    # A holdout card not introduced yet: no t0, no cost.
    assert c["t0"] == c["ankiSeconds"] == c["ankiAgain"] == c["complete"] == ""
    assert c["status"] == "pending"


def test_an_incomplete_window_is_marked() -> None:
    t0 = ms(2026, 10, 13, 20)
    row = card_row("drilled", 1, Outcome("pending", t0))
    (rec,) = records([row], [], {}, {}, ROLLOVER, ms(2026, 10, 20), UTC)
    assert rec.cost is not None and not rec.cost.complete and rec.cost.ratings == 0
    assert list(csv.DictReader(io.StringIO(outcomes_csv([rec], UTC))))[0]["complete"] == "0"


def test_write_text_is_atomic(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    path = st.write_text(OUTCOMES, "a,b\n1,2\n")
    assert path == tmp_path / "user_files" / "profiles" / "User 1" / "exports" / "outcomes.csv"
    assert path.read_bytes() == b"a,b\n1,2\n"  # LF, no BOM
    assert sorted(p.name for p in path.parent.iterdir()) == ["outcomes.csv"]  # no temp left

    # A failure while renaming keeps the old file and leaves no temp file.
    real_replace = os.replace

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(os, "replace", boom)
    with pytest.raises(OSError, match="disk full"):
        st.write_text(OUTCOMES, "new\n")
    monkeypatch.setattr(os, "replace", real_replace)
    assert path.read_text(encoding="utf-8") == "a,b\n1,2\n"
    assert sorted(p.name for p in path.parent.iterdir()) == ["outcomes.csv"]
    st.write_text(OUTCOMES, "new\n")
    assert path.read_text(encoding="utf-8") == "new\n"
    with pytest.raises(ValueError):
        st.write_text("exports/sub/x.csv", "")


def test_the_config_key() -> None:
    from recalldrill.addon_config import parse_config

    assert parse_config({}).export_on_open is True
    assert parse_config({"export_on_open": False}).export_on_open is False
    assert parse_config({"export_on_open": 0}).export_on_open is True  # mistyped: default
