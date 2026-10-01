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


_ABSENT = "<absent>"


def first_difference(expected: Any, actual: Any, path: str = "") -> tuple[str, Any, Any] | None:
    """The first place two JSON values differ: (path, TS value, Python value), or None.

    Dict keys are walked in sorted order; a key on one side only shows as
    ``<absent>`` on the other.
    """
    if isinstance(expected, dict) and isinstance(actual, dict):
        for key in sorted(set(expected) | set(actual)):
            sub = f"{path}.{key}" if path else str(key)
            if key not in actual:
                return sub, expected[key], _ABSENT
            if key not in expected:
                return sub, _ABSENT, actual[key]
            found = first_difference(expected[key], actual[key], sub)
            if found:
                return found
        return None
    if isinstance(expected, list | tuple) and isinstance(actual, list | tuple):
        for i, (e, a) in enumerate(zip(expected, actual, strict=False)):
            found = first_difference(e, a, f"{path}[{i}]")
            if found:
                return found
        if len(expected) != len(actual):
            return f"{path}.length", len(expected), len(actual)
        return None
    return None if same_json(expected, actual) else (path or "<root>", expected, actual)


def fail_on_difference(expected: Any, actual: Any, where: str) -> None:
    """Fails with the first differing key, as JSON, unless the values are equal."""
    found = first_difference(expected, actual)
    if found is None:
        return
    path, e, a = found
    pytest.fail(
        f"{where}: Python != TS at {path}\n"
        f"  TS:     {json.dumps(e, ensure_ascii=False)}\n"
        f"  Python: {json.dumps(a, ensure_ascii=False)}",
        pytrace=False,
    )
