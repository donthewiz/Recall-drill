"""The Plan stage's matching rule."""

from __future__ import annotations

import pytest
from recipe_files import all_recipes

from math_path.plan_match import damerau_levenshtein, matches, normalize, tolerance


@pytest.mark.parametrize(
    ("a", "b", "d"),
    [
        ("", "", 0),
        ("abc", "", 3),
        ("", "abc", 3),
        ("kitten", "sitting", 3),
        ("ab", "ba", 1),  # one swap of neighbours
        ("ca", "abc", 2),  # swap, then insert: the restricted (OSA) distance would be 3
        ("abcdef", "abcfed", 2),
        ("factor", "factro", 1),
        ("same", "same", 0),
    ],
)
def test_damerau_levenshtein(a: str, b: str, d: int) -> None:
    assert damerau_levenshtein(a, b) == d == damerau_levenshtein(b, a)


def test_normalize_lowercases_drops_punctuation_and_the_three_words() -> None:
    assert normalize("Write it in STANDARD form (= 0)") == "write it in standard form 0"
    assert normalize("Set  each factor equal to 0.") == "set each factor equal to 0"
    assert normalize("find the x-coordinate of a vertex") == "find x coordinate of vertex"
    assert normalize("the A An the") == ""
    assert normalize("don't") == "dont" and normalize("don’t") == "dont"


def test_equal_after_normalising_is_right() -> None:
    assert matches("write it in standard form", "Write it in the standard form (= 0)")
    assert matches("  FACTOR ", "factor")
    assert not matches("", "factor")
    assert not matches("factor", "")


@pytest.mark.parametrize(
    ("name", "tol"),
    [("factor", 1), ("set each factor equal to 0", 3), ("a b", 1), ("x" * 40, 5)],
)
def test_the_tolerance_is_a_eighth_of_the_name_and_at_least_one(name: str, tol: int) -> None:
    assert tolerance(name) == tol


def test_a_typo_or_two_is_near_enough_but_a_different_step_is_not() -> None:
    name = "substitute into the quadratic formula"  # normalised 33 characters: 4 edits allowed
    assert matches("substitue into the quadratic formula", name)
    assert matches("substitute into quadratic fromula", name)
    assert not matches("simplify the discriminant", name)
    assert not matches("factor", "solve each equation")
    assert matches("facotr", "factor")  # one swap on a 6-letter name: 1 edit allowed
    assert not matches("fcator", "solve")  # unrelated


def test_every_recipes_steps_match_themselves_and_not_their_neighbours() -> None:
    for recipe in all_recipes():
        names = [s.name for s in recipe.steps]
        for i, name in enumerate(names):
            assert matches(name, name)
            for j, other in enumerate(names):
                if i != j and normalize(name) != normalize(other):
                    assert not matches(other, name), (recipe.id, name, other)
