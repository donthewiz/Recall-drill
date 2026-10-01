"""Port of the pure cases in src/test/cycleOrder.spec.ts (orderCycleQueue, and
buildItems' default shuffle). The session cases are golden scenarios
(cycle-order-*). The TS name is in each docstring.
"""

from __future__ import annotations

from recalldrill.engine.items import build_items
from recalldrill.engine.session import order_cycle_queue
from recalldrill.engine.types import DeckItem


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
