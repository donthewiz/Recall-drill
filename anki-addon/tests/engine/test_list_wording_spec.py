"""Port of src/test/listWording.spec.ts (2026-10-13): list chunks and combine windows
are slices of the card's own answer, so typing the card as written is never wrong."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
import simulate as harness

from recalldrill.engine import rand
from recalldrill.engine.estimate import compute_minimum_trials
from recalldrill.engine.grading import grade, list_item_spans, split_list_items
from recalldrill.engine.items import (
    build_items,
    chunk_text,
    find_all_culprit_chunks,
    join_window,
)
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    advance_to_next_batch,
    apply_answer,
    init_session,
    select_trial,
)
from recalldrill.engine.types import DeckItem, SessionState


@dataclass(frozen=True)
class Case:
    name: str
    back: str
    chunks: list[str]
    windows: list[str]
    """windows[e]: chunks 0..e+1 as one combine window, written by hand."""


CASES = [
    Case(
        'ends "..., and x"',
        "humerus, radius and ulna, carpals, metacarpals, and phalanges",
        ["humerus, radius and ulna", "carpals, metacarpals, and phalanges"],
        ["humerus, radius and ulna, carpals, metacarpals, and phalanges"],
    ),
    Case(
        "a parenthetical item",
        "cranial (frontal, parietal), facial, spinal (cervical; thoracic), sacral, coccygeal",
        ["cranial (frontal, parietal), facial", "spinal (cervical; thoracic), sacral, coccygeal"],
        ["cranial (frontal, parietal), facial, spinal (cervical; thoracic), sacral, coccygeal"],
    ),
    Case(
        'three chunks with "and" before the last item',
        "red, orange, yellow, green, blue, indigo, violet, and white",
        ["red, orange, yellow", "green, blue, indigo", "violet, and white"],
        [
            "red, orange, yellow, green, blue, indigo",
            "red, orange, yellow, green, blue, indigo, violet, and white",
        ],
    ),
    Case(
        "semicolons and odd spacing",
        "alpha;  beta ;gamma; delta ,epsilon; zeta; eta;  theta",
        ["alpha;  beta ;gamma", "delta ,epsilon; zeta", "eta;  theta"],
        [
            "alpha;  beta ;gamma; delta ,epsilon; zeta",
            "alpha;  beta ;gamma; delta ,epsilon; zeta; eta;  theta",
        ],
    ),
    Case(
        "a 3-item list over the threshold",
        "fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), "
        "and synovial joints (freely movable)",
        [
            "fibrous joints (sutures, syndesmoses)",
            "cartilaginous joints (symphyses)",
            "synovial joints (freely movable)",
        ],
        [
            "fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses)",
            "fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), "
            "and synovial joints (freely movable)",
        ],
    ),
]
IDS = [c.name for c in CASES]
ZERO = {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0}


def _start(back: str, any_order: bool, strict: bool) -> SessionState:
    items = build_items(
        [{"front": "Q", "back": back, "anyOrder": any_order}], 35, "cumulative", None, 3, False
    )
    return init_session(
        {
            "items": items,
            "phase": "encode",
            "queue": [],
            "stats": dict(ZERO),  # type: ignore[typeddict-item]
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": dict(ZERO),  # type: ignore[typeddict-item]
            "config": {
                "encodeReps": 1,
                "chunkDifficulty": 35,
                "stemTolerance": True,
                "ladderMode": "cumulative",
                "strictPunctuation": strict,
            },
        }
    )


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_list_item_spans_slice_out_the_items(case: Case) -> None:
    items = [case.back[a:b] for a, b in list_item_spans(case.back)]
    assert items == split_list_items(case.back)


@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_chunk_and_window_targets(case: Case) -> None:
    chunks = chunk_text(case.back, 35, 3)
    assert chunks == case.chunks
    assert chunks is not None
    for any_order in (False, True):
        for i, w in enumerate(case.windows):
            assert join_window(chunks, 0, i + 2, any_order, case.back) == w
        if len(chunks) == 3:
            tail = case.back[case.back.index(chunks[1]) :]
            assert join_window(chunks, 1, 3, any_order, case.back) == tail


@pytest.mark.parametrize("any_order", [False, True])
@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("case", CASES, ids=IDS)
def test_typing_the_card_as_written_is_exact_on_every_trial(
    case: Case, strict: bool, any_order: bool
) -> None:
    s = _start(case.back, any_order, strict)
    seen: list[str] = []
    for _ in range(100):
        t = select_trial(s)
        if t is None:
            if s["phase"] != "batch-done":
                break
            s = advance_to_next_batch(s)
            continue
        assert t["target"] in case.back
        seen.append(t["target"])
        presented = t["cue"]["kind"] == "present"
        r = apply_answer(s, "" if presented else t["target"], revealed=False)
        if not presented:
            assert r["verdict"] == "exact"
        s = r["state"]
    assert s["stats"]["misses"] == 0
    for w in [*case.chunks, *case.windows]:
        assert w in seen
    assert case.back in seen  # the cycle and the Final check


def test_grade_is_exact_for_the_card_as_written() -> None:
    for c in CASES:
        for strict in (False, True):
            for w in [c.back, *c.chunks, *c.windows]:
                assert grade(w, w, strict_punctuation=strict)["verdict"] == "exact"
                assert grade(w, w, strict_punctuation=strict, any_order=True)["verdict"] == "exact"


def test_the_old_rejoined_window_was_wrong_on_strict_decks() -> None:
    c = CASES[0]
    rejoined = "humerus, radius and ulna carpals, metacarpals, phalanges"
    assert grade(c.back, rejoined, strict_punctuation=True)["verdict"] == "wrong"
    assert grade(c.back, c.windows[0], strict_punctuation=True)["verdict"] == "exact"


def test_minimum_trials_equal_a_perfect_runs_attempts() -> None:
    deck: list[DeckItem] = [{"front": "Q", "back": c.back} for c in CASES]
    for encode_reps in (1, 3):
        for min_words in (3, 8):
            config = {
                "encodeReps": encode_reps,
                "chunkDifficulty": 35,
                "stemTolerance": True,
                "ladderMode": "cumulative",
            }
            items = build_items(deck, 35, "cumulative", None, min_words)
            with rand.seeded(1):
                run = harness.simulate(deck, config, harness.LEARNERS["perfect"], min_words)  # type: ignore[arg-type]
            assert run.attempts == compute_minimum_trials(items, encode_reps)


BACK = "red, orange, yellow, green, blue, indigo, violet, and white"
CHUNKS = ["red, orange, yellow", "green, blue, indigo", "violet, and white"]


def test_remediation_finds_the_chunk_holding_the_missed_word() -> None:
    def culprits(typed: str, end: int, strict: bool) -> list[int]:
        return find_all_culprit_chunks(typed, CHUNKS, 0, end, strict, False, None, BACK)

    assert culprits(BACK, 2, False) == [2]
    assert culprits("red, orange, yellow, green, blue, violet, and white", 2, True) == [1]
    assert culprits("red, yellow, green, blue, indigo, violet, and white", 2, True) == [0]
    assert culprits("red, orange, yellow, green, blue, indigo, violet, white", 1, True) == [1]


def test_remediation_for_an_any_order_card() -> None:
    typed = "white, violet, indigo, green, yellow, red, orange"
    assert find_all_culprit_chunks(typed, CHUNKS, 0, 2, True, True, True, BACK) == [1]


def test_without_the_answer_the_chunks_join_as_before() -> None:
    assert join_window(CHUNKS, 0, 2) == "red, orange, yellow green, blue, indigo"
    assert join_window(CHUNKS, 0, 2, True) == "red, orange, yellow, green, blue, indigo"
    assert join_window(["x, y", "z, w"], 0, 2, False, BACK) == "x, y z, w"
