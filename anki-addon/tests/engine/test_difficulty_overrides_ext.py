"""Engine extension (add-on only): per-card ``encodeRepsOverride`` and
``minWordsToChunkOverride``.

docs/DECISIONS.md, "Engine extensions beyond the TS engine". Absent, every
read is the session's ``encodeReps`` / threshold, exactly as the TS engine (the
golden and simulate parity suites run with them absent, unchanged). Set, a card
needs its own number of consecutive blind successes on every ``encodeReps``
step (full, the final combine window, remediation), the progress bar and the
perfect-run floor count them, and a mid-session rebuild keeps them.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, cast

import pytest
from simulate import pattern_overrides, perfect_learner, simulate

from recalldrill.engine import rand
from recalldrill.engine.estimate import compute_minimum_trials
from recalldrill.engine.items import (
    MIN_WORDS_TO_CHUNK,
    build_item,
    build_items,
    normalize_item,
    reps_for,
)
from recalldrill.engine.progress import compute_item_progress, compute_session_progress
from recalldrill.engine.session import (
    apply_answer,
    apply_next,
    edit_current_item,
    empty_stats,
    init_session,
    select_trial,
)
from recalldrill.engine.types import (
    DeckItem,
    DrillItem,
    ItemOverrides,
    LadderMode,
    SessionConfig,
    SessionState,
)

SHORT = "alpha beta"
TWELVE = "one two three four five six seven eight nine ten eleven twelve"
"""12 words: chunks of round(12 * 0.35) = 4 words, so 3 chunks; cumulative
windows 1-2 (1 rep) and 1-3 (the final window, encodeReps)."""


def config(
    reps: int = 3, ladder: LadderMode = "cumulative", min_words: int | None = None
) -> SessionConfig:
    c: SessionConfig = {
        "encodeReps": reps,
        "chunkDifficulty": 35,
        "stemTolerance": True,
        "ladderMode": ladder,
        "strictPunctuation": False,
        "batchSize": 0,
        "cycleOrder": "inOrder",
    }
    if min_words is not None:
        c["minWordsToChunk"] = min_words
    return c


def session(
    backs: Sequence[str],
    overrides: Sequence[ItemOverrides | None],
    cfg: SessionConfig | None = None,
) -> SessionState:
    c = cfg if cfg is not None else config()
    deck: list[DeckItem] = [{"front": f"q{i}", "back": b} for i, b in enumerate(backs)]
    items = build_items(
        deck,
        c["chunkDifficulty"],
        c["ladderMode"],
        0,
        c.get("minWordsToChunk", MIN_WORDS_TO_CHUNK),
        shuffle_within_batch=False,
        overrides=overrides,
    )
    return init_session(
        {
            "items": items,
            "phase": "encode",
            "queue": [],
            "stats": {**empty_stats(), "startTime": 0},
            "currentId": -1,
            "batchIndex": 0,
            "batchStartStats": empty_stats(),
            "config": c,
        }
    )


def item(s: SessionState, item_id: int = 0) -> DrillItem:
    return next(i for i in s["items"] if i["id"] == item_id)


def answer(s: SessionState, correct: bool = True) -> tuple[SessionState, dict[str, Any]]:
    trial = select_trial(s)
    assert trial is not None
    r = apply_answer(s, trial["target"] if correct else "zzz", revealed=False)
    nxt = r["state"]
    if r["advance"] == "manual" and nxt["phase"] in ("cycle", "final"):
        nxt = apply_next(nxt)
    return nxt, cast(dict[str, Any], r)


# ---------------------------------------------------------------------------
# reps_for and the fields
# ---------------------------------------------------------------------------


def test_reps_for() -> None:
    cfg = config(3)
    assert reps_for({}, cfg) == 3
    assert reps_for({"encodeRepsOverride": 5}, cfg) == 5
    assert reps_for({"encodeRepsOverride": 1}, 4) == 1
    assert reps_for({}, 4) == 4


def test_absent_overrides_build_the_ts_item() -> None:
    """No overrides (None, or an empty entry): the same item as the TS call, no new keys."""
    p: DeckItem = {"front": "q", "back": TWELVE}
    plain = build_item(p, 0, 35, "cumulative", 8)
    assert build_item(p, 0, 35, "cumulative", 8, {}) == plain
    assert build_item(p, 0, 35, "cumulative", 8, None) == plain
    assert "encodeRepsOverride" not in plain and "minWordsToChunkOverride" not in plain
    deck: list[DeckItem] = [p, {"front": "r", "back": SHORT}]
    a = build_items(deck, 35, "cumulative", 0, 8, shuffle_within_batch=False)
    b = build_items(deck, 35, "cumulative", 0, 8, shuffle_within_batch=False, overrides=[{}, None])
    assert a == b


def test_build_item_threshold_override_wins_over_the_session() -> None:
    p: DeckItem = {"front": "q", "back": "a b c d e f g"}  # 7 words
    assert build_item(p, 0, 35, "cumulative", 8)["chunks"] is None
    chunked = build_item(p, 0, 35, "cumulative", 8, {"minWordsToChunkOverride": 6})
    assert chunked["chunks"] == ["a b", "c d", "e f g"]
    assert chunked["stage"] == "chunks" and chunked.get("minWordsToChunkOverride") == 6
    # An override above the session's threshold wins too (never made by the mapping).
    p12: DeckItem = {"front": "q", "back": TWELVE}
    assert (
        build_item(p12, 0, 35, "cumulative", 8, {"minWordsToChunkOverride": 12})["chunks"] is None
    )


def test_normalize_threads_both_fields_through() -> None:
    it = build_item(
        {"front": "q", "back": SHORT},
        0,
        35,
        "cumulative",
        8,
        {"encodeRepsOverride": 4, "minWordsToChunkOverride": 6},
    )
    n = normalize_item(cast(dict[str, Any], it))
    assert (n.get("encodeRepsOverride"), n.get("minWordsToChunkOverride")) == (4, 6)
    bare = normalize_item(
        cast(dict[str, Any], build_item({"front": "q", "back": SHORT}, 0, 35, "cumulative", 8))
    )
    assert "encodeRepsOverride" not in bare and "minWordsToChunkOverride" not in bare


# ---------------------------------------------------------------------------
# Scripted sessions
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("override", "needed"), [(None, 3), (5, 5), (1, 1), (2, 2)])
def test_full_card_needs_its_own_reps(override: int | None, needed: int) -> None:
    o: ItemOverrides = {} if override is None else {"encodeRepsOverride": override}
    s = session([SHORT], [o])
    r: dict[str, Any] = {}
    for k in range(1, needed + 1):
        assert item(s)["stage"] == "full" and item(s)["status"] == "encoding"
        s, r = answer(s)
        if k < needed:
            assert r["feedback"]["text"] == f"{k} of {needed} streaks"
    assert item(s)["status"] == "ready"
    assert r["feedback"]["dwellKey"] == "full-advance"


def test_two_cards_with_different_reps() -> None:
    """Card 0 (+1) needs 4, card 1 (-1) needs 2; the session's 3 applies to neither."""
    s = session([SHORT, "gamma delta"], [{"encodeRepsOverride": 4}, {"encodeRepsOverride": 2}])
    answered: dict[int, int] = {0: 0, 1: 0}
    while s["phase"] == "encode":
        trial = select_trial(s)
        assert trial is not None
        answered[trial["itemId"]] += 1
        s, _ = answer(s)
    assert answered == {0: 4, 1: 2}


def _to_final_window(s: SessionState) -> SessionState:
    """Correct answers until card 0 sits on its last combine window."""
    for _ in range(50):
        it = item(s)
        seq = it["combineSeq"]
        if it["stage"] == "combine" and seq is not None and it["combineSeqIdx"] == len(seq) - 1:
            return s
        s, _ = answer(s)
    raise AssertionError("never reached the final window")


@pytest.mark.parametrize(("override", "needed"), [(None, 3), (4, 4), (1, 1)])
def test_final_combine_window_uses_the_card_reps(override: int | None, needed: int) -> None:
    o: ItemOverrides = {} if override is None else {"encodeRepsOverride": override}
    s = _to_final_window(session([TWELVE], [o]))
    assert item(s)["chunks"] is not None and len(item(s)["chunks"] or []) == 3
    for _ in range(needed):
        assert item(s)["status"] == "encoding"
        s, _ = answer(s)
    assert item(s)["status"] == "ready"


def test_intermediate_window_still_needs_one_rep() -> None:
    """Cumulative: only the final window takes encodeReps (the override too)."""
    s = session([TWELVE], [{"encodeRepsOverride": 5}])
    while item(s)["stage"] == "chunks":
        s, _ = answer(s)
    assert item(s)["combineSeqIdx"] == 0
    s, r = answer(s)
    assert item(s)["combineSeqIdx"] == 1 and r["feedback"]["dwellKey"] == "combine-advance"


def test_exhaustive_ladder_uses_the_card_reps_on_every_window() -> None:
    s = session([TWELVE], [{"encodeRepsOverride": 2}], config(3, "exhaustive"))
    while item(s)["stage"] == "chunks":
        s, _ = answer(s)
    seq = item(s)["combineSeq"]
    assert seq is not None
    combine_answers = 0
    while item(s)["status"] == "encoding":
        s, _ = answer(s)
        combine_answers += 1
    assert combine_answers == 2 * len(seq)


@pytest.mark.parametrize(("override", "needed"), [(None, 3), (4, 4), (1, 1)])
def test_remediation_uses_the_card_reps(override: int | None, needed: int) -> None:
    o: ItemOverrides = {} if override is None else {"encodeRepsOverride": override}
    s = session([TWELVE], [o])
    while item(s)["stage"] == "chunks":
        s, _ = answer(s)
    # Window 1-2 has two chunks, so one miss starts remediation on both parts.
    s, r = answer(s, correct=False)
    assert item(s)["stage"] == "remediate" and r["feedback"]["dwellKey"] == "combine-miss-remediate"
    assert len(item(s)["remediateQueue"]) == 1
    corrects = 0
    while item(s)["stage"] == "remediate":
        s, r = answer(s)
        corrects += 1
        if (
            item(s)["stage"] == "remediate"
            and r["feedback"]["dwellKey"] == "remediate-streak-progress"
        ):
            assert r["feedback"]["text"].endswith(f"of {needed} streaks")
    assert corrects == 2 * needed  # two parts, each `needed` in a row
    assert item(s)["stage"] == "combine"


def test_edit_restart_keeps_the_overrides_and_chunks_with_the_card_threshold() -> None:
    o: ItemOverrides = {"encodeRepsOverride": 4, "minWordsToChunkOverride": 6}
    s = session([SHORT], [o])
    s, _ = answer(s)
    res = edit_current_item(s, {"front": "q0", "back": "a b c d e f g"})  # 7 words
    assert res["restarted"]
    rebuilt = item(res["state"])
    assert (rebuilt.get("encodeRepsOverride"), rebuilt.get("minWordsToChunkOverride")) == (4, 6)
    assert rebuilt["chunks"] == ["a b", "c d", "e f g"]  # 7 > 6: chunked under the card's T
    # Without the threshold override the session's 8 keeps 7 words whole.
    plain = edit_current_item(
        session([SHORT], [{"encodeRepsOverride": 4}]), {"front": "q0", "back": "a b c d e f g"}
    )
    assert item(plain["state"])["chunks"] is None
    assert item(plain["state"]).get("encodeRepsOverride") == 4


def test_edit_without_restart_keeps_the_overrides() -> None:
    o: ItemOverrides = {"encodeRepsOverride": 4, "minWordsToChunkOverride": 6}
    s = session(["a b c d e f g"], [o])
    res = edit_current_item(s, {"front": "q0", "back": "A b c d e f g"})  # case only
    assert not res["restarted"]
    it = item(res["state"])
    assert (it.get("encodeRepsOverride"), it.get("minWordsToChunkOverride")) == (4, 6)
    assert it["chunks"] == ["A b", "c d", "e f g"]  # rechunked under 6, same count: kept


def test_progress_counts_the_card_reps() -> None:
    s = session([SHORT, "gamma delta"], [{"encodeRepsOverride": 4}, {}])
    s, _ = answer(s)  # card 0: 1 of 4
    assert compute_item_progress(item(s, 0), 3) == pytest.approx(0.7 / 4)
    s, _ = answer(s)  # card 1: 1 of 3
    assert compute_item_progress(item(s, 1), 3) == pytest.approx(0.7 / 3)
    p = compute_session_progress(s["items"], 3)
    assert p["deckFraction"] == pytest.approx((0.7 / 4 + 0.7 / 3) / 2)


# ---------------------------------------------------------------------------
# The perfect-run floor (coldStartEstimate.consistency.spec.ts, with overrides)
# ---------------------------------------------------------------------------

PROSE = [
    "the quick brown fox jumps over the lazy dog and runs far away into the dark woods",
    "a stitch in time saves nine but only when the needle is sharp and the thread holds",
]
DECKS: dict[str, list[str]] = {
    "short": ["heart", "liver", "lung", "brain", "bone marrow", "skin"] * 2,
    "medium": ["a b c d e f", "a b c d e f g", "a b c d e", "a b c d e f g h"] * 3,
    "prose": PROSE * 6,
    "mixed": ["heart", "liver", "lung", "skin", "brain", "bone"] + PROSE * 3,
}


@pytest.mark.parametrize("deck_name", list(DECKS))
@pytest.mark.parametrize("reps", [1, 3, 5])
@pytest.mark.parametrize("ladder", ["cumulative", "exhaustive"])
def test_minimum_trials_with_mixed_overrides_matches_a_perfect_session(
    deck_name: str, reps: int, ladder: LadderMode
) -> None:
    backs = DECKS[deck_name]
    deck: list[DeckItem] = [{"front": f"q{i}", "back": b} for i, b in enumerate(backs)]
    overrides = pattern_overrides(len(deck), reps)
    cfg: SessionConfig = {
        "encodeReps": reps,
        "chunkDifficulty": 35,
        "stemTolerance": True,
        "ladderMode": ladder,
    }
    with rand.seeded(7):
        run = simulate(deck, cfg, perfect_learner, overrides=overrides)
    items = build_items(deck, 35, ladder, None, MIN_WORDS_TO_CHUNK, overrides=overrides)
    assert run.attempts == compute_minimum_trials(items, reps, ladder)
    # The overrides changed the floor wherever they could.
    plain = build_items(deck, 35, ladder, None, MIN_WORDS_TO_CHUNK)
    if reps > 2:
        assert items != plain


def test_pattern_overrides_follow_the_mapping() -> None:
    o = pattern_overrides(12, 3)
    assert o[:4] == [{"encodeRepsOverride": 4, "minWordsToChunkOverride": 6}] * 4
    assert o[4:8] == [{}] * 4
    assert o[8:] == [{"encodeRepsOverride": 2}] * 4
    assert pattern_overrides(12, 1)[8:] == [{}] * 4  # a deck at 1 stays at 1
    assert pattern_overrides(12, 2)[8:] == [{}] * 4  # never below min_encode_reps (2)
