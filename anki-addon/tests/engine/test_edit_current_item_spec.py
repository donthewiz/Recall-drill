"""Port of the one pure items case in src/test/editCurrentItem.spec.ts
(selectNextEncodeItem). The editCurrentItem cases are Phase 1b. The TS name is in
the docstring.
"""

from __future__ import annotations

from engine_test_support import CHUNK_DIFFICULTY, FOUR_CHUNK_BACK

from recalldrill.engine.items import build_items, select_next_encode_item
from recalldrill.engine.types import DeckItem, DrillItem

SESSION_COMPLETE_ID = -1  # src/utils/session.ts

DECK: list[DeckItem] = [
    {"front": "Tachycardia", "back": "fast heart rate"},
    {"front": "Inner ear disorder", "back": "Menieres disease"},
    {"front": "Before surgery", "back": "pre op"},
    {"front": "Describe where the trees grow", "back": FOUR_CHUNK_BACK},
]


def test_never_picks_mastered() -> None:
    """TS: selectNextEncodeItem skips mastered items > never picks a mastered item, from
    the front or mid-rotation"""
    items = build_items(DECK, CHUNK_DIFFICULTY, "cumulative", None, shuffle_within_batch=False)
    batch: list[DrillItem] = [
        {**it, "status": "encoding"} if idx == 3 else {**it, "status": "mastered"}
        for idx, it in enumerate(items)
    ]
    assert select_next_encode_item(batch, SESSION_COMPLETE_ID) is batch[3]
    assert select_next_encode_item(batch, batch[3]["id"]) is batch[3]
    assert select_next_encode_item(batch, batch[0]["id"]) is batch[3]
    all_done: list[DrillItem] = [
        {**it, "status": "ready"} if idx == 3 else it for idx, it in enumerate(batch)
    ]
    assert select_next_encode_item(all_done, all_done[0]["id"]) is None
