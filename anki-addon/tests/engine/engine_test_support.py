"""Shared helpers for the engine parity tests.

- Golden data loading and a JSON-value comparison (bool is not a number,
  int 1 equals float 1.0, tuple equals list) that fails with the input and
  both outputs.
- Python copies of the TS spec fixtures in ``src/test/fixtures/deck.ts``.
"""

from __future__ import annotations

import json
from functools import cache
from pathlib import Path
from typing import Any

import pytest

ADDON_ROOT = Path(__file__).resolve().parents[2]
REPO_ROOT = ADDON_ROOT.parent
GOLDEN_DIR = ADDON_ROOT / "tests" / "golden"
ENGINE_DIR = ADDON_ROOT / "recalldrill" / "engine"


@cache
def load_golden(name: str) -> Any:
    return json.loads((GOLDEN_DIR / name).read_text(encoding="utf-8"))


def same_json(a: Any, b: Any) -> bool:
    """Whether two values are the same JSON value (JS has one number type)."""
    if isinstance(a, bool) or isinstance(b, bool):
        return type(a) is type(b) and a == b
    if isinstance(a, int | float) and isinstance(b, int | float):
        return a == b
    if isinstance(a, list | tuple) and isinstance(b, list | tuple):
        return len(a) == len(b) and all(same_json(x, y) for x, y in zip(a, b, strict=True))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(same_json(a[k], b[k]) for k in a)
    return type(a) is type(b) and a == b


def check(actual: Any, expected: Any, what: str, **inputs: Any) -> None:
    """Fails with the input and both outputs unless they're the same JSON value."""
    if not same_json(actual, expected):
        lines = [f"{what}: Python != TS"]
        lines += [f"  input {name} = {value!r}" for name, value in inputs.items()]
        lines += [f"  TS:     {expected!r}", f"  Python: {actual!r}"]
        pytest.fail("\n".join(lines), pytrace=False)


def case_ids(cases: list[Any]) -> list[str]:
    return [f"{i:04d}" for i in range(len(cases))]


# src/test/fixtures/deck.ts
CHUNK_DIFFICULTY = 20
TWO_CHUNK_DIFFICULTY = 50
FULL_STAGE_BACK = "cats sleep often"
TWO_CHUNK_BACK = "the mitochondria produces most of the cells energy supply"
TWO_CHUNK_CHUNKS = ["the mitochondria produces most of", "the cells energy supply"]
FOUR_CHUNK_BACK = "large green trees grow slowly near the quiet river"
FOUR_CHUNK_CHUNKS = ["large green", "trees grow", "slowly near", "the quiet river"]
