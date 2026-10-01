"""The engine's one shared random stream: the port of ``Math.random``.

The TS engine draws every random number from the global ``Math.random``, and
its harness swaps that for a seeded mulberry32 (``withSeededRandom`` in
``test/prng.ts``). The Python engine mirrors it: every place the TS code calls
``Math.random()``, the Python code calls :func:`random` at the same point and in
the same order. Inside :func:`seeded` the draws are then identical to the TS
engine's under ``withSeededRandom`` with the same seed.

The module-level source is the one global state the engine is allowed.
"""

from __future__ import annotations

import random as _stdlib_random
from collections.abc import Callable, Generator
from contextlib import contextmanager

from .jscompat import i32, imul, u32, utf16_units

_source: Callable[[], float] = _stdlib_random.random


def random() -> float:
    """A float in [0, 1) from the current source (``Math.random()``)."""
    return _source()


def hash_seed(label: str) -> int:
    """Port of ``hashSeed``: a stable 32-bit seed from a label (over UTF-16 code units)."""
    h = 0
    for unit in utf16_units(label):
        h = i32(imul(31, h) + unit)
    return u32(h)


def mulberry32(seed: int) -> Callable[[], float]:
    """Port of ``mulberry32``: a seeded generator with ``Math.random``'s contract."""
    a = u32(seed)

    def next_float() -> float:
        nonlocal a
        a = i32(a + 0x6D2B79F5)
        t = imul(a ^ (u32(a) >> 15), 1 | a)
        t = i32(t + imul(t ^ (u32(t) >> 7), 61 | t)) ^ t
        return u32(t ^ (u32(t) >> 14)) / 4294967296

    return next_float


@contextmanager
def seeded(seed: int) -> Generator[None]:
    """Port of ``withSeededRandom``: draw from ``mulberry32(seed)`` inside the block.

    The previous source comes back on exit, even if the block raises.
    """
    global _source
    original = _source
    _source = mulberry32(seed)
    try:
        yield
    finally:
        _source = original
