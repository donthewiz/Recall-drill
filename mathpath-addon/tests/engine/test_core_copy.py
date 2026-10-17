"""The copied checker files are byte-identical to the plugin's (core/SOURCE.md lists the hashes)."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

import pytest

CORE = Path(__file__).resolve().parents[2] / "core"


def _table() -> dict[str, str]:
    text = (CORE / "SOURCE.md").read_text(encoding="utf-8")
    return dict(re.findall(r"^\| `([^`]+\.py)` \| `([0-9a-f]{64})` \|", text, re.MULTILINE))


def test_the_table_lists_six_files() -> None:
    assert sorted(_table()) == [
        "drill_check/__init__.py",
        "drill_check/math_answer.py",
        "drill_check/math_parse.py",
        "drill_check/math_vendor.py",
        "recipe_validator.py",
        "verify_math.py",
    ]


@pytest.mark.parametrize("name", sorted(_table()))
def test_sha256_equals_source_md(name: str) -> None:
    digest = hashlib.sha256((CORE / name).read_bytes()).hexdigest()
    assert digest == _table()[name], f"{name} was edited: copy it again from the plugin instead"


def test_no_other_python_file_is_in_core() -> None:
    found = sorted(p.relative_to(CORE).as_posix() for p in CORE.rglob("*.py"))
    assert found == sorted(_table())
