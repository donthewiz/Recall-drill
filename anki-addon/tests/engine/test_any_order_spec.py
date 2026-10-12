"""Port of src/test/anyOrder.spec.ts (2026-10-12): unordered list answers grade in
any order."""

from __future__ import annotations

from recalldrill.engine.grading import grade
from recalldrill.engine.items import (
    ORDER_CUES,
    build_items,
    find_all_culprit_chunks,
    list_order_from_wording,
    with_list_order,
)
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    apply_answer,
    init_session,
    select_trial,
)
from recalldrill.engine.types import SessionState

BONES = "humerus, radius and ulna, carpals, metacarpals, phalanges"
SIX = "1 frontal, 2 parietal, 2 temporal, 1 occipital, 1 sphenoid, 1 ethmoid"


def test_any_order_accepted() -> None:
    """TS: accepts the items in any order, exact when every item is exact"""
    typed = "phalanges, metacarpals, carpals, radius and ulna, humerus"
    assert grade(typed, BONES, any_order=True)["verdict"] == "exact"
    assert grade(typed, BONES)["verdict"] == "wrong"
    assert grade(typed, BONES, any_order=False) == grade(typed, BONES)


def test_near_item() -> None:
    """TS: is near when every item matches and one only nearly"""
    typed = "phalanges, the metacarpals, carpals, radius and ulna, humerus"
    assert grade(typed, BONES, any_order=True)["verdict"] == "near"


def test_missing_and_extra_items() -> None:
    """TS: is wrong with an item missing or one left over, and marks only the missing
    item"""
    missing = grade("phalanges, carpals, humerus, radius and ulna", BONES, any_order=True)
    assert missing["verdict"] == "wrong"
    assert missing["missingWords"] == ["metacarpals"]
    assert [d["word"] for d in missing["diff"] if not d["matched"]] == ["metacarpals,"]
    extra = grade(
        "phalanges, carpals, humerus, radius and ulna, metacarpals, femur", BONES, any_order=True
    )
    assert extra["verdict"] == "wrong" and extra["extraWords"] == ["femur"]


def test_whitespace_split_for_one_word_items() -> None:
    """TS: splits one-word items typed without separators on whitespace, dropping
    "and"/"or" """
    target = "epithelial, connective, muscle, and nervous"
    assert grade("nervous muscle connective epithelial", target, any_order=True)["verdict"] == (
        "exact"
    )
    assert grade("nervous and muscle or connective epithelial", target, any_order=True)[
        "verdict"
    ] == ("exact")


def test_multi_word_items_without_separators_grade_as_today() -> None:
    """TS: grades as today when multi-word items are typed without separators"""
    typed = "phalanges metacarpals carpals radius and ulna humerus"
    assert grade(typed, BONES, any_order=True) == grade(typed, BONES)


def test_list_order_from_wording() -> None:
    """TS: is "ordered" for every cue, else "any"; matches whole words only and
    ignores the cloze blank"""
    for cue in ORDER_CUES:
        assert list_order_from_wording(f"Name them {cue} now") == "ordered"
    assert list_order_from_wording("Name the types of cartilage") == "any"
    assert list_order_from_wording("Name the stepson's bicycle parts") == "any"
    assert list_order_from_wording("The four tissue types are [...]") == "any"
    assert list_order_from_wording("The cell cycle phases: [...]") == "ordered"


def test_with_list_order() -> None:
    """TS: withListOrder sets anyOrder on unordered list answers only"""
    assert with_list_order({"front": "Name the types", "back": "a, b, c"}) == {
        "front": "Name the types",
        "back": "a, b, c",
        "anyOrder": True,
    }
    assert "anyOrder" not in with_list_order({"front": "Name the steps", "back": "a, b, c"})
    assert "anyOrder" not in with_list_order({"front": "Name the pair", "back": "a, b"})


def _start() -> SessionState:
    items = build_items(
        [{"front": "Name the cranial bones", "back": SIX, "anyOrder": True}],
        35,
        "cumulative",
        None,
        8,
        False,
    )
    zero = {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0}
    return init_session(
        {
            "items": items,
            "phase": "encode",
            "queue": [],
            "stats": dict(zero),  # type: ignore[typeddict-item]
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": dict(zero),  # type: ignore[typeddict-item]
            "config": {
                "encodeReps": 1,
                "chunkDifficulty": 35,
                "stemTolerance": True,
                "ladderMode": "cumulative",
            },
        }
    )


def test_chunks_and_windows_any_order() -> None:
    """TS: a chunk and a combine window take their items in any order; windows join
    with ", " """
    s = apply_answer(_start(), "", revealed=False)["state"]
    chunk = apply_answer(s, "2 parietal, 1 frontal", revealed=False)
    assert chunk["verdict"] == "exact"
    s = chunk["state"]
    for typed in ("", "1 occipital, 2 temporal", "", "1 ethmoid, 1 sphenoid"):
        s = apply_answer(s, typed, revealed=False)["state"]
    trial = select_trial(s)
    assert trial is not None
    assert trial["target"] == "1 frontal, 2 parietal, 2 temporal, 1 occipital"
    typed = "1 occipital, 2 temporal, 2 parietal, 1 frontal"
    assert apply_answer(s, typed, revealed=False)["verdict"] == "exact"


def test_culprit_is_the_chunk_with_the_missed_item() -> None:
    """TS: remediation isolates the chunk holding the missed item, wherever it was
    typed"""
    chunks = ["1 frontal, 2 parietal", "2 temporal, 1 occipital", "1 sphenoid, 1 ethmoid"]
    typed = "1 ethmoid, 2 temporal, 1 sphenoid, 1 frontal, 2 parietal"
    assert find_all_culprit_chunks(typed, chunks, 0, 2, False, True, True) == [1]
    assert find_all_culprit_chunks(typed, chunks, 0, 2) != [1]
