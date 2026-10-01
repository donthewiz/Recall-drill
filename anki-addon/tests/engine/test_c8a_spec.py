"""Port of the normalizeItem migration cases in src/test/c8a.spec.ts. The
applyAnswer cases are Phase 1b. One test per TS `it(...)`; the TS name is in each
docstring.
"""

from __future__ import annotations

from typing import Any

from engine_test_support import FOUR_CHUNK_BACK, FOUR_CHUNK_CHUNKS

from recalldrill.engine.items import normalize_item


def test_clamps_legacy_chunk_streak_to_1() -> None:
    """TS: C8a migration: normalizeItem clamps a pre-C8a chunkStreak into {0, 1} > clamps a
    legacy mid-chunk chunkStreak (accumulated under the old encodeReps-per-chunk rule) down to 1"""
    legacy: dict[str, Any] = {
        "id": 0,
        "front": "Q",
        "back": FOUR_CHUNK_BACK,
        "status": "encoding",
        "encodeStreak": 0,
        "cycleStreak": 0,
        "chunks": FOUR_CHUNK_CHUNKS,
        "chunkIndex": 1,
        "chunkStreak": 2,  # impossible under C8a's {0,1} range -- a pre-C8a save
        "combineSeq": None,
        "combineSeqIdx": 0,
        "combineStreak": 0,
        "combineMissCount": 0,
        "remediateStack": [],
        "remediateQueue": [],
        "remediateReturnSeqIdx": 0,
        "stage": "chunks",
    }
    normalized = normalize_item(legacy)
    assert normalized["chunkStreak"] == 1


def test_leaves_valid_chunk_streak() -> None:
    """TS: C8a migration: normalizeItem clamps a pre-C8a chunkStreak into {0, 1} > leaves a
    valid {0, 1} chunkStreak untouched"""
    legacy: dict[str, Any] = {
        "id": 0,
        "front": "Q",
        "back": FOUR_CHUNK_BACK,
        "status": "encoding",
        "chunks": FOUR_CHUNK_CHUNKS,
        "chunkIndex": 1,
        "chunkStreak": 1,
        "stage": "chunks",
    }
    assert normalize_item(legacy)["chunkStreak"] == 1

    legacy_zero = {**legacy, "chunkStreak": 0}
    assert normalize_item(legacy_zero)["chunkStreak"] == 0
