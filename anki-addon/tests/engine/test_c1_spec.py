"""Port of the ladder cases in src/test/c1.spec.ts (buildCombineSequence,
requiredRepsForWindow). The two applyAnswer end-to-end cases are Phase 1b.
One test per TS `it(...)`; the TS name is in each docstring.
"""

from __future__ import annotations

from recalldrill.engine.items import build_combine_sequence, required_reps_for_window


def test_cumulative_is_n_minus_1_growing_prefixes() -> None:
    """TS: buildCombineSequence > cumulative (forward chaining): n-1 growing-prefix windows"""
    seq = build_combine_sequence(6, "cumulative")
    assert len(seq) == 5
    assert seq == [
        {"start": 1, "end": 2},
        {"start": 1, "end": 3},
        {"start": 1, "end": 4},
        {"start": 1, "end": 5},
        {"start": 1, "end": 6},
    ]


def test_exhaustive_is_n_choose_2_windows() -> None:
    """TS: buildCombineSequence > exhaustive: n(n-1)/2 windows, unchanged from the original
    ladder"""
    seq = build_combine_sequence(6, "exhaustive")
    assert len(seq) == 15


def test_defaults_to_cumulative() -> None:
    """TS: buildCombineSequence > defaults to cumulative when no mode is given"""
    assert build_combine_sequence(4) == build_combine_sequence(4, "cumulative")


def test_only_final_window_needs_encode_reps() -> None:
    """TS: requiredRepsForWindow > requires just 1 rep for every window except the final
    (whole-answer) one"""
    seq = build_combine_sequence(4, "cumulative")
    reps = [required_reps_for_window(w, 4, 3) for w in seq]
    assert reps == [1, 1, 3]
