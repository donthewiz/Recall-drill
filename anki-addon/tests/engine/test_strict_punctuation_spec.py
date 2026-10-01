"""Port of the grade() cases in src/test/strictPunctuation.spec.ts.

The applyAnswer cases are Phase 1b; the storage cases are N/A (see SPEC_MAP.md).
One test per TS `it(...)`; the TS name is in each docstring.
"""

from __future__ import annotations

import pytest

from recalldrill.engine.grading import grade

E_ACUTE = "\N{LATIN SMALL LETTER E WITH ACUTE}"
E_GRAVE = "\N{LATIN SMALL LETTER E WITH GRAVE}"
RSQUO = "\N{RIGHT SINGLE QUOTATION MARK}"
EM_DASH = "\N{EM DASH}"

RIGHT_PAIRS = [
    ("tachycardia fast heart rate", "tachycardia (fast heart rate)"),
    ("the fight or flight response", 'the "fight or flight" response'),
    ("normal range 7.35-7.45", "normal range: 7.35-7.45"),
    ("heart lungs kidneys", "heart, lungs, kidneys"),
    ("the end", "The end."),
    ("dont", "don" + RSQUO + "t"),
    ("pre-op", "pre" + EM_DASH + "op"),
    ("Menieres disease", "M" + E_ACUTE + "ni" + E_GRAVE + "re" + RSQUO + "s disease"),
    ("Meni" + E_GRAVE + "re", "Meni" + E_GRAVE + "re"),
]

WRONG_PAIRS = [
    ("tachycardia", "tachycardia (fast heart rate)"),
    ("inflammation of stomach", "inflammation of the stomach"),
    ("inflammation of the joint", "inflammation of the joints"),
    ("pre op", "pre-op"),
    ("and or", "and/or"),
    ("74", "7.4"),
    ("Na", "Na+"),
    ("5", "-5"),
]

PHASE1_EXACT_PAIRS = [
    ("pre op", "pre-op"),
    ("and or", "and/or"),
    ("10 mg", "10mg"),
    ("Na +", "Na+"),
    ("5 %", "5%"),
    ("itis", "-itis"),
    ("dont", "don't"),
    ("tachycardia fast heart rate", "tachycardia (fast heart rate)"),
]

PHASE1_WRONG_PAIRS = [
    ("74", "7.4"),
    ("Na", "Na+"),
    ("5", "-5"),
]


@pytest.mark.parametrize(("typed", "target"), RIGHT_PAIRS)
def test_strict_pair_is_exact(typed: str, target: str) -> None:
    """TS: grade() strict punctuation mode > strict: "${typed}" vs "${target}" -> exact"""
    assert grade(typed, target, strict_punctuation=True)["verdict"] == "exact"


@pytest.mark.parametrize(("typed", "target"), WRONG_PAIRS)
def test_strict_pair_is_wrong(typed: str, target: str) -> None:
    """TS: grade() strict punctuation mode > strict: "${typed}" vs "${target}" -> wrong"""
    assert grade(typed, target, strict_punctuation=True)["verdict"] == "wrong"


@pytest.mark.parametrize(("typed", "target"), PHASE1_EXACT_PAIRS)
def test_strict_off_pair_is_exact(typed: str, target: str) -> None:
    """TS: grade() strict punctuation mode > strict off: "${typed}" vs "${target}" -> exact
    (unchanged from Phase 1)"""
    assert grade(typed, target, strict_punctuation=False)["verdict"] == "exact"


@pytest.mark.parametrize(("typed", "target"), PHASE1_WRONG_PAIRS)
def test_strict_off_pair_is_wrong(typed: str, target: str) -> None:
    """TS: grade() strict punctuation mode > strict off: "${typed}" vs "${target}" -> wrong
    (unchanged from Phase 1)"""
    assert grade(typed, target, strict_punctuation=False)["verdict"] == "wrong"
