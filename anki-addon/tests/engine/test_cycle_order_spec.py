"""Port of the one pure items case in src/test/cycleOrder.spec.ts (buildItems'
default shuffle). The session cases are Phase 1b. The TS name is in the docstring.
"""

from __future__ import annotations

from recalldrill.engine.items import build_items
from recalldrill.engine.types import DeckItem


def make_short_deck(count: int) -> list[DeckItem]:
    return [{"front": f"Q{i}", "back": f"answer{i}"} for i in range(count)]


def test_default_still_shuffles_within_batches() -> None:
    """TS: encode order (buildItems shuffleWithinBatch=false, as the app uses) > default
    (no flag) still shuffles within batches, for the harness"""
    items = build_items(make_short_deck(10), 35, "cumulative", 5)
    assert sorted(i["id"] for i in items[:5]) == [0, 1, 2, 3, 4]
    assert sorted(i["id"] for i in items[5:]) == [5, 6, 7, 8, 9]
