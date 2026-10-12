"""Port of src/test/listChunking.spec.ts (2026-10-12): list answers are chunked at
item boundaries, and the word rule never cuts inside parentheses."""

from __future__ import annotations

from recalldrill.engine.estimate import compute_minimum_trials
from recalldrill.engine.items import build_item, chunk_text, list_items

SIX = "1 frontal, 2 parietal, 2 temporal, 1 occipital, 1 sphenoid, 1 ethmoid"


def test_list_items_splits_trims_and_drops_and_or() -> None:
    """TS: splits on commas and semicolons, trims, and drops a leading "and"/"or" """
    assert list_items("skeletal, cardiac, and smooth") == ["skeletal", "cardiac", "smooth"]
    assert list_items("alpha; beta; or gamma") == ["alpha", "beta", "gamma"]


def test_list_items_keeps_brackets_and_wording() -> None:
    """TS: keeps separators inside () and [] and each item's own wording"""
    assert list_items("true (vertebrosternal, sternal), false [x; y], floating") == [
        "true (vertebrosternal, sternal)",
        "false [x; y]",
        "floating",
    ]


def test_list_needs_three_items() -> None:
    """TS: is a list only with 3 or more items"""
    assert list_items("radius and ulna") is None
    assert list_items("alpha, beta") is None
    assert list_items("a, , b,") is None
    assert list_items("humerus, radius and ulna, carpals") == [
        "humerus",
        "radius and ulna",
        "carpals",
    ]


def test_cuts_at_item_boundaries() -> None:
    """TS: cuts at item boundaries, never mid-item, joining items with ", " """
    assert chunk_text(SIX, 35) == [
        "1 frontal, 2 parietal",
        "2 temporal, 1 occipital",
        "1 sphenoid, 1 ethmoid",
    ]


def test_four_items_chunk_whatever_the_word_count() -> None:
    """TS: chunks a list of 4+ items whatever its word count"""
    assert chunk_text("epithelial, connective, muscle, nervous", 35) == [
        "epithelial, connective",
        "muscle, nervous",
    ]


def test_lonely_trailing_item_merges() -> None:
    """TS: merges a lonely 1-item trailing chunk into the one before"""
    assert chunk_text("a, b, c, d, e", 35) == ["a, b", "c, d, e"]


def test_three_item_lists_do_not_chunk() -> None:
    """TS: a 3-item list: never at or under the threshold; over it, 2 items per chunk
    merge to one, so none"""
    assert chunk_text("skeletal, cardiac, smooth", 35) is None
    long = (
        "fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), "
        "synovial joints (freely movable)"
    )
    assert chunk_text(long, 35) is None


def test_hundred_percent_means_no_chunking() -> None:
    """TS: chunkDifficulty >= 100 still means no chunking"""
    assert chunk_text(SIX, 100) is None


def test_percentage_applies_to_items() -> None:
    """TS: uses the same percentage on items as on words"""
    assert chunk_text("a, b, c, d, e, f, g, h", 35) == ["a, b, c", "d, e, f", "g, h"]
    assert chunk_text("a, b, c, d, e, f, g, h", 50) == ["a, b, c, d", "e, f, g, h"]


def test_cut_moves_out_of_parentheses() -> None:
    """TS: moves a cut inside parentheses to just after the closing word"""
    assert chunk_text("w1 w2 (w3 w4 w5 w6 w7 w8 w9 w10) w11 w12", 35) == [
        "w1 w2 (w3 w4 w5 w6 w7 w8 w9 w10)",
        "w11 w12",
    ]


def test_min_trials_follow_list_chunks() -> None:
    """TS: buildItem chunks a list by items, and the minimum trials count those chunks"""
    item = build_item({"front": "Q", "back": "a, b, c, d, e, f"}, 0, 35, "cumulative", 8)
    assert item["stage"] == "chunks"
    assert item["chunks"] == ["a, b", "c, d", "e, f"]
    assert compute_minimum_trials([item], 1) == 3 + 1 + 1 + 1 + 1
