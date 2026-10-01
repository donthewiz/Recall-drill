"""The golden data stays small enough to keep in the repo: under 8 MB in total."""

from __future__ import annotations

from engine_test_support import GOLDEN_DIR

BUDGET_BYTES = 8_000_000


def test_golden_files_fit_the_budget() -> None:
    total = sum(p.stat().st_size for p in GOLDEN_DIR.glob("*.json"))
    assert total < BUDGET_BYTES, f"tests/golden/*.json is {total:,} bytes"
