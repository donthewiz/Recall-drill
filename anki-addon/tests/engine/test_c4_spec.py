"""Port of src/test/c4.spec.ts (computeItemProgress, computeSessionProgress, and the
perfect-session acceptance walk). One test per TS `it(...)`; the TS name is in each
docstring. The golden scenarios also record progress after every step.
"""

from __future__ import annotations

import pytest
from engine_test_support import CHUNK_DIFFICULTY, FOUR_CHUNK_BACK

from recalldrill.engine.items import build_items
from recalldrill.engine.progress import compute_item_progress, compute_session_progress
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    apply_answer,
    apply_next,
    init_session,
)
from recalldrill.engine.types import DrillItem, SessionState, SessionStats


def four_chunk_item() -> DrillItem:
    return build_items([{"front": "Q", "back": FOUR_CHUNK_BACK}], CHUNK_DIFFICULTY)[0]


def test_new_ready_mastered() -> None:
    """TS: computeItemProgress > new is 0, ready is 0.7, mastered is 1.0"""
    item = four_chunk_item()
    assert compute_item_progress(item, 2) == 0
    assert compute_item_progress({**item, "status": "ready"}, 2) == 0.7
    assert compute_item_progress({**item, "status": "mastered"}, 2) == 1


def test_chunk_progress_grows() -> None:
    """TS: computeItemProgress > encoding: chunk progress falls strictly between 0 and 0.7
    and grows with chunkIndex/chunkStreak"""
    encoding: DrillItem = {**four_chunk_item(), "status": "encoding"}
    at_start = compute_item_progress(encoding, 2)
    streaking = compute_item_progress({**encoding, "chunkStreak": 1}, 2)
    one_done = compute_item_progress({**encoding, "chunkIndex": 1}, 2)
    two_done = compute_item_progress({**encoding, "chunkIndex": 2}, 2)
    assert at_start == 0
    assert at_start < streaking < one_done < two_done < 0.7


def test_chunk_progress_ignores_encode_reps() -> None:
    """TS: computeItemProgress > encoding: chunk progress is independent of encodeReps (C8a
    fixed the chunk criterion at 1 cued + 1 blind)"""
    halfway: DrillItem = {**four_chunk_item(), "status": "encoding", "chunkStreak": 1}
    assert compute_item_progress(halfway, 1) == compute_item_progress(halfway, 2)
    assert compute_item_progress(halfway, 2) == compute_item_progress(halfway, 5)


def test_combine_picks_up_where_chunks_left_off() -> None:
    """TS: computeItemProgress > encoding: combine-stage progress picks up where the chunks
    left off (all chunks pre-credited)"""
    finished: DrillItem = {
        **four_chunk_item(),
        "status": "encoding",
        "chunkIndex": 4,
        "chunkStreak": 0,
    }
    entered: DrillItem = {**finished, "stage": "combine", "combineSeqIdx": 0, "combineStreak": 0}
    assert compute_item_progress(entered, 2) == pytest.approx(compute_item_progress(finished, 2))
    mid: DrillItem = {**entered, "combineSeqIdx": 2}
    assert compute_item_progress(mid, 2) > compute_item_progress(entered, 2)


def test_remediate_holds_progress_flat() -> None:
    """TS: computeItemProgress > encoding: remediate holds progress flat at the combine
    window it interrupted (doesn't dip)"""
    mid: DrillItem = {
        **four_chunk_item(),
        "status": "encoding",
        "chunkIndex": 4,
        "stage": "combine",
        "combineSeqIdx": 1,
        "combineStreak": 0,
    }
    assert compute_item_progress({**mid, "stage": "remediate"}, 2) == compute_item_progress(mid, 2)


def test_deck_and_batch_fractions() -> None:
    """TS: computeSessionProgress > deckFraction averages every item; batchFraction averages
    only the given subset"""
    items = build_items(
        [{"front": "Q1", "back": FOUR_CHUNK_BACK}, {"front": "Q2", "back": FOUR_CHUNK_BACK}],
        CHUNK_DIFFICULTY,
    )
    mastered: DrillItem = {**items[0], "status": "mastered"}
    fresh: DrillItem = {**items[1], "status": "new"}
    both = [mastered, fresh]
    assert compute_session_progress(both, 2)["deckFraction"] == pytest.approx(0.5)
    assert compute_session_progress(both, 2, [mastered])["batchFraction"] == 1
    assert compute_session_progress(both, 2, [fresh])["batchFraction"] == 0
    assert compute_session_progress(both, 2)["masteredCount"] == 1


def test_batch_defaults_to_items() -> None:
    """TS: computeSessionProgress > defaults batch to the full item list when omitted
    (matches the doc's 2-arg signature)"""
    result = compute_session_progress([four_chunk_item()], 2)
    assert result["batchFraction"] == result["deckFraction"]


def _target(state: SessionState, it: DrillItem) -> str:
    chunks = it["chunks"]
    seq = it["combineSeq"]
    if state["phase"] in ("cycle", "final"):
        return it["back"]
    if it["stage"] == "chunks" and chunks is not None:
        return chunks[it["chunkIndex"]]
    if it["stage"] == "combine" and chunks is not None and seq is not None:
        window = seq[it["combineSeqIdx"]]
        return " ".join(chunks[window["start"] - 1 : window["end"]])
    return FOUR_CHUNK_BACK


def test_progress_over_a_perfect_session() -> None:
    """TS: C4 acceptance: progress over a full perfect-learner session > never decreases,
    starts > 0 after the first correct chunk, and reaches exactly 1.0 only once every item
    is mastered"""
    zero: SessionStats = {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0}
    state: SessionState = init_session(
        {
            "items": build_items([{"front": "Q", "back": FOUR_CHUNK_BACK}], CHUNK_DIFFICULTY),
            "phase": "encode",
            "queue": [],
            "stats": zero.copy(),
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": zero.copy(),
            "config": {
                "encodeReps": 2,
                "chunkDifficulty": CHUNK_DIFFICULTY,
                "stemTolerance": True,
                "ladderMode": "cumulative",
            },
        }
    )
    readings = [compute_session_progress(state["items"], 2)["deckFraction"]]
    assert readings[0] == 0
    for _ in range(500):
        if state["currentId"] == SESSION_COMPLETE_ID:
            break
        it = next(i for i in state["items"] if i["id"] == state["currentId"])
        result = apply_answer(state, _target(state, it), revealed=False)
        state = result["state"]
        if result["advance"] == "manual" and state["phase"] in ("cycle", "final"):
            state = apply_next(state)
        readings.append(compute_session_progress(state["items"], 2)["deckFraction"])

    assert readings[1] > 0
    assert all(b >= a for a, b in zip(readings, readings[1:], strict=False))
    assert readings[-1] == 1
    assert all(i["status"] == "mastered" for i in state["items"])
    first_one = readings.index(1)
    assert first_one > 0 and all(r < 1 for r in readings[:first_one])
