"""Per-deck session history entries, built from the per-card telemetry
``apply_answer`` records. Port of the pure part of ``src/utils/history.ts``.

The TS module is the reference; this is a copy, not an improvement. Parity is
checked against recorded TS outputs in ``tests/golden/session_scenarios.json``.

=======================  ===========================
TS name                  Python name
=======================  ===========================
``MAX_HISTORY_ENTRIES``  ``MAX_HISTORY_ENTRIES``
``wordCount``            ``_word_count``
``buildHistoryCard``     ``build_history_card``
``buildHistoryEntry``    ``build_history_entry``
``cardTroubleScore``     ``card_trouble_score``
``rankHardestCards``     ``rank_hardest_cards``
=======================  ===========================

Not ported: ``get/set/append/clearSessionHistory`` (storage, Phase 3a).
``buildHistoryEntry``'s ``finishedAt`` has no default here: callers pass the
time explicitly, as epoch milliseconds (what JS ``Date.now()`` returns).
"""

from __future__ import annotations

import functools
from collections.abc import Sequence
from typing import NotRequired, TypedDict

from .jscompat import js_iso_string, js_split_ws, js_trim
from .types import DrillItem, LadderMode, SessionState, SessionStats

# Oldest entries drop off past this, to keep one deck's log bounded.
MAX_HISTORY_ENTRIES = 50


class SessionHistoryCard(TypedDict):
    front: str
    words: int
    # Chunk count, or 0 for a card drilled whole (the 'full' stage).
    chunks: int
    attempts: int
    misses: int
    reveals: int
    nearMisses: int
    finalMisses: int
    hardSpans: list[str]


class SessionHistoryConfig(TypedDict):
    encodeReps: int
    chunkDifficulty: float
    ladderMode: LadderMode
    batchSize: NotRequired[int]


class SessionHistoryEntry(TypedDict):
    startedAt: NotRequired[str]
    finishedAt: str
    stats: SessionStats
    config: SessionHistoryConfig
    cards: list[SessionHistoryCard]


def _word_count(s: str) -> int:
    return len([w for w in js_split_ws(js_trim(s)) if w])


def build_history_card(item: DrillItem) -> SessionHistoryCard:
    chunks = item["chunks"]
    return {
        "front": item["front"],
        "words": _word_count(item["back"]),
        "chunks": len(chunks) if chunks is not None else 0,
        "attempts": item.get("attempts", 0),
        "misses": item.get("misses", 0),
        "reveals": item.get("reveals", 0),
        "nearMisses": item.get("nearMisses", 0),
        "finalMisses": item.get("finalMisses", 0),
        "hardSpans": item.get("hardSpans", []),
    }


def build_history_entry(state: SessionState, finished_at: float) -> SessionHistoryEntry:
    """One history entry for a finished session. ``finished_at`` is epoch milliseconds
    (JS ``Date.now()``); both times are formatted like ``toISOString()``."""
    config: SessionHistoryConfig = {
        "encodeReps": state["config"]["encodeReps"],
        "chunkDifficulty": state["config"]["chunkDifficulty"],
        "ladderMode": state["config"]["ladderMode"],
    }
    batch_size = state["config"].get("batchSize")
    if batch_size is not None:
        config["batchSize"] = batch_size
    entry: SessionHistoryEntry = {
        "finishedAt": js_iso_string(finished_at),
        "stats": state["stats"],
        "config": config,
        "cards": [build_history_card(i) for i in state["items"]],
    }
    # A missing startTime leaves startedAt out; 0 (the epoch) is a real time.
    start_time = state["stats"].get("startTime")
    if start_time is not None:
        entry["startedAt"] = js_iso_string(start_time)
    return entry


def card_trouble_score(item: DrillItem) -> int:
    """Misses and reveals, plus misses in the Final check."""
    return item.get("misses", 0) + item.get("reveals", 0) + item.get("finalMisses", 0)


def _hardest_first(a: DrillItem, b: DrillItem) -> int:
    """The TS comparator, as written: trouble, then attempts, then deck order."""
    return (
        card_trouble_score(b) - card_trouble_score(a)
        or b.get("attempts", 0) - a.get("attempts", 0)
        or a["id"] - b["id"]
    )


def rank_hardest_cards(items: Sequence[DrillItem], limit: int = 5) -> list[DrillItem]:
    """Cards with any trouble, worst first. Python's sort is stable, like JS's."""
    troubled = [i for i in items if card_trouble_score(i) > 0]
    return sorted(troubled, key=functools.cmp_to_key(_hardest_first))[:limit]
