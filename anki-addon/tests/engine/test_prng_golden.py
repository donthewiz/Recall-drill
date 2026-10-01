"""Replays tests/golden/prng.json (recorded from test/prng.ts) and checks the
shared random stream in recalldrill.engine.rand."""

from __future__ import annotations

import random
from typing import Any

import pytest
from engine_test_support import check, load_golden

from recalldrill.engine import rand
from recalldrill.engine.rand import hash_seed, mulberry32

GOLDEN = load_golden("prng.json")
HASHES: list[Any] = GOLDEN["hashSeed"]
STREAMS: list[Any] = GOLDEN["mulberry32"]


@pytest.mark.parametrize("case", HASHES, ids=[f"{i:02d}" for i in range(len(HASHES))])
def test_hash_seed(case: Any) -> None:
    check(hash_seed(case["label"]), case["value"], "hashSeed", label=case["label"])


@pytest.mark.parametrize("stream", STREAMS, ids=[str(s["seed"]) for s in STREAMS])
def test_mulberry32_stream(stream: Any) -> None:
    next_float = mulberry32(stream["seed"])
    outputs = [next_float() for _ in range(len(stream["outputs"]))]
    for i, (actual, expected) in enumerate(zip(outputs, stream["outputs"], strict=True)):
        check(actual, expected, f"mulberry32 output #{i}", seed=stream["seed"])


def test_first_1000_outputs_for_the_harness_seed() -> None:
    """The harness's own label: current:shortDeck:realistic."""
    seed = hash_seed("current:shortDeck:realistic")
    stream = next(s for s in STREAMS if s["seed"] == seed)
    next_float = mulberry32(seed)
    assert len(stream["outputs"]) == 1000
    assert [next_float() for _ in range(1000)] == stream["outputs"]


def test_hash_seed_walks_utf16_code_units() -> None:
    # One astral character is two UTF-16 units in JS, one code point in Python.
    labels = {c["label"]: c["value"] for c in HASHES}
    assert chr(0x1F600) in labels
    assert hash_seed(chr(0x1F600)) == labels[chr(0x1F600)]
    assert hash_seed(chr(0x1F600)) != (31 * 0 + 0x1F600)


def test_seeded_draws_the_mulberry32_stream_then_restores() -> None:
    before = rand._source  # pyright: ignore[reportPrivateUsage]
    expected = mulberry32(42)
    with rand.seeded(42):
        assert [rand.random() for _ in range(5)] == [expected() for _ in range(5)]
    assert rand._source is before  # pyright: ignore[reportPrivateUsage]


def test_seeded_restores_on_error() -> None:
    before = rand._source  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(RuntimeError), rand.seeded(1):
        rand.random()
        raise RuntimeError("boom")
    assert rand._source is before  # pyright: ignore[reportPrivateUsage]


def test_seeded_nests() -> None:
    outer = mulberry32(1)
    inner = mulberry32(2)
    with rand.seeded(1):
        assert rand.random() == outer()
        with rand.seeded(2):
            assert rand.random() == inner()
        assert rand.random() == outer()


def test_default_source_is_unseeded_stdlib_random() -> None:
    assert rand._source is random.random  # pyright: ignore[reportPrivateUsage]
    assert 0 <= rand.random() < 1


def test_seed_wraps_to_32_bits() -> None:
    """mulberry32 does `seed >>> 0`."""
    a = mulberry32(2**32 + 41)
    b = mulberry32(41)
    assert [a() for _ in range(3)] == [b() for _ in range(3)]
