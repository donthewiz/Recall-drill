"""Port of src/test/chunkText.spec.ts.

One test per TS `it(...)`; the TS name is in each docstring.
"""

from __future__ import annotations

from recalldrill.engine.items import MIN_WORDS_TO_CHUNK, chunk_text


def words(n: int) -> str:
    return " ".join(f"word{i}" for i in range(n))


def test_min_words_to_chunk_is_8() -> None:
    """TS: MIN_WORDS_TO_CHUNK > is 8"""
    assert MIN_WORDS_TO_CHUNK == 8


def test_short_back_never_chunks() -> None:
    """TS: MIN_WORDS_TO_CHUNK > a back at or under MIN_WORDS_TO_CHUNK never chunks,
    regardless of chunkDifficulty"""
    for n in (1, 3, 8):
        for pct in (15, 35, 50, 90):
            assert chunk_text(words(n), pct) is None


def test_one_word_over_can_chunk() -> None:
    """TS: MIN_WORDS_TO_CHUNK > a back one word over MIN_WORDS_TO_CHUNK can chunk
    (chunkDifficulty permitting)"""
    assert chunk_text(words(9), 50) is not None
