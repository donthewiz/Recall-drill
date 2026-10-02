"""Cold-start time estimate: a floor/ceiling range before a session, recalibrated at
each batch interstitial. Port of the pure part of ``src/utils/estimate.ts``.

The TS module is the reference; this is a copy, not an improvement. Parity is
checked against recorded TS outputs in ``tests/golden/session_scenarios.json``.

==========================================  =============================================
TS name                                     Python name
==========================================  =============================================
``COLD_START_MULTIPLIERS``                  ``COLD_START_MULTIPLIERS``
``pickColdStartDeckShape``                  ``pick_cold_start_deck_shape``
``computeMinimumTrials``                    ``compute_minimum_trials``
``estimateColdStartSeconds``                ``estimate_cold_start_seconds``
``formatColdStartMinutes``                  ``_format_cold_start_minutes``
``formatColdStartRange``                    ``format_cold_start_range``
``computeColdStartEstimate``                ``compute_cold_start_estimate``
``computeCumulativeColdStartMultiplier``    ``compute_cumulative_cold_start_multiplier``
``computeRemainingColdStartRange``          ``compute_remaining_cold_start_range``
==========================================  =============================================

Not ported: ``getColdStartHistory`` / ``saveColdStartHistory`` (storage, Phase 3a).
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Literal, TypedDict

from .items import MIN_WORDS_TO_CHUNK, build_items, partition_into_batches, reps_for
from .jscompat import js_round, js_split_ws, js_trim, utf16_len
from .types import DeckItem, DrillItem, LadderMode, SessionState

ExposureLevel = Literal["fresh", "once", "familiar"]
ColdStartDeckShape = Literal["chunked", "full"]

# Seed multipliers: ceiling = floor (perfect-run trial count) x this value.
# Derived from docs/BASELINE.md's harness table; see the TS comment.
COLD_START_MULTIPLIERS: dict[ColdStartDeckShape, dict[ExposureLevel, float]] = {
    "chunked": {"fresh": 5.3, "once": 1.8, "familiar": 1.4},
    "full": {"fresh": 2.5, "once": 1.5, "familiar": 1.2},
}

# Mirrors test/simulate.ts's wallClockEstimate constants.
_COLD_START_TYPING_CPS = 4.5
_COLD_START_PER_TRIAL_OVERHEAD_SEC = 1.5


class ColdStartEstimate(TypedDict):
    floorTrials: int
    ceilingTrials: int
    floorSeconds: float
    ceilingSeconds: float
    multiplier: float
    deckShape: ColdStartDeckShape


class ColdStartRange(TypedDict):
    floorTrials: int
    ceilingTrials: int
    floorSeconds: float
    ceilingSeconds: float


def pick_cold_start_deck_shape(
    items: Sequence[DeckItem] | Sequence[DrillItem],
) -> ColdStartDeckShape:
    """'chunked' when more than half the backs are longer than MIN_WORDS_TO_CHUNK."""
    if not items:
        return "full"

    def word_count(back: str) -> int:
        return len([w for w in js_split_ws(js_trim(back)) if w])

    chunkable_count = len([it for it in items if word_count(it["back"]) > MIN_WORDS_TO_CHUNK])
    return "chunked" if chunkable_count / len(items) > 0.5 else "full"


def compute_minimum_trials(
    items: Sequence[DrillItem],
    encode_reps: int,
    ladder_mode: LadderMode | None = "cumulative",
    include_final_check: bool = True,
) -> int:
    """The minimum ``stats.attempts`` for a perfect learner (presentations excluded).

    ``ladder_mode`` None is TS ``undefined``, which takes the 'cumulative' default.
    Add-on extension: a card's ``encodeRepsOverride`` replaces ``encode_reps``
    for that card (:func:`.items.reps_for`).
    """
    total = 0
    for item in items:
        reps = reps_for(item, encode_reps)
        chunks = item["chunks"]
        combine_seq = item["combineSeq"]
        if chunks is not None and combine_seq is not None:
            total += len(chunks)
            if ladder_mode is None or ladder_mode == "cumulative":
                total += max(0, len(combine_seq) - 1) + reps
            else:
                total += len(combine_seq) * reps
        else:
            total += reps
        total += 2  # cycle: exactly 2 corrects to reach mastered
        if include_final_check:
            total += 1  # Phase 3: one Final-check answer
    return total


def estimate_cold_start_seconds(
    trials: float, items: Sequence[DeckItem] | Sequence[DrillItem]
) -> float:
    """Typing time for ``trials`` answers of the items' average back length."""
    if items:
        total_chars = 0
        for it in items:
            total_chars += utf16_len(it["back"])
        avg_chars: float = total_chars / len(items)
    else:
        avg_chars = 20
    return trials * (avg_chars / _COLD_START_TYPING_CPS + _COLD_START_PER_TRIAL_OVERHEAD_SEC)


def _format_cold_start_minutes(seconds: float) -> str:
    mins = seconds / 60
    if mins < 1:
        return "<1"
    return str(js_round(mins))


def format_cold_start_range(floor_seconds: float, ceiling_seconds: float) -> str:
    """'~{low}-{high} min', collapsing both-under-a-minute and equal ends."""
    low = _format_cold_start_minutes(floor_seconds)
    high = _format_cold_start_minutes(ceiling_seconds)
    if low == "<1" and high == "<1":
        return "under a minute"
    if low == high:
        return f"~{low} min"
    return f"~{low}\u2013{high} min"


def compute_cold_start_estimate(
    deck_items: Sequence[DeckItem],
    encode_reps: int,
    chunk_difficulty: float,
    ladder_mode: LadderMode,
    multiplier_override: float | ExposureLevel,
    min_words_to_chunk: int = MIN_WORDS_TO_CHUNK,
) -> ColdStartEstimate:
    """Setup-screen estimate. ``build_items`` shuffles, so this draws from
    :mod:`.rand` exactly like the TS call (the result doesn't depend on the draws).

    ``min_words_to_chunk`` is an add-on extension (the session's threshold);
    left out, the TS constant."""
    deck_shape = pick_cold_start_deck_shape(deck_items)
    built = build_items(
        deck_items, chunk_difficulty, ladder_mode, min_words_to_chunk=min_words_to_chunk
    )
    floor_trials = compute_minimum_trials(built, encode_reps, ladder_mode)
    multiplier = (
        COLD_START_MULTIPLIERS[deck_shape][multiplier_override]
        if isinstance(multiplier_override, str)
        else multiplier_override
    )
    ceiling_trials = js_round(floor_trials * multiplier)
    return {
        "floorTrials": floor_trials,
        "ceilingTrials": ceiling_trials,
        "floorSeconds": estimate_cold_start_seconds(floor_trials, deck_items),
        "ceilingSeconds": estimate_cold_start_seconds(ceiling_trials, deck_items),
        "multiplier": multiplier,
        "deckShape": deck_shape,
    }


def _effective_batches(state: SessionState) -> list[list[DrillItem]]:
    size = state["config"].get("batchSize")
    return partition_into_batches(state["items"], len(state["items"]) if size is None else size)


def compute_cumulative_cold_start_multiplier(state: SessionState) -> float | None:
    """Actual attempts / perfect-run minimum, over every batch FULLY completed so far.

    None when no batch is complete yet. The Final check's floor (and the
    attempts already spent in it) only count once every item is finalDone.
    """
    batches = _effective_batches(state)
    batch_index = state["batchIndex"]
    current_batch = batches[batch_index] if 0 <= batch_index < len(batches) else []
    current_batch_done = len(current_batch) > 0 and all(
        it["status"] == "mastered" for it in current_batch
    )
    completed_through_idx = batch_index if current_batch_done else batch_index - 1
    if completed_through_idx < 0:
        return None

    completed_items = [it for batch in batches[: completed_through_idx + 1] for it in batch]
    final_check_done = len(state["items"]) > 0 and all(it.get("finalDone") for it in state["items"])
    min_trials = compute_minimum_trials(
        completed_items,
        state["config"]["encodeReps"],
        state["config"].get("ladderMode"),
        final_check_done,
    )
    if state["phase"] == "final":
        if final_check_done:
            completed_attempts = state["stats"]["attempts"]
        else:
            start = state.get("finalCheckStartAttempts")
            completed_attempts = state["stats"]["attempts"] if start is None else start
    elif current_batch_done:
        completed_attempts = state["stats"]["attempts"]
    else:
        completed_attempts = state["batchStartStats"]["attempts"]
    return completed_attempts / min_trials if min_trials > 0 else None


def compute_remaining_cold_start_range(state: SessionState, multiplier: float) -> ColdStartRange:
    """Floor/ceiling for the batches after the current one."""
    batches = _effective_batches(state)
    remaining_items = [it for batch in batches[state["batchIndex"] + 1 :] for it in batch]
    floor_trials = compute_minimum_trials(
        remaining_items, state["config"]["encodeReps"], state["config"].get("ladderMode")
    )
    ceiling_trials = js_round(floor_trials * multiplier)
    return {
        "floorTrials": floor_trials,
        "ceilingTrials": ceiling_trials,
        "floorSeconds": estimate_cold_start_seconds(floor_trials, remaining_items),
        "ceilingSeconds": estimate_cold_start_seconds(ceiling_trials, remaining_items),
    }
