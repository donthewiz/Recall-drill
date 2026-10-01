"""Port of the pure cases in src/test/history.spec.ts (buildHistoryEntry,
rankHardestCards). The four session-history storage cases are N/A (localStorage;
the add-on's storage is Phase 3a). One test per TS `it(...)`; the TS name is in each
docstring.
"""

from __future__ import annotations

from typing import Any, cast

from recalldrill.engine.history import build_history_entry, rank_hardest_cards
from recalldrill.engine.items import build_items
from recalldrill.engine.session import SESSION_COMPLETE_ID, empty_stats
from recalldrill.engine.types import DeckItem, DrillItem, SessionState

DECK: list[DeckItem] = [
    {"front": "Tachy", "back": "fast heart rate"},
    {"front": "Hyper", "back": "blood pressure that stays above the normal range for a long time"},
    {"front": "itis", "back": "inflammation"},
]
# Date.UTC(2026, 8, 30, 9) and Date.UTC(2026, 8, 30, 10)
SEPT_30_9AM = 1790758800000
SEPT_30_10AM = 1790762400000


def done_state(items: list[DrillItem]) -> SessionState:
    return {
        "items": items,
        "phase": "final",
        "queue": [],
        "stats": {
            **empty_stats(),
            "attempts": 12,
            "misses": 2,
            "reveals": 1,
            "startTime": SEPT_30_9AM,
        },
        "currentId": SESSION_COMPLETE_ID,
        "batchIndex": 0,
        "batchStartStats": empty_stats(),
        "config": {
            "encodeReps": 3,
            "chunkDifficulty": 35,
            "stemTolerance": True,
            "ladderMode": "cumulative",
        },
    }


def items() -> list[DrillItem]:
    return build_items(DECK, 35, "cumulative", None, 8, False)


def with_fields(item: DrillItem, **fields: Any) -> DrillItem:
    return cast(DrillItem, {**item, **fields})


def test_records_each_card() -> None:
    """TS: buildHistoryEntry > records each card with its length, chunking, and cost"""
    its = items()
    its[1] = with_fields(
        its[1], attempts=9, misses=2, reveals=1, finalMisses=1, hardSpans=["normal range"]
    )
    e = build_history_entry(done_state(its), SEPT_30_10AM)
    assert e.get("startedAt") == "2026-09-30T09:00:00.000Z"
    assert e["finishedAt"] == "2026-09-30T10:00:00.000Z"
    assert {k: e["stats"].get(k) for k in ("attempts", "misses", "reveals")} == {
        "attempts": 12,
        "misses": 2,
        "reveals": 1,
    }
    card0 = e["cards"][0]
    summary = (card0["front"], card0["words"], card0["chunks"], card0["attempts"])
    assert summary == ("Tachy", 3, 0, 0)
    assert card0["hardSpans"] == []
    card1 = e["cards"][1]
    assert card1 == {
        **card1,
        "front": "Hyper",
        "words": 12,
        "attempts": 9,
        "misses": 2,
        "reveals": 1,
        "finalMisses": 1,
        "hardSpans": ["normal range"],
    }
    chunks = its[1]["chunks"]
    assert chunks is not None and card1["chunks"] == len(chunks)


def test_keeps_a_start_time_of_zero() -> None:
    """TS: buildHistoryEntry > keeps a startTime of 0 (the epoch) instead of treating it as
    missing"""
    state = done_state(items())
    state["stats"] = {**empty_stats(), "startTime": 0}
    assert build_history_entry(state, 0).get("startedAt") == "1970-01-01T00:00:00.000Z"
    del state["stats"]["startTime"]
    assert "startedAt" not in build_history_entry(state, 0)


def test_rank_orders_by_trouble_then_attempts_then_deck_order() -> None:
    """TS: rankHardestCards > orders by misses + reveals + final-check misses, then
    attempts, then deck order"""
    its = items()
    scored = [
        with_fields(its[0], misses=1, attempts=4),
        with_fields(its[1], misses=1, reveals=1, attempts=9),
        with_fields(its[2], finalMisses=1, attempts=6),
    ]
    assert [i["front"] for i in rank_hardest_cards(scored)] == ["Hyper", "itis", "Tachy"]


def test_rank_leaves_out_untroubled_cards_and_respects_limit() -> None:
    """TS: rankHardestCards > leaves out cards with no trouble, and respects the limit"""
    its = items()
    scored = [
        with_fields(its[0], attempts=5),
        with_fields(its[1], misses=3),
        with_fields(its[2], misses=1),
    ]
    assert [i["front"] for i in rank_hardest_cards(scored)] == ["Hyper", "itis"]
    assert [i["front"] for i in rank_hardest_cards(scored, 1)] == ["Hyper"]
