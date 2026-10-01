"""Replays tests/golden/grading.json (recorded from src/utils/grading.ts)."""

from __future__ import annotations

import re
from typing import Any

import pytest
from engine_test_support import REPO_ROOT, case_ids, check, load_golden

from recalldrill.engine import grading
from recalldrill.engine.grading import compute_word_diff, exact_match, grade, norm

GOLDEN = load_golden("grading.json")
COMBOS: list[Any] = GOLDEN["gradeCombos"]
CASES: list[Any] = GOLDEN["cases"]


def _diff(case: Any, strict: bool) -> Any:
    word_diff = case["wordDiff"]
    if "both" in word_diff:
        return word_diff["both"]
    return word_diff["strict" if strict else "lenient"]


def test_golden_case_count() -> None:
    assert len(CASES) >= 1900
    assert [c["key"] for c in COMBOS][0] == "default"
    assert len(COMBOS) == 9


@pytest.mark.parametrize("case", CASES, ids=case_ids(CASES))
def test_grading_case(case: Any) -> None:
    typed: str = case["typed"]
    target: str = case["target"]

    check([norm(typed), norm(target)], case["norm"], "norm", typed=typed, target=target)
    check(
        exact_match(typed, target),
        case["exactMatch"]["lenient"],
        "exactMatch",
        typed=typed,
        target=target,
    )
    check(
        exact_match(typed, target, False),
        case["exactMatch"]["lenient"],
        "exactMatch strict=false",
        typed=typed,
        target=target,
    )
    check(
        exact_match(typed, target, True),
        case["exactMatch"]["strict"],
        "exactMatch strict=true",
        typed=typed,
        target=target,
    )
    check(
        compute_word_diff(typed, target),
        _diff(case, False),
        "computeWordDiff",
        typed=typed,
        target=target,
    )
    check(
        compute_word_diff(typed, target, True),
        _diff(case, True),
        "computeWordDiff strict=true",
        typed=typed,
        target=target,
    )

    for idx, combo in enumerate(COMBOS):
        opts = combo["opts"]
        if opts is None:
            actual = grade(typed, target)
            strict = False
        else:
            actual = grade(
                typed,
                target,
                lenient=opts["lenient"],
                stem_tolerance=opts["stemTolerance"],
                strict_punctuation=opts["strictPunctuation"],
            )
            strict = opts["strictPunctuation"]
        expected = {**case["gradeResults"][case["grade"][idx]], "diff": _diff(case, strict)}
        check(actual, expected, f"grade {combo['key']}", typed=typed, target=target)


def test_grade_none_options_mean_defaults() -> None:
    """TS `opts?.x ?? default`: an undefined option is the default."""
    typed, target = "wait for bus", "wait for the bus"
    assert grade(
        typed, target, lenient=None, stem_tolerance=None, strict_punctuation=None
    ) == grade(typed, target)


def test_markers_are_the_ts_code_points() -> None:
    """The private-use markers are byte-for-byte the ones in src/utils/grading.ts."""
    source = (REPO_ROOT / "src" / "utils" / "grading.ts").read_text(encoding="utf-8")
    decimal = re.search(r"const DECIMAL_MARKER = '(.)';", source)
    negative = re.search(r"const NEGATIVE_MARKER = '(.)';", source)
    assert decimal is not None and negative is not None
    assert grading.DECIMAL_MARKER == decimal.group(1) == chr(0xE000)
    assert grading.NEGATIVE_MARKER == negative.group(1) == chr(0xE001)


def test_stopwords_match_ts_source() -> None:
    source = (REPO_ROOT / "src" / "utils" / "grading.ts").read_text(encoding="utf-8")
    block = re.search(r"const STOPWORDS = new Set\(\[(.*?)\]\);", source, re.DOTALL)
    assert block is not None
    assert grading.STOPWORDS == frozenset(re.findall(r"'([a-z]+)'", block.group(1)))
