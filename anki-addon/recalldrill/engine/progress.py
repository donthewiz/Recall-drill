"""C4: per-item and per-session progress for the session progress bars. Port of
``src/utils/progress.ts``.

The TS module is the reference; this is a copy, not an improvement. Parity is
checked against recorded TS outputs in ``tests/golden/session_scenarios.json``.

==========================  ============================
TS name                     Python name
==========================  ============================
``clamp01``                 ``_clamp01``
``computeItemProgress``     ``compute_item_progress``
``computeSessionProgress``  ``compute_session_progress``
==========================  ============================
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TypedDict

from .items import reps_for
from .jscompat import js_sum
from .types import DrillItem


class SessionProgress(TypedDict):
    deckFraction: float
    batchFraction: float
    masteredCount: int
    readyCount: int


def _clamp01(n: float) -> float:
    return max(0, min(1, n))


def compute_item_progress(item: DrillItem, encode_reps: int) -> float:
    """0..1 encoding progress: 'new' 0, 'ready' 0.7, 'mastered' 1, and 'encoding' the
    fraction of the item's own ladder done, scaled into 0..0.7.

    Add-on extension: a card's ``encodeRepsOverride`` replaces ``encode_reps``
    (:func:`.items.reps_for`)."""
    encode_reps = reps_for(item, encode_reps)
    if item["status"] == "mastered":
        return 1
    if item["status"] == "ready":
        return 0.7
    if item["status"] == "new":
        return 0

    # status == 'encoding'
    chunks = item["chunks"]
    if chunks is None:
        # Unchunked ('full' stage): a single ladder rung needing encodeReps.
        frac = _clamp01(item["encodeStreak"] / encode_reps) if encode_reps > 0 else 0
        return frac * 0.7

    total_chunks = len(chunks)
    combine_seq = item["combineSeq"]
    total_windows = len(combine_seq) if combine_seq is not None else 0
    total_units = total_chunks + total_windows
    if total_units == 0:
        return 0

    if item["stage"] == "chunks":
        # C8a: a chunk is 1 cued + 1 blind, so the denominator is a fixed 2.
        streak_frac = _clamp01(item["chunkStreak"] / 2)
        completed_units = item["chunkIndex"] + streak_frac
    elif item["stage"] == "combine":
        streak_frac = _clamp01(item["combineStreak"] / encode_reps) if encode_reps > 0 else 0
        completed_units = total_chunks + item["combineSeqIdx"] + streak_frac
    else:
        # 'remediate' holds progress at the window it interrupted.
        completed_units = total_chunks + item["combineSeqIdx"]

    return _clamp01(completed_units / total_units) * 0.7


def compute_session_progress(
    items: Sequence[DrillItem], encode_reps: int, batch: Sequence[DrillItem] | None = None
) -> SessionProgress:
    """Deck-wide and batch-scoped progress. ``batch`` None (TS undefined) is ``items``."""
    if batch is None:
        batch = items

    def average(lst: Sequence[DrillItem]) -> float:
        if not lst:
            return 0
        return js_sum(compute_item_progress(it, encode_reps) for it in lst) / len(lst)

    return {
        "deckFraction": average(items),
        "batchFraction": average(batch),
        "masteredCount": len([it for it in items if it["status"] == "mastered"]),
        "readyCount": len([it for it in items if it["status"] == "ready"]),
    }
