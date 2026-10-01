"""Replays tests/golden/items.json (recorded from src/utils/items.ts)."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from engine_test_support import case_ids, check, load_golden

from recalldrill.engine import items, rand
from recalldrill.engine.items import (
    build_combine_sequence,
    build_item,
    build_items,
    chunk_text,
    culprit_half,
    find_all_culprit_chunks,
    normalize_item,
    parse_deck,
    partition_into_batches,
    render_first_letter_cue,
    required_reps_for_window,
    resolve_batch_config,
    resolve_source_deck_editable,
    select_next_encode_item,
    shuffle,
    slugify,
    split_in_half,
)

GOLDEN = load_golden("items.json")


def _cases(section: str) -> Any:
    cases = GOLDEN[section]
    return pytest.mark.parametrize("case", cases, ids=case_ids(cases))


def test_constants() -> None:
    check(items.MIN_WORDS_TO_CHUNK, GOLDEN["constants"]["MIN_WORDS_TO_CHUNK"], "MIN_WORDS_TO_CHUNK")


@_cases("chunkTextGrid")
def test_chunk_text_grid(case: Any) -> None:
    text = GOLDEN["chunkTextGridTexts"][case["n"] - 1]
    check(
        chunk_text(text, case["pct"], case["min"]),
        case["out"],
        "chunkText",
        text=text,
        chunk_percent=case["pct"],
        min_words_to_chunk=case["min"],
    )


@_cases("chunkTextDefaults")
def test_chunk_text_defaults(case: Any) -> None:
    check(chunk_text(case["text"]), case["out"], "chunkText(text)", text=case["text"])
    check(chunk_text(case["text"], 50), case["out50"], "chunkText(text, 50)", text=case["text"])


@_cases("chunkTextIrregular")
def test_chunk_text_irregular_whitespace(case: Any) -> None:
    check(chunk_text(case["text"], 20, 4), case["out"], "chunkText(text, 20, 4)", text=case["text"])


@_cases("targets")
def test_render_first_letter_cue(case: Any) -> None:
    check(
        render_first_letter_cue(case["text"]),
        case["cue"],
        "renderFirstLetterCue",
        text=case["text"],
    )


@_cases("combine")
def test_combine_sequence_and_reps(case: Any) -> None:
    n = case["n"]
    mode = case["mode"]
    seq = build_combine_sequence(n) if mode is None else build_combine_sequence(n, mode)
    check(seq, case["seq"], "buildCombineSequence", n=n, mode=mode)
    for reps in case["reps"]:
        check(
            [required_reps_for_window(w, n, reps["encodeReps"]) for w in seq],
            reps["out"],
            "requiredRepsForWindow",
            n=n,
            mode=mode,
            encode_reps=reps["encodeReps"],
        )


@_cases("windows")
def test_window_split_in_half(case: Any) -> None:
    chunks = GOLDEN["chunkings"][case["chunking"]]["chunks"]
    assert " ".join(chunks[case["startIdx"] : case["endIdx"] + 1]) == case["text"]
    check(split_in_half(case["text"]), case["halves"], "splitInHalf", text=case["text"])


@_cases("remediation")
def test_remediation_helpers(case: Any) -> None:
    window = GOLDEN["windows"][case["window"]]
    chunks = GOLDEN["chunkings"][window["chunking"]]["chunks"]
    start, end = window["startIdx"], window["endIdx"]
    left, right = window["halves"]
    typed = case["typed"]
    inputs = {"typed": typed, "chunks": chunks, "start_idx": start, "end_idx": end}
    check(
        find_all_culprit_chunks(typed, chunks, start, end),
        case["findAllCulpritChunks"]["lenient"],
        "findAllCulpritChunks",
        **inputs,
    )
    check(
        find_all_culprit_chunks(typed, chunks, start, end, True),
        case["findAllCulpritChunks"]["strict"],
        "findAllCulpritChunks strict",
        **inputs,
    )
    check(
        culprit_half(typed, left, right),
        case["culpritHalf"]["lenient"],
        "culpritHalf",
        typed=typed,
        left=left,
        right=right,
    )
    check(
        culprit_half(typed, left, right, True),
        case["culpritHalf"]["strict"],
        "culpritHalf strict",
        typed=typed,
        left=left,
        right=right,
    )


@_cases("splitInHalf")
def test_split_in_half(case: Any) -> None:
    check(split_in_half(case["text"]), case["out"], "splitInHalf", text=case["text"])


@_cases("culpritHalfEdges")
def test_culprit_half_edges(case: Any) -> None:
    args = (case["typed"], case["left"], case["right"])
    check(culprit_half(*args), case["lenient"], "culpritHalf", args=args)
    check(culprit_half(*args, True), case["strict"], "culpritHalf strict", args=args)


@_cases("parseDeck")
def test_parse_deck(case: Any) -> None:
    check(parse_deck(case["text"]), case["out"], "parseDeck", text=case["text"])


@_cases("normalizeItem")
def test_normalize_item(case: Any) -> None:
    it = copy.deepcopy(case["it"])
    check(normalize_item(it), case["out"], "normalizeItem(it)", it=case["it"])
    check(
        normalize_item(it, "cumulative"),
        case["out"],
        "normalizeItem(it, 'cumulative')",
        it=case["it"],
    )
    check(
        normalize_item(it, "exhaustive"),
        case["outExhaustive"],
        "normalizeItem(it, 'exhaustive')",
        it=case["it"],
    )
    assert it == case["it"], "normalizeItem must not mutate its input"


@_cases("partitionIntoBatches")
def test_partition_into_batches(case: Any) -> None:
    values = list(range(case["n"]))
    out = (
        partition_into_batches(values)
        if case["size"] is None
        else partition_into_batches(values, case["size"])
    )
    check(out, case["out"], "partitionIntoBatches", n=case["n"], size=case["size"])


_BUILD_KWARGS = {
    "chunkPercent": "chunk_percent",
    "ladderMode": "ladder_mode",
    "batchSize": "batch_size",
    "minWordsToChunk": "min_words_to_chunk",
    "shuffleWithinBatch": "shuffle_within_batch",
}


@_cases("buildItems")
def test_build_items_under_seed(case: Any) -> None:
    deck = GOLDEN["decks"][case["deck"]]
    kwargs = {_BUILD_KWARGS[k]: v for k, v in case["args"].items()}
    with rand.seeded(case["seed"]):
        out = build_items(deck, **kwargs)
        next_random = rand.random()
    check(out, case["out"], "buildItems", deck=case["deck"], args=case["args"], seed=case["seed"])
    # Same number of draws as TS: the next draw from the stream matches too.
    check(next_random, case["nextRandom"], "Math.random() after buildItems", seed=case["seed"])


@_cases("buildItem")
def test_build_item(case: Any) -> None:
    out = build_item(case["p"], case["id"], case["pct"], case["mode"], case["min"])
    check(out, case["out"], "buildItem", p=case["p"], id=case["id"], pct=case["pct"])


@_cases("shuffle")
def test_shuffle_under_seed(case: Any) -> None:
    with rand.seeded(case["seed"]):
        outs = [shuffle(a) for a in case["inputs"]]
        next_random = rand.random()
    check(outs, case["outs"], "shuffle", inputs=case["inputs"], seed=case["seed"])
    check(next_random, case["nextRandom"], "Math.random() after shuffle", seed=case["seed"])


@_cases("selectNextEncodeItem")
def test_select_next_encode_item(case: Any) -> None:
    batch = copy.deepcopy(case["batch"])
    picked = select_next_encode_item(batch, case["lastItemId"])
    # TS returns the batch's own object; record which one by identity.
    index = None if picked is None else next(i for i, b in enumerate(batch) if b is picked)
    check(
        index,
        case["out"],
        "selectNextEncodeItem",
        batch=case["batch"],
        last_item_id=case["lastItemId"],
    )


@_cases("slugify")
def test_slugify(case: Any) -> None:
    check(slugify(case["name"]), case["out"], "slugify", name=case["name"])


@_cases("resolveBatchConfig")
def test_resolve_batch_config(case: Any) -> None:
    built: list[Any] = [{} for _ in range(case["n"])]
    check(
        resolve_batch_config(case["saved"], built),
        case["out"],
        "resolveBatchConfig",
        saved=case["saved"],
        n=case["n"],
    )


@_cases("resolveSourceDeckEditable")
def test_resolve_source_deck_editable(case: Any) -> None:
    check(
        resolve_source_deck_editable(case["saved"]),
        case["out"],
        "resolveSourceDeckEditable",
        saved=case["saved"],
    )


def test_undefined_fields_stay_absent() -> None:
    """TS undefined -> absent key, never None (types.py's representation rule)."""
    no_extra, with_extra = build_items(
        [{"front": "f", "back": "b"}, {"front": "f", "back": "b", "extra": "x"}],
        shuffle_within_batch=False,
    )
    assert "extra" not in no_extra
    assert with_extra.get("extra") == "x"
    normalized = normalize_item({"id": 0, "front": "f", "back": "b"})
    for key in ("extra", "finalDone", "finalMisses", "attempts", "misses", "reveals", "nearMisses"):
        assert key not in normalized
    # TS null is kept as None.
    assert (
        normalize_item({"id": 0, "front": "f", "back": "b", "extra": None}).get("extra", "absent")
        is None
    )
