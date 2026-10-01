"""Port of the computeAccuracyPercent cases in src/test/telemetry.spec.ts. The
per-card telemetry cases are golden scenarios (telemetry-*). One test per TS
`it(...)`; the TS name is in each docstring.
"""

from __future__ import annotations

from recalldrill.engine.items import build_items
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    apply_answer,
    compute_accuracy_percent,
    compute_batch_summary,
    empty_stats,
    init_session,
)
from recalldrill.engine.types import DeckItem


def test_excludes_reveals() -> None:
    """TS: computeAccuracyPercent > excludes reveals from the correct count"""
    assert compute_accuracy_percent({"attempts": 10, "misses": 2, "reveals": 3}) == 50


def test_missing_reveals_is_zero() -> None:
    """TS: computeAccuracyPercent > treats a missing reveals field (an old save) as 0"""
    assert compute_accuracy_percent({"attempts": 4, "misses": 1}) == 75


def test_no_attempts_and_never_negative() -> None:
    """TS: computeAccuracyPercent > reads 100 with no attempts and never goes negative"""
    assert compute_accuracy_percent({"attempts": 0, "misses": 0, "reveals": 0}) == 100
    assert compute_accuracy_percent({"attempts": 1, "misses": 1, "reveals": 1}) == 0


def test_is_what_the_batch_summary_reports() -> None:
    """TS: computeAccuracyPercent > is what the batch summary reports"""
    deck: list[DeckItem] = [
        {"front": "Tachy", "back": "fast heart rate"},
        {
            "front": "Hyper",
            "back": "blood pressure that stays above the normal range for a long time",
        },
    ]
    state = init_session(
        {
            "items": build_items(deck, 35, "cumulative", None, 8, False),
            "phase": "encode",
            "queue": [],
            "stats": empty_stats(),
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": empty_stats(),
            "config": {
                "encodeReps": 3,
                "chunkDifficulty": 35,
                "stemTolerance": True,
                "ladderMode": "cumulative",
                "cycleOrder": "inOrder",
            },
        }
    )
    result = apply_answer(state, "fast heart rate", revealed=True)
    assert compute_batch_summary(result["state"])["accuracyPercent"] == 0
