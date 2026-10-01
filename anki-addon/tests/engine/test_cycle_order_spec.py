"""Port of the pure cases in src/test/cycleOrder.spec.ts (orderCycleQueue,
buildItems' default shuffle, and how many random numbers a cycle miss or reveal
draws). The session cases are golden scenarios (cycle-order-*). The TS name is in
each docstring.
"""

from __future__ import annotations

import pytest

from recalldrill.engine import rand
from recalldrill.engine.items import build_items
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    apply_answer,
    init_session,
    order_cycle_queue,
)
from recalldrill.engine.types import CycleOrder, DeckItem, SessionState, SessionStats


def make_short_deck(count: int) -> list[DeckItem]:
    return [{"front": f"Q{i}", "back": f"answer{i}"} for i in range(count)]


def test_default_still_shuffles_within_batches() -> None:
    """TS: encode order (buildItems shuffleWithinBatch=false, as the app uses) > default
    (no flag) still shuffles within batches, for the harness"""
    items = build_items(make_short_deck(10), 35, "cumulative", 5)
    assert sorted(i["id"] for i in items[:5]) == [0, 1, 2, 3, 4]
    assert sorted(i["id"] for i in items[5:]) == [5, 6, 7, 8, 9]


def test_in_order_sorts_without_mutating() -> None:
    """TS: orderCycleQueue > inOrder sorts ids ascending without mutating the input"""
    ids = [3, 0, 4, 1, 2]
    assert order_cycle_queue(ids, "inOrder") == [0, 1, 2, 3, 4]
    assert ids == [3, 0, 4, 1, 2]


def test_shuffled_is_a_permutation() -> None:
    """TS: orderCycleQueue > shuffled (and default) returns a permutation of the same ids"""
    assert sorted(order_cycle_queue([3, 0, 4, 1, 2], "shuffled")) == [0, 1, 2, 3, 4]
    assert sorted(order_cycle_queue([3, 0, 4, 1, 2])) == [0, 1, 2, 3, 4]


def _cycle_state(count: int, batch_size: int, cycle_order: CycleOrder) -> SessionState:
    """The spec's cycleState(): every card 'ready', the session starting in its cycle."""
    zero: SessionStats = {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0}
    items = build_items(make_short_deck(count), 35, "cumulative", batch_size)
    return init_session(
        {
            "items": [{**i, "status": "ready"} for i in items],
            "phase": "cycle",
            "queue": [],
            "stats": zero,
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": zero.copy(),
            "config": {
                "encodeReps": 1,
                "chunkDifficulty": 35,
                "stemTolerance": True,
                "ladderMode": "cumulative",
                "batchSize": batch_size,
                "cycleOrder": cycle_order,
            },
        }
    )


@pytest.mark.parametrize(("order", "draws"), [("inOrder", 0), ("shuffled", 1)])
def test_cycle_miss_and_reveal_random_draws(
    order: CycleOrder, draws: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """TS: random draws on a cycle miss or reveal > cycleOrder=inOrder: a miss and a reveal
    each draw 0 random number(s) / cycleOrder=shuffled: ... each draw 1"""
    state = _cycle_state(5, 5, order)
    calls: list[float] = []

    def counting_source() -> float:
        calls.append(0.5)
        return 0.5

    monkeypatch.setattr(rand, "_source", counting_source)
    apply_answer(state, "zzzz wrong", revealed=False)
    assert len(calls) == draws
    calls.clear()
    apply_answer(state, "", revealed=True)
    assert len(calls) == draws
