"""Port of the pure items cases in src/test/c3.spec.ts (partitionIntoBatches,
selectNextEncodeItem). The session cases are Phase 1b. One test per TS `it(...)`;
the TS name is in each docstring.
"""

from __future__ import annotations

from engine_test_support import CHUNK_DIFFICULTY

from recalldrill.engine.items import build_items, partition_into_batches, select_next_encode_item
from recalldrill.engine.types import DeckItem, DrillItem

SESSION_COMPLETE_ID = -1  # src/utils/session.ts


def make_chunked_deck(count: int) -> list[DeckItem]:
    return [
        {
            "front": f"Q{i}",
            "back": " ".join(
                f"{w}{i}"
                for w in (
                    "alpha",
                    "beta",
                    "gamma",
                    "delta",
                    "epsilon",
                    "zeta",
                    "eta",
                    "theta",
                    "iota",
                )
            ),
        }
        for i in range(count)
    ]


def test_13_cards_at_batch_size_5() -> None:
    """TS: partitionIntoBatches > a 13-card deck at batchSize 5 produces batches of 5/5/3"""
    items = build_items(make_chunked_deck(13), CHUNK_DIFFICULTY, "cumulative", 5)
    batches = partition_into_batches(items, 5)
    assert [len(b) for b in batches] == [5, 5, 3]


def test_batch_size_0_or_omitted_is_one_batch() -> None:
    """TS: partitionIntoBatches > batchSize 0 (or omitted) is a single whole-deck batch"""
    items = build_items(make_chunked_deck(13), CHUNK_DIFFICULTY, "cumulative")
    assert len(partition_into_batches(items, 0)) == 1
    assert len(partition_into_batches(items)) == 1


def test_round_robins_skipping_ready() -> None:
    """TS: selectNextEncodeItem > round-robins over not-yet-ready items, skipping ready ones"""
    items = build_items(make_chunked_deck(3), CHUNK_DIFFICULTY, "cumulative", 3)
    [batch] = partition_into_batches(items, 3)
    assert select_next_encode_item(batch, SESSION_COMPLETE_ID) is batch[0]
    assert select_next_encode_item(batch, batch[0]["id"]) is batch[1]
    assert select_next_encode_item(batch, batch[1]["id"]) is batch[2]
    assert select_next_encode_item(batch, batch[2]["id"]) is batch[0]  # wraps

    ready_batch: list[DrillItem] = [
        {**it, "status": "ready"} if idx == 1 else it for idx, it in enumerate(batch)
    ]
    assert select_next_encode_item(ready_batch, ready_batch[0]["id"]) is ready_batch[2]

    all_ready: list[DrillItem] = [{**it, "status": "ready"} for it in batch]
    assert select_next_encode_item(all_ready, all_ready[0]["id"]) is None
