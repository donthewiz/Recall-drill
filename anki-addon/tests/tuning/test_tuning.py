"""tuning.py: build_report (outcomes per group, header, breakdowns), the
suggestion rules, CSV, the tuning line and the Apply confirmation text."""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from datetime import UTC, date
from typing import Any

from tuning_support import ROLLOVER, Drilled, handoff_line, ms, rating, session_line

from recalldrill.measure import Outcome, RevlogRow
from recalldrill.tuning import (
    CONFOUND_WARNING,
    CSV_COLUMNS,
    DELETED,
    T_CAVEAT,
    TOO_SMALL,
    CardInfo,
    CardRow,
    Report,
    ReportSettings,
    Suggestion,
    build_report,
    chunks_bucket,
    collect_cids,
    confirmation_text,
    render_html,
    render_text,
    stat,
    suggest_encode_reps,
    suggest_t,
    to_csv,
    tuning_line,
    words_bucket,
)

CH1 = CardInfo("Med Term::Ch 1", "Med Term")
CH2 = CardInfo("Med Term::Ch 2", "Med Term")
OTHER = CardInfo("Other", "Other")
S1 = [Drilled(101, words=1), Drilled(102, words=3), Drilled(103, words=5, chunks=2),
      Drilled(104, words=12, chunks=3, attempts=20, misses=2, reveals=1)]  # fmt: skip


def scenario() -> tuple[list[dict[str, Any]], list[RevlogRow], dict[int, CardInfo]]:
    lines = [
        session_line("s1", ms(2026, 10, 1, 14), S1, holdout=[201, 202]),
        handoff_line("s1", ms(2026, 10, 1, 15), S1, holdout=[201, 202]),
        session_line("s2", ms(2026, 10, 3, 14), [Drilled(105)]),
        {"type": "handoff", "sessionId": "s2", "declined": True, "timestamp": "x"},
        {"type": "tuning", "parameter": "encode_reps", "old": 3, "new": 2},
    ]
    revlog = [
        rating(101, ms(2026, 10, 2, 10), ease=1),  # next day, Again
        rating(102, ms(2026, 10, 1, 20), ease=1),  # same Anki day: not an outcome
        rating(102, ms(2026, 10, 2, 10), ease=3),
        rating(103, ms(2026, 10, 6, 10), ease=3),  # 5 days later: late
        # 104: no rating yet: pending
        rating(201, ms(2026, 10, 2, 10), ease=3),  # holdout introduced
        rating(201, ms(2026, 10, 2, 10, 5), ease=3),
        rating(201, ms(2026, 10, 3, 10), ease=1, type_=1),  # next day, Again
        rating(202, ms(2026, 10, 2, 10), ease=0, type_=4),  # manual: not an introduction
        rating(301, ms(2026, 9, 1, 10), ease=3),  # baseline, before s1
        rating(301, ms(2026, 9, 3, 10), ease=3, type_=1),
        rating(302, ms(2026, 10, 2, 10), ease=3),  # introduced after s1: not baseline
        rating(302, ms(2026, 10, 3, 10), ease=1),
        rating(303, ms(2026, 9, 1, 10), ease=3),  # another top-level deck
        rating(303, ms(2026, 9, 2, 10), ease=1),
        rating(304, ms(2026, 9, 1, 10), ease=3),
        rating(304, ms(2026, 9, 10, 10), ease=3, type_=3),  # cram: not counted
        rating(304, ms(2026, 9, 12, 10), ease=1, type_=1),  # late
    ]
    cards = {101: CH1, 102: CH1, 103: CH1, 104: CH1, 201: CH1, 202: CH1}
    cards |= {301: CH2, 302: CH2, 303: OTHER, 304: CH2}
    return lines, revlog, cards


def report(deck_filter: str | None = None, min_n: int = 1) -> Report:
    lines, revlog, cards = scenario()
    return build_report(
        lines,
        revlog,
        deck_filter,
        cards=cards,
        rollover=ROLLOVER,
        settings=ReportSettings(min_n=min_n),
        tz=UTC,
    )


def by_cid(rows: Sequence[CardRow]) -> dict[int, CardRow]:
    return {r.cid: r for r in rows}


def test_outcomes_per_group() -> None:
    r = report()
    drilled = by_cid(r.group("drilled"))
    assert sorted(drilled) == [101, 102, 103, 104]  # s2's declined handoff isn't there
    assert drilled[101].outcome.status == "outcome" and drilled[101].outcome.again is True
    assert drilled[102].outcome.again is False and drilled[102].outcome.elapsed == 1
    assert drilled[103].outcome.status == "late" and drilled[103].outcome.elapsed == 5
    assert drilled[104].outcome == Outcome("pending", ms(2026, 10, 1, 15))
    assert drilled[104].words == 12 and drilled[104].chunks == 3 and drilled[104].struggle == 3
    assert drilled[101].encode_reps == 3 and drilled[101].mode == "B"
    assert drilled[101].card_class == "suspended_new" and drilled[101].deck == "Med Term::Ch 1"
    holdout = by_cid(r.group("holdout"))
    assert holdout[201].outcome.again is True and holdout[201].outcome.elapsed == 1
    assert holdout[201].outcome.t0_ms == ms(2026, 10, 2, 10)
    assert holdout[202].outcome.status == "pending" and holdout[202].outcome.t0_ms is None
    baseline = by_cid(r.group("baseline"))
    assert sorted(baseline) == [301, 304]  # 302 came after the first session, 303 elsewhere
    assert (baseline[301].outcome.elapsed, baseline[301].outcome.again) == (2, False)
    assert baseline[304].outcome.status == "late"


def test_header_and_comparison() -> None:
    r = report()
    assert r.sessions == 2 and r.decks == ["Med Term"]
    assert (r.first_day, r.last_day) == (date(2026, 10, 1), date(2026, 10, 3))
    assert r.counts("drilled") == (4, 2, 1, 1)
    assert r.counts("holdout") == (2, 1, 0, 1)
    drilled, holdout, baseline = r.comparison
    assert (drilled.n, drilled.again, drilled.pending, drilled.late) == (2, 1, 1, 1)
    assert drilled.trials == (6 + 6 + 6 + 20) / 4 and drilled.struggle == 3 / 4
    assert (holdout.n, holdout.again, holdout.trials) == (1, 1, None)
    assert (baseline.n, baseline.again) == (1, 0)
    text = render_text(r)
    assert CONFOUND_WARNING in text
    assert "Sessions: 2 (2026-10-01 to 2026-10-03)" in text
    assert "Drilled cards handed off: 4: 2 with a next-day outcome, 1 rated later" in text
    assert CONFOUND_WARNING in render_html(r).replace("&#x27;", "'")


def test_small_groups_say_n_too_small() -> None:
    r = report(min_n=30)
    assert all(s.too_small for s in r.comparison)
    assert TOO_SMALL in render_text(r)
    assert all(s.rate_text() == TOO_SMALL for _, stats in r.breakdowns for s in stats)
    assert [s.actionable for s in r.suggestions] == [False, False]


def test_breakdowns() -> None:
    r = report()
    names = [title for title, _ in r.breakdowns]
    assert names == [
        "answer words",
        "chunks",
        "encodeReps",
        "adjustment (+1 / 0 / −1)",
        "card class",
        "handoff mode",
        "deck",
    ]
    words = {s.label: s for s in dict(r.breakdowns)["answer words"]}
    assert list(words) == ["1", "2–3", "4–8", "9–15"]
    assert (words["1"].n, words["1"].again) == (1, 1)
    assert words["9–15"].pending == 1
    chunks = [s.label for s in dict(r.breakdowns)["chunks"]]
    assert chunks == ["none", "2", "3"]
    assert [words_bucket(w) for w in (1, 2, 3, 4, 8, 9, 15, 16, None)] == [
        "1", "2–3", "2–3", "4–8", "4–8", "9–15", "9–15", "16+", "unknown",
    ]  # fmt: skip
    assert [chunks_bucket(c) for c in (0, 2, 3, 4, 7, None)] == [
        "none", "2", "3", "4+", "4+", "unknown",
    ]  # fmt: skip


def test_deck_filter() -> None:
    lines, revlog, cards = scenario()
    cards[103] = CardInfo("Path::Ch 1", "Path")
    r = build_report(
        lines,
        revlog,
        "Path",
        cards=cards,
        rollover=ROLLOVER,
        tz=UTC,
    )
    assert [x.cid for x in r.rows if x.group == "drilled"] == [103]
    assert r.decks == ["Med Term", "Path"] and r.sessions == 1
    assert r.group("holdout") == [] and r.group("baseline") == []


def test_deleted_cards_keep_their_rows() -> None:
    lines, revlog, cards = scenario()
    del cards[101]
    r = build_report(
        lines,
        revlog,
        None,
        cards=cards,
        rollover=ROLLOVER,
        tz=UTC,
    )
    row = by_cid(r.group("drilled"))[101]
    assert row.deck == DELETED and row.outcome.again is True


def test_collect_cids() -> None:
    lines, _, _ = scenario()
    assert collect_cids(lines) == ({101, 102, 103, 104}, {201, 202})


def test_csv() -> None:
    r = report()
    rows = list(csv.reader(io.StringIO(to_csv(r, UTC))))
    assert tuple(rows[0]) == CSV_COLUMNS
    assert len(rows) == 1 + len(r.rows) == 1 + 4 + 2 + 2
    first = dict(zip(CSV_COLUMNS, rows[1], strict=True))
    assert first["group"] == "drilled" and first["cid"] == "101" and first["again"] == "1"
    assert first["t0"] == "2026-10-01T15:00:00+00:00" and first["elapsed_days"] == "1"
    pending = dict(zip(CSV_COLUMNS, rows[4], strict=True))
    assert pending["status"] == "pending" and pending["again"] == "" and pending["ease"] == ""


# ---------------------------------------------------------------------------
# Suggestions
# ---------------------------------------------------------------------------


def rows(
    n: int,
    again: int,
    *,
    words: int,
    chunks: int = 0,
    attempts: int = 6,
    reps: int = 3,
    start: int = 0,
) -> list[CardRow]:
    out: list[CardRow] = []
    for i in range(n):
        o = Outcome("outcome", 0, 1, 1, 1 if i < again else 3)
        out.append(
            CardRow(
                group="drilled",
                cid=start + i,
                deck="D",
                top="D",
                outcome=o,
                words=words,
                chunks=chunks,
                attempts=attempts,
                encode_reps=reps,
                misses=0,
                reveals=0,
            )
        )
    return out


def test_t_suggests_lower_when_unchunked_cards_do_worse() -> None:
    # Unchunked 5–8 words: 20/40 Again. Chunked 9–12 words: 2/40.
    data = rows(40, 20, words=7) + rows(40, 2, words=10, chunks=2, start=100)
    s = suggest_t(data, 8, 30)
    assert (s.proposed, s.actionable) == (6, True)
    assert s.verdict.startswith("Suggest 8 → 6")
    assert s.caveat == T_CAVEAT
    assert s.evidence[0].startswith("Unchunked, 5–8 words: n 40, Again 50%")
    assert s.evidence[1].startswith("Chunked, 9–12 words: n 40, Again 5%")


def test_t_suggests_higher_when_chunking_costs_more_for_the_same_result() -> None:
    # Same Again rate; chunked: 30 trials / 10 words = 3.0 vs 6 / 7 ≈ 0.86 per word.
    data = rows(40, 4, words=7) + rows(40, 4, words=10, chunks=2, attempts=30, start=100)
    s = suggest_t(data, 8, 30)
    assert s.proposed == 10 and s.verdict.startswith("Suggest 8 → 10")
    assert "trials/word" in s.evidence[1]


def test_t_no_change_and_too_small() -> None:
    same_cost = rows(40, 4, words=7, attempts=7) + rows(
        40, 4, words=10, chunks=2, attempts=10, start=100
    )
    s = suggest_t(same_cost, 8, 30)
    assert (s.proposed, s.actionable, s.verdict) == (8, False, "No change.")
    # Chunked cards significantly worse: also no change (the rule only lowers T
    # when unchunked cards do worse).
    worse = rows(40, 2, words=7) + rows(40, 25, words=10, chunks=2, start=100)
    assert suggest_t(worse, 8, 30).proposed == 8
    small = suggest_t(rows(10, 9, words=7) + rows(40, 0, words=10, chunks=2), 8, 30)
    assert small.proposed is None and TOO_SMALL in small.verdict
    # Cards outside the windows don't count: 4 words is under T - 3.
    outside = rows(40, 30, words=4) + rows(40, 0, words=10, chunks=2, start=100)
    assert suggest_t(outside, 8, 30).proposed is None


def test_encode_reps_insufficient_variation() -> None:
    s = suggest_encode_reps(rows(100, 10, words=2, reps=3), 3, 30)
    assert s.proposed is None and s.verdict.startswith("Insufficient variation")
    two_small = rows(100, 10, words=2, reps=3) + rows(10, 1, words=2, reps=2, start=500)
    assert suggest_encode_reps(two_small, 3, 30).proposed is None


def test_encode_reps_prefers_the_lower_value_when_cis_overlap() -> None:
    data = rows(60, 9, words=2, reps=3, attempts=8) + rows(
        60, 11, words=2, reps=2, attempts=5, start=500
    )
    s = suggest_encode_reps(data, 3, 30)
    assert (s.proposed, s.actionable) == (2, True)
    assert "fewer trials" in s.verdict
    assert s.evidence[0].startswith("encodeReps 2: n 60") and "5.0 trials/card" in s.evidence[0]


def test_encode_reps_keeps_the_higher_value_when_the_lower_is_worse() -> None:
    data = rows(80, 5, words=2, reps=3) + rows(80, 40, words=2, reps=2, start=500)
    s = suggest_encode_reps(data, 3, 30)
    assert (s.proposed, s.actionable, s.verdict) == (3, False, "No change.")
    s = suggest_encode_reps(data, 2, 30)
    assert s.proposed == 3 and "significantly worse" in s.verdict


def test_stat_trials_per_word() -> None:
    s = stat("x", rows(2, 0, words=4, attempts=8), 1, per_word=True)
    assert s.trials_per_word == 2.0 and s.trials == 8.0


def test_tuning_line_and_confirmation() -> None:
    s = Suggestion("encode_reps", 3, 2, "Suggest 3 → 2: …", ("encodeReps 2: n 60", "x"))
    line = tuning_line(s, ms(2026, 10, 9), "Med Term")
    assert line == {
        "type": "tuning",
        "timestamp": "2026-10-09T12:00:00.000Z",
        "parameter": "encode_reps",
        "configKey": "encode_reps",
        "old": 3,
        "new": 2,
        "verdict": "Suggest 3 → 2: …",
        "evidence": ["encodeReps 2: n 60", "x"],
        "deckFilter": "Med Term",
    }
    text = confirmation_text(s, "Med Term", ["Med Term (3)"])
    assert text.startswith("Change the add-on's default encodeReps from 3 to 2?")
    assert "• encodeReps 2: n 60" in text and "Evidence (the Med Term deck)" in text
    assert "Med Term (3)" in text
    t = Suggestion("min_words_to_chunk", 8, 6, "v", ("e",), T_CAVEAT)
    assert "MIN_WORDS_TO_CHUNK from 8 to 6" in confirmation_text(t, None, [])
    assert T_CAVEAT in confirmation_text(t, None, [])


# ---------------------------------------------------------------------------
# Phase 6: per-card encodeReps
# ---------------------------------------------------------------------------


def test_per_card_reps_drive_the_encode_reps_rows_and_adjustment() -> None:
    """A Phase 6 line's per-card ``encodeReps`` wins over the session's; an older
    line (no per-card value) falls back to the session's, with no adjustment."""
    new = [Drilled(401, reps=4), Drilled(402, reps=3), Drilled(403, reps=2)]
    old = [Drilled(404)]
    lines = [
        session_line("p6", ms(2026, 10, 1, 14), new),
        handoff_line("p6", ms(2026, 10, 1, 15), new),
        session_line("p5", ms(2026, 10, 1, 16), old),
        handoff_line("p5", ms(2026, 10, 1, 17), old),
    ]
    revlog = [rating(c, ms(2026, 10, 2, 10), ease=3) for c in (401, 402, 403, 404)]
    cards = {c: CH1 for c in (401, 402, 403, 404)}
    r = build_report(lines, revlog, None, cards=cards, rollover=ROLLOVER, tz=UTC)
    drilled = by_cid(r.group("drilled"))
    assert [drilled[c].encode_reps for c in (401, 402, 403, 404)] == [4, 3, 2, 3]
    assert [drilled[c].adjustment for c in (401, 402, 403, 404)] == [1, 0, -1, None]
    reps = {s.label: s.n for s in dict(r.breakdowns)["encodeReps"]}
    assert reps == {"2": 1, "3": 2, "4": 1}
    adjust = {s.label: s.n for s in dict(r.breakdowns)["adjustment (+1 / 0 / −1)"]}
    assert adjust == {"+1": 1, "0": 1, "−1": 1, "unknown": 1}
    first = dict(zip(CSV_COLUMNS, list(csv.reader(io.StringIO(to_csv(r, UTC))))[1], strict=True))
    assert (first["encode_reps"], first["adjustment"]) == ("4", "1")
