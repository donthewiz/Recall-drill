"""Port of src/test/grade.spec.ts. One test per TS `it(...)`; the TS name is in each docstring."""

from __future__ import annotations

import pytest

from recalldrill.engine.grading import grade

# grade


def test_exact_match() -> None:
    """TS: grade > exact match"""
    r = grade("the cat sat on the mat", "the cat sat on the mat")
    assert r["verdict"] == "exact"
    assert r["similarity"] == 1


def test_stopword_only_omission_is_near() -> None:
    """TS: grade > stopword-only omission -> near"""
    r = grade("wait for bus", "wait for the bus")
    assert r["verdict"] == "near"
    assert r["missingWords"] == ["the"]
    assert r["extraWords"] == []


def test_stopword_only_insertion_is_near() -> None:
    """TS: grade > stopword-only insertion -> near"""
    r = grade("wait for the bus", "wait for bus")
    assert r["verdict"] == "near"
    assert r["missingWords"] == []
    assert r["extraWords"] == ["the"]


def test_plural_difference_in_long_answer_is_near() -> None:
    """TS: grade > plural difference in an otherwise-long answer -> near (stemTolerance on)"""
    target = "large green trees grow slowly near the quiet flowing rivers"
    typed = "large green trees grow slowly near the quiet flowing river"
    r = grade(typed, target)
    assert r["similarity"] >= 0.9
    assert r["verdict"] == "near"


def test_plural_difference_without_stem_tolerance_is_wrong() -> None:
    """TS: grade > plural difference -> wrong when stemTolerance is off"""
    target = "large green trees grow slowly near the quiet flowing rivers"
    typed = "large green trees grow slowly near the quiet flowing river"
    r = grade(typed, target, stem_tolerance=False)
    assert r["verdict"] == "wrong"


def test_one_content_word_wrong_is_wrong() -> None:
    """TS: grade > one content word wrong -> wrong"""
    target = "large green trees grow slowly near the quiet flowing rivers"
    typed = "large green trees grow slowly near the quiet flowing streams"
    r = grade(typed, target)
    assert r["verdict"] == "wrong"


def test_transposed_clause_is_wrong() -> None:
    """TS: grade > transposed clause -> wrong"""
    r = grade("energy makes cell the mitochondria", "the mitochondria makes cell energy")
    assert r["verdict"] == "wrong"


def test_empty_input_is_wrong() -> None:
    """TS: grade > empty input -> wrong"""
    r = grade("", "the mitochondria makes cell energy")
    assert r["verdict"] == "wrong"
    assert r["missingWords"] == ["the", "mitochondria", "makes", "cell", "energy"]


def test_lenient_false_is_wrong_for_any_non_exact_answer() -> None:
    """TS: grade > lenient: false always returns wrong for a non-exact answer, even a
    stopword-only diff"""
    r = grade("wait for bus", "wait for the bus", lenient=False)
    assert r["verdict"] == "wrong"


def test_wrong_short_answer_is_not_rescued() -> None:
    """TS: grade > a genuinely wrong short answer is not rescued by the near-miss tier"""
    r = grade("dog", "cat")
    assert r["verdict"] == "wrong"


# grade punctuation normalization

MENIERES = "M\N{LATIN SMALL LETTER E WITH ACUTE}ni\N{LATIN SMALL LETTER E WITH GRAVE}re's disease"

EXACT_PAIRS = [
    ("pre op", "pre-op"),
    ("and or", "and/or"),
    ("10 mg", "10mg"),
    ("Menieres disease", MENIERES),
    ("Na +", "Na+"),
    ("5 %", "5%"),
    ("itis", "-itis"),
    ("dont", "don't"),
    ("7.4", "7.4"),
    ("-5", "\N{MINUS SIGN}5"),
    ("- 5", "-5"),
    ("10 20", "10-20"),
    ("10 - 20", "10-20"),
    ("tachycardia fast heart rate", "tachycardia (fast heart rate)"),
]

WRONG_PAIRS = [
    ("74", "7.4"),
    ("60", "<60"),
    ("Na", "Na+"),
    ("5", "-5"),
    ("BE 2 to 2", "BE -2 to +2"),
    ("tachycardia", "tachycardia (fast heart rate)"),
]


@pytest.mark.parametrize(("typed", "target"), EXACT_PAIRS)
def test_punctuation_pair_is_exact(typed: str, target: str) -> None:
    """TS: grade punctuation normalization > "${typed}" vs "${target}" -> exact"""
    assert grade(typed, target)["verdict"] == "exact"


@pytest.mark.parametrize(("typed", "target"), WRONG_PAIRS)
def test_punctuation_pair_is_wrong(typed: str, target: str) -> None:
    """TS: grade punctuation normalization > "${typed}" vs "${target}" -> wrong"""
    assert grade(typed, target)["verdict"] == "wrong"
