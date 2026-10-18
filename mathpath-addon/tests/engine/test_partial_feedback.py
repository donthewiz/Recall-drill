"""Partial-answer feedback on list answers (2026-10-18): the headline says how many of the typed
pieces are right, never which, and never changes ok / not ok or whether it counts as a try."""

from __future__ import annotations

import dataclasses
import re

import pytest
from drive import key_text, tex_of
from problems_cache import problems
from recipe_files import CH03, all_recipes, ids, load

from math_path import grading
from math_path.problem import Problem
from math_path.recipe import Recipe

LISTS = [r for r in all_recipes() if r.kind == "list" and r.task == "solve"]
WRONG = "987654321"


def _pieces(problem: Problem) -> list[str]:
    out: list[str] = []
    for piece in grading._top_split(key_text(problem)):  # pyright: ignore[reportPrivateUsage]
        piece = piece.strip()
        if piece.startswith("+-"):
            body = piece[2:].strip()
            out += [body, f"-({body})"]
        elif "+-" in piece:
            out += [piece.replace("+-", "+", 1), piece.replace("+-", "-", 1)]
        else:
            out.append(piece)
    return out


def _grade(problem: Problem, typed: str, palette: bool) -> grading.AnswerVerdict:
    if palette:
        return grading.check_typed(problem, tex_of(typed))
    return grading.check_keyboard(problem, typed)


def _multi(problem: Problem) -> bool:
    return len(problem.truth) >= 2


@pytest.mark.parametrize("palette", [False, True], ids=["keyboard", "palette"])
@pytest.mark.parametrize("recipe", LISTS, ids=ids(LISTS))
def test_partial_feedback_on_every_list_recipe(recipe: Recipe, palette: bool) -> None:
    for problem in problems(recipe, 4):
        pieces = _pieces(problem)
        total = len(problem.truth)
        wrongly = _grade(problem, WRONG, palette)
        assert not wrongly.ok and wrongly.headline == "Not right yet."
        if total < 2:
            right = _grade(problem, ", ".join(pieces), palette)
            assert right.ok and not right.partial
            continue
        # one right piece and nothing else
        one = _grade(problem, pieces[0], palette)
        assert not one.ok and not one.value_ok and one.counts_as_try
        assert one.headline == (
            f"Not right yet: you have 1 of {total} solutions; "
            + ("there is another." if total == 2 else f"there are {total - 1} more.")
        ), (recipe.id, problem.seed)
        # one right piece and one wrong piece
        mixed = _grade(problem, f"{pieces[0]}, {WRONG}", palette)
        assert not mixed.ok and mixed.counts_as_try
        assert mixed.headline == "Not right yet: 1 of your 2 values is right.", (
            recipe.id,
            problem.seed,
        )
        # the verdict is the same as without the words
        assert dataclasses.replace(mixed, partial="").headline == "Not right yet."
        # the whole answer is still right
        assert _grade(problem, ", ".join(pieces), palette).ok


def test_the_labelled_form_gets_the_same_words() -> None:
    recipe = load(CH03 / "ca.quad.solve_factoring.json")
    for problem in problems(recipe, 4):
        first = _pieces(problem)[0]
        v = grading.check_keyboard(problem, f"x = {first}")
        assert v.headline == "Not right yet: you have 1 of 2 solutions; there is another."


def test_three_values_one_right_two_wrong_uses_the_plural() -> None:
    recipe = load(CH03 / "ca.quad.solve_factoring.json")
    problem = problems(recipe, 1)[0]
    first = _pieces(problem)[0]
    v = grading.check_keyboard(problem, f"{first}, {WRONG}, 123456789")
    assert v.headline == "Not right yet: 1 of your 3 values is right."
    assert re.search(r"\d of your \d values are right", "2 of your 3 values are right")


def test_a_wholly_wrong_list_and_a_right_value_in_the_wrong_form_are_unchanged() -> None:
    recipe = load(CH03 / "ca.quad.solve_factoring.json")
    problem = problems(recipe, 1)[0]
    assert grading.check_keyboard(problem, f"{WRONG}, 123456789").headline == "Not right yet."
    # a right value with a form problem keeps its own headline
    recipe = load(CH03 / "ca.quad.solve_formula.json")
    for p in problems(recipe, 8):
        v = grading.check_keyboard(p, ", ".join(_pieces(p)))
        if v.ok:
            assert v.headline == "Right." and not v.partial
