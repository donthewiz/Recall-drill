"""recalldrill.engine.jscompat against tests/golden/jscompat.json (JS built-ins
recorded under Node), plus the Python behavior each helper exists to avoid."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

import pytest
from engine_test_support import check, load_golden

from recalldrill.engine.jscompat import (
    JS_WS,
    JS_WS_CHARS,
    WS_RE,
    i32,
    imul,
    is_js_ws,
    js_iso_string,
    js_round,
    js_split_ws,
    js_sum,
    js_to_fixed,
    js_trim,
    truthy,
    u32,
    utf16_len,
    utf16_units,
)

GOLDEN = load_golden("jscompat.json")


def _ids(cases: list[Any]) -> list[str]:
    return [f"{i:03d}" for i in range(len(cases))]


@pytest.mark.parametrize("case", GOLDEN["mathRound"], ids=_ids(GOLDEN["mathRound"]))
def test_js_round_matches_math_round(case: Any) -> None:
    check(js_round(case["x"]), case["out"], "Math.round", x=case["x"])


@pytest.mark.parametrize("case", GOLDEN["whitespace"], ids=_ids(GOLDEN["whitespace"]))
def test_whitespace_helpers_match_js(case: Any) -> None:
    c = case["ch"]
    check(js_trim(c + "a" + c + "b" + c), case["trim"], "trim", ch=c)
    check(js_split_ws("a" + c + "b" + c + c + "c"), case["split"], "split(/\\s+/)", ch=c)
    check(js_split_ws(c + "a" + c), case["splitEdges"], "split(/\\s+/) at the ends", ch=c)
    check(is_js_ws(c), case["isWs"], "/\\s/.test", ch=c)
    check(bool(re.fullmatch(JS_WS, c)), case["isWs"], "JS_WS", ch=c)


@pytest.mark.parametrize("case", GOLDEN["toLowerCase"], ids=_ids(GOLDEN["toLowerCase"]))
def test_python_lower_matches_to_lower_case(case: Any) -> None:
    """No helper needed so far: str.lower() agreed with toLowerCase on every case."""
    check(case["s"].lower(), case["out"], "toLowerCase", s=case["s"])


@pytest.mark.parametrize("case", GOLDEN["nfkd"], ids=_ids(GOLDEN["nfkd"]))
def test_unicodedata_nfkd_matches_normalize(case: Any) -> None:
    """No helper needed so far: unicodedata agreed with String.normalize on every case."""
    check(unicodedata.normalize("NFKD", case["s"]), case["out"], "normalize('NFKD')", s=case["s"])


@pytest.mark.parametrize("case", GOLDEN["truthy"], ids=_ids(GOLDEN["truthy"]))
def test_truthy_matches_js(case: Any) -> None:
    check(truthy(case["value"]), case["out"], "!!value", value=case["value"])


def _number(x: Any) -> float:
    """A golden number; NaN, the infinities and -0 are written as strings."""
    return float(x) if isinstance(x, str) else x


@pytest.mark.parametrize("case", GOLDEN["toFixed"], ids=_ids(GOLDEN["toFixed"]))
def test_js_to_fixed_matches_to_fixed(case: Any) -> None:
    x = _number(case["x"])
    digits = (0, 1, 2) if isinstance(case["x"], str) else (0, 1, 2, 3, 20)
    check([js_to_fixed(x, d) for d in digits], case["digits"], "toFixed", x=case["x"])


@pytest.mark.parametrize("case", GOLDEN["toISOString"], ids=_ids(GOLDEN["toISOString"]))
def test_js_iso_string_matches_to_iso_string(case: Any) -> None:
    ms = _number(case["ms"])
    if case["out"] is None:
        assert case["error"] == "RangeError"
        with pytest.raises(ValueError, match="Invalid time value"):
            js_iso_string(ms)
    else:
        check(js_iso_string(ms), case["out"], "toISOString", ms=case["ms"])


@pytest.mark.parametrize("case", GOLDEN["length"], ids=_ids(GOLDEN["length"]))
def test_utf16_len_matches_length(case: Any) -> None:
    check(utf16_len(case["text"]), case["out"], ".length", text=case["text"])


@pytest.mark.parametrize("case", GOLDEN["reduceSum"], ids=_ids(GOLDEN["reduceSum"]))
def test_js_sum_matches_reduce(case: Any) -> None:
    check(js_sum(case["values"]), case["out"], "reduce((a, b) => a + b, 0)", values=case["values"])


# Why each helper exists: the Python built-in gives a different answer.


def test_python_format_rounds_ties_to_even() -> None:
    assert f"{0.25:.1f}" == "0.2" and js_to_fixed(0.25, 1) == "0.3"
    assert f"{-0.0:.1f}" == "-0.0" and js_to_fixed(-0.0, 1) == "0.0"
    assert js_to_fixed(-0.04, 1) == "-0.0"
    assert js_to_fixed(1e21, 1) == "1e+21"
    with pytest.raises(ValueError):
        js_to_fixed(1.0, 101)


def test_python_sum_is_compensated() -> None:
    """Python 3.12+ sums floats with compensation; JS reduce rounds at every step."""
    values = [0.1, 0.2, 0.3]
    assert sum(values) == 0.6
    assert js_sum(values) == 0.6000000000000001


def test_python_len_counts_code_points() -> None:
    face = chr(0x1F600)
    assert len(face) == 1 and utf16_len(face) == 2


def test_python_round_is_bankers_rounding() -> None:
    assert [round(x) for x in (0.5, 1.5, 2.5)] == [0, 2, 2]
    assert [js_round(x) for x in (0.5, 1.5, 2.5)] == [1, 2, 3]
    assert js_round(-0.5) == 0 and js_round(-1.5) == -1


def test_floor_plus_half_is_not_math_round() -> None:
    """The textbook floor(x + 0.5) rounds twice; JS Math.round doesn't."""
    import math

    x = 0.49999999999999994
    assert math.floor(x + 0.5) == 1
    assert js_round(x) == 0
    big = 2**52 + 1
    assert math.floor(big + 0.5) == big + 1
    assert js_round(float(big)) == big


def test_python_whitespace_differs_from_js() -> None:
    fs = chr(0x1C)
    nel = chr(0x85)
    bom = chr(0xFEFF)
    assert (fs + "a" + nel).strip() == "a"
    assert js_trim(fs + "a" + nel) == fs + "a" + nel
    assert (bom + "a").strip() == bom + "a"
    assert js_trim(bom + "a") == "a"
    assert ("a" + fs + "b").split() == ["a", "b"]
    assert js_split_ws("a" + fs + "b") == ["a" + fs + "b"]
    assert re.split(r"\s+", "a" + fs + "b") == ["a", "b"]
    assert WS_RE.split("a" + fs + "b") == ["a" + fs + "b"]


def test_js_split_keeps_edge_empties() -> None:
    assert js_split_ws(" a b ") == ["", "a", "b", ""]
    assert js_split_ws("") == [""]
    assert " a b ".split() == ["a", "b"]


def test_python_re_digit_is_unicode_wide() -> None:
    arabic_three = chr(0x663)
    assert re.fullmatch(r"\d", arabic_three)
    assert not re.fullmatch("[0-9]", arabic_three)


def test_python_dollar_matches_before_a_final_newline() -> None:
    assert re.search("a$", "a\n")
    assert not re.search("a\\Z", "a\n")


def test_ws_chars_are_exactly_the_ecmascript_set() -> None:
    expected = {0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0xA0, 0x1680, *range(0x2000, 0x200B)}
    expected |= {0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF}
    assert {ord(c) for c in JS_WS_CHARS} == expected
    assert len(JS_WS_CHARS) == len(expected)


def test_int32_helpers() -> None:
    assert i32(0xFFFFFFFF) == -1
    assert i32(0x80000000) == -(2**31)
    assert i32(2**32 + 5) == 5
    assert u32(-1) == 0xFFFFFFFF
    assert imul(0xFFFFFFFF, 5) == -5
    assert imul(0x7FFFFFFF, 2) == -2
    assert imul(3, 4) == 12
    assert imul(-3, 4) == -12


def test_utf16_units() -> None:
    assert list(utf16_units("a")) == [0x61]
    assert list(utf16_units(chr(0x1F600))) == [0xD83D, 0xDE00]
    assert list(utf16_units(chr(0xD800))) == [0xD800]  # a lone surrogate survives


def test_truthy_empty_containers_are_true_in_js() -> None:
    assert truthy([]) and truthy({})
    assert not truthy(float("nan"))
    assert not truthy(0.0) and not truthy(-0.0)
    assert not [] and not {}
