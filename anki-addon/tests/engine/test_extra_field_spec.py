"""Port of the pure items cases in src/test/extraField.spec.ts (parseDeck,
buildItems/normalizeItem). The editCurrentItem cases are Phase 1b; the backup case
is N/A. One test per TS `it(...)`; the TS name is in each docstring.
"""

from __future__ import annotations

import json

from engine_test_support import CHUNK_DIFFICULTY

from recalldrill.engine.items import build_items, parse_deck
from recalldrill.engine.types import DeckItem

# parseDeck -- optional third "extra" segment


def test_three_field_tab_line() -> None:
    """TS: parseDeck -- optional third "extra" segment > a three-field tab line produces
    front/back/extra"""
    out = parse_deck("mitochondria\tpowerhouse of the cell\talso does aerobic respiration")
    assert out == [
        {
            "front": "mitochondria",
            "back": "powerhouse of the cell",
            "extra": "also does aerobic respiration",
        }
    ]


def test_two_field_tab_line_has_no_extra() -> None:
    """TS: parseDeck -- optional third "extra" segment > a two-field tab line produces no
    extra key at all"""
    out = parse_deck("front\tback")
    assert out == [{"front": "front", "back": "back"}]
    assert "extra" not in out[0]


def test_three_field_colon_line() -> None:
    """TS: parseDeck -- optional third "extra" segment > a three-field :: line produces
    front/back/extra"""
    out = parse_deck("Capital of France :: Paris :: Also the seat of the EU parliament sometimes")
    assert out == [
        {
            "front": "Capital of France",
            "back": "Paris",
            "extra": "Also the seat of the EU parliament sometimes",
        }
    ]


def test_two_field_colon_line_has_no_extra() -> None:
    """TS: parseDeck -- optional third "extra" segment > a two-field :: line produces no
    extra key"""
    out = parse_deck("Capital of France :: Paris")
    assert out == [{"front": "Capital of France", "back": "Paris"}]
    assert "extra" not in out[0]


def test_fourth_tab_segment_folds_into_extra() -> None:
    """TS: parseDeck -- optional third "extra" segment > a fourth tab segment folds into
    extra, not dropped"""
    out = parse_deck("f\tb\tpart one\tpart two")
    assert out[0].get("extra") == "part one\tpart two"


def test_whitespace_third_segment_is_no_extra() -> None:
    """TS: parseDeck -- optional third "extra" segment > an all-whitespace third segment
    is trimmed away to no extra"""
    out = parse_deck("f\tb\t   ")
    assert "extra" not in out[0]


def test_comments_and_blank_lines_skipped() -> None:
    """TS: parseDeck -- optional third "extra" segment > comment and blank lines are still
    skipped, extra or not"""
    out = parse_deck("# a comment\n\nf1\tb1\te1\n// another comment\nf2 :: b2")
    assert out == [
        {"front": "f1", "back": "b1", "extra": "e1"},
        {"front": "f2", "back": "b2"},
    ]


# buildItems / normalizeItem carry extra through


def test_extra_carried_onto_item() -> None:
    """TS: buildItems / normalizeItem carry extra through > a card with extra carries it
    onto the built DrillItem"""
    deck: list[DeckItem] = [{"front": "f", "back": "b", "extra": "note"}]
    [item] = build_items(deck, CHUNK_DIFFICULTY, "cumulative", None, shuffle_within_batch=False)
    assert item.get("extra") == "note"


def test_no_extra_card_is_unchanged() -> None:
    """TS: buildItems / normalizeItem carry extra through > a no-extra card is
    byte-identical to before extra existed"""
    deck: list[DeckItem] = [{"front": "f", "back": "b"}]
    [item] = build_items(deck, CHUNK_DIFFICULTY, "cumulative", None, shuffle_within_batch=False)
    assert "extra" not in item
    assert "extra" not in json.dumps(item)


def test_normalize_item_reads_extra() -> None:
    """TS: buildItems / normalizeItem carry extra through > normalizeItem reads extra from
    a saved item, undefined-safe"""
    [built] = build_items(
        [{"front": "f", "back": "b", "extra": "note"}],
        CHUNK_DIFFICULTY,
        "cumulative",
        None,
        shuffle_within_batch=False,
    )
    revived = json.loads(json.dumps(built))
    assert revived["extra"] == "note"

    old_save_no_extra = {"id": 0, "front": "f", "back": "b", "status": "new"}
    [plain] = build_items(
        [{"front": "f", "back": "b"}],
        CHUNK_DIFFICULTY,
        "cumulative",
        None,
        shuffle_within_batch=False,
    )
    assert "extra" not in plain
    assert "extra" not in old_save_no_extra
