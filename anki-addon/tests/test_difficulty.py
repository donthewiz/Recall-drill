"""difficulty.py: every mapping branch, the floor clamp, the chunk shift, stable."""

from __future__ import annotations

from dataclasses import replace

import pytest

from recalldrill.card_state import CardSnapshot
from recalldrill.difficulty import (
    CardAdjustment,
    DifficultySettings,
    adjust_card,
    easy_reps,
    hard_threshold,
    is_stable,
    summarize,
)

NEW = CardSnapshot(
    cid=1, nid=1, did=1, odid=0, ord=0, ntid=1, type=0, queue=0, ivl=0, due=1,
    lapses=0, reps=0, factor=0, flags=0, tags=(), fsrs_d=None, fsrs_s=None,
)  # fmt: skip
REVIEWED = replace(NEW, type=2, queue=2, ivl=10, reps=6, factor=2500)


def fsrs(d: float, s: float = 10.0, **kw: object) -> CardSnapshot:
    return replace(REVIEWED, fsrs_d=d, fsrs_s=s, **kw)  # type: ignore[arg-type]


def adj(snap: CardSnapshot | None, reps: int = 3, t: int = 8, **kw: object) -> CardAdjustment:
    return adjust_card(snap, reps, t, DifficultySettings(**kw))  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# FSRS present
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("d", [7.0, 8.5, 10.0])
def test_hard_fsrs_card_gets_a_rep_and_chunks_earlier(d: float) -> None:
    a = adj(fsrs(d))
    assert (a.basis, a.encode_reps, a.min_words_to_chunk) == ("fsrs", 4, 6)
    assert a.adjustment == 1 and a.chunks_earlier
    assert a.overrides() == {"encodeRepsOverride": 4, "minWordsToChunkOverride": 6}
    assert (a.fsrs_d, a.fsrs_s) == (d, 10.0)


@pytest.mark.parametrize("d", [1.0, 2.2, 3.0])
def test_easy_fsrs_card_gets_one_fewer_rep(d: float) -> None:
    a = adj(fsrs(d))
    assert (a.basis, a.encode_reps, a.min_words_to_chunk, a.adjustment) == ("fsrs", 2, 8, -1)
    assert a.overrides() == {"encodeRepsOverride": 2}
    assert not a.chunks_earlier


@pytest.mark.parametrize("d", [3.01, 5.0, 6.99])
def test_middle_fsrs_card_is_unchanged(d: float) -> None:
    a = adj(fsrs(d))
    assert (a.basis, a.adjustment, a.overrides()) == ("fsrs", 0, {})


@pytest.mark.parametrize(
    ("deck_reps", "expected"),
    [(5, 4), (4, 3), (3, 2), (2, 2), (1, 1)],
)
def test_easy_floor(deck_reps: int, expected: int) -> None:
    """Never below min_encode_reps (2), nor below the deck's own when that's lower:
    Med Term at 1 stays at 1, not 2."""
    assert easy_reps(deck_reps, 2) == expected
    a = adj(fsrs(2.0), reps=deck_reps)
    assert a.encode_reps == expected
    assert a.adjustment == (-1 if expected < deck_reps else 0)


def test_easy_floor_is_never_below_one() -> None:
    assert easy_reps(1, 0) == 1
    assert easy_reps(3, 0) == 2
    assert adj(fsrs(2.0), reps=1, min_encode_reps=1).encode_reps == 1


@pytest.mark.parametrize(
    ("t", "shift", "expected"),
    [(8, 2, 6), (6, 2, 4), (5, 2, 4), (4, 2, 4), (3, 2, 3), (12, 5, 7), (8, 0, 8)],
)
def test_hard_chunk_threshold(t: int, shift: int, expected: int) -> None:
    """T minus the shift, never under 4 and never above T."""
    assert hard_threshold(t, shift) == expected
    a = adj(fsrs(9.0), t=t, hard_chunk_shift=shift)
    assert a.min_words_to_chunk == expected
    assert ("minWordsToChunkOverride" in a.overrides()) == (expected < t)


def test_thresholds_are_settings() -> None:
    assert adj(fsrs(6.0), hard_d=6).adjustment == 1
    assert adj(fsrs(4.0), easy_d=4).adjustment == -1
    assert adj(fsrs(2.0), reps=4, min_encode_reps=4).adjustment == 0


def test_fsrs_wins_over_review_history() -> None:
    """With FSRS present, only D counts: lapses and the leech tag don't add a rep."""
    a = adj(fsrs(5.0, lapses=6, tags=("leech",)))
    assert (a.basis, a.adjustment) == ("fsrs", 0)


# ---------------------------------------------------------------------------
# No FSRS, review history
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "kw",
    [
        {"lapses": 3},
        {"lapses": 7},
        {"factor": 1999},
        {"factor": 1300},
        {"tags": ("leech",)},
        {"tags": ("Leech",)},
    ],
)
def test_history_hard_card_gets_one_more_rep(kw: dict[str, object]) -> None:
    a = adj(replace(REVIEWED, **kw))  # type: ignore[arg-type]
    assert (a.basis, a.encode_reps, a.adjustment) == ("history", 4, 1)
    assert a.overrides() == {"encodeRepsOverride": 4}  # no chunk shift without FSRS


@pytest.mark.parametrize("kw", [{"lapses": 2}, {"factor": 2000}, {"factor": 2500}, {"factor": 0}])
def test_history_card_otherwise_unchanged(kw: dict[str, object]) -> None:
    a = adj(replace(REVIEWED, **kw))  # type: ignore[arg-type]
    assert (a.basis, a.adjustment, a.overrides()) == ("history", 0, {})


# ---------------------------------------------------------------------------
# New cards, off, None
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("snap", [NEW, replace(NEW, queue=-1), replace(NEW, tags=("leech",)), None])
def test_new_card_has_no_override(snap: CardSnapshot | None) -> None:
    a = adj(snap)
    assert (a.basis, a.encode_reps, a.min_words_to_chunk, a.overrides()) == ("new", 3, 8, {})


def test_off_changes_nothing() -> None:
    for snap in (fsrs(9.0), fsrs(1.0), replace(REVIEWED, lapses=5)):
        a = adj(snap, adjust=False)
        assert (a.basis, a.overrides()) == ("off", {})


# ---------------------------------------------------------------------------
# stable, and the panel's line
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("snap", "stable"),
    [
        (fsrs(5.0, 30.0), True),
        (fsrs(1.0, 400.0), True),
        (fsrs(5.01, 100.0), False),
        (fsrs(4.0, 29.99), False),
        (fsrs(4.0, 60.0, tags=("leech",)), False),
        (REVIEWED, False),
        (NEW, False),
    ],
)
def test_is_stable(snap: CardSnapshot, stable: bool) -> None:
    assert is_stable(snap) is stable


def test_is_stable_thresholds() -> None:
    assert is_stable(fsrs(6.0, 20.0), min_stability=20, max_difficulty=6)
    assert not is_stable(fsrs(6.0, 20.0))


def test_summary_line() -> None:
    adjustments = [
        adj(fsrs(9.0)),
        adj(fsrs(8.0)),
        adj(fsrs(2.0)),
        adj(fsrs(5.0)),
        adj(replace(REVIEWED, lapses=4)),
        adj(NEW),
        adj(NEW),
        adj(fsrs(9.0), t=4),  # +1 rep, but already at the chunk floor
    ]
    s = summarize(adjustments, True)
    assert (s.plus, s.minus, s.chunk_earlier, s.new_cards) == (4, 1, 2, 2)
    assert s.text() == (
        "Difficulty-adjusted: 4 cards +1 rep, 1 card −1 rep, 2 cards chunk earlier. "
        "New cards (2): no FSRS data, unchanged."
    )
    off = summarize([adj(fsrs(9.0), adjust=False)], False)
    assert (off.plus, off.minus) == (0, 0)
    assert off.text().startswith("Difficulty adjustment off")


def test_all_new_deck_line() -> None:
    """Med Term (all new): nothing adjusted, and the line says why."""
    s = summarize([adj(NEW, reps=1)] * 5, True)
    assert s.text() == (
        "Difficulty-adjusted: 0 cards +1 rep, 0 cards −1 rep, 0 cards chunk earlier. "
        "New cards (5): no FSRS data, unchanged."
    )
