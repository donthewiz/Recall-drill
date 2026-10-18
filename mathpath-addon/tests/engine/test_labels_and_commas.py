"""Two ways people write answers that are right (found in review, 2026-10-17).

- A list answer written with the variable: ``x = -5/2, x = -9`` (what MyMathLab and most
  worked solutions show) is the list ``-5/2, -9``.
- An "each" step written with commas between the equations: the palette has a comma button but no
  semicolon, so ``2x+5=0, x+9=0`` counts as ``2x+5=0; x+9=0``.
"""

from __future__ import annotations

import pytest
from drive import key_text, tex_of
from problems_cache import problems
from recipe_files import CH03, all_recipes, ids, load

from math_path import grading
from math_path.recipe import Recipe

LISTS = [r for r in all_recipes() if r.kind == "list" and r.task == "solve"]
EACH = [r for r in all_recipes() if any(s.check == "each" for s in r.steps)]
FACTORING = load(CH03 / "ca.quad.solve_factoring.json")


def _labelled(key: str, var: str) -> str:
    return ", ".join(f"{var} = {p.strip()}" for p in grading._top_split(key))  # pyright: ignore[reportPrivateUsage]


@pytest.mark.parametrize("recipe", LISTS, ids=ids(LISTS))
def test_a_list_answer_written_with_the_variable_is_right(recipe: Recipe) -> None:
    var = str(recipe.raw.get("var", "x"))
    for problem in problems(recipe, 5):
        key = key_text(problem)
        if "+-" in key:
            continue  # one item with both branches: "x = a +- b" is covered below
        typed = _labelled(key, var)
        assert grading.check_keyboard(problem, typed).ok, (recipe.id, problem.seed, typed)
        assert grading.check_typed(problem, tex_of(typed)).ok, (recipe.id, problem.seed, typed)


def test_a_plus_minus_answer_written_with_the_variable_is_right() -> None:
    recipe = load(CH03 / "ca.quad.solve_square_root.json")
    for problem in problems(recipe, 5):
        key = key_text(problem)
        assert grading.check_keyboard(problem, f"x = {key}").ok, (problem.seed, key)


@pytest.mark.parametrize("recipe", EACH, ids=ids(EACH))
def test_an_each_step_with_commas_is_right(recipe: Recipe) -> None:
    for problem in problems(recipe, 5):
        for step in problem.steps:
            if step.check != "each" or not step.blankable:
                continue
            with_commas = ", ".join(p.strip() for p in step.result.split(";"))
            assert grading.check_step_keyboard(problem, step.index, with_commas).ok, (
                recipe.id,
                problem.seed,
                with_commas,
            )
            typed = ",".join(tex_of(p.strip()) for p in step.result.split(";"))
            assert grading.check_step_typed(problem, step.index, typed).ok, (recipe.id, typed)


def test_labels_change_nothing_else() -> None:
    problem = problems(FACTORING, 1)[0]
    key = key_text(problem)
    first, second = (p.strip() for p in grading._top_split(key))  # pyright: ignore[reportPrivateUsage]
    # another letter, a half-labelled list, a relation: left as typed, so still wrong
    assert not grading.check_keyboard(problem, f"y = {first}, y = {second}").ok
    assert grading.drop_var_labels(f"x = {first}, {second}", "x") == f"x = {first}, {second}"
    assert grading.drop_var_labels("x < 3", "x") == "x < 3"
    assert grading.drop_var_labels("x = 2 = 3", "x") == "x = 2 = 3"
    # a wrong value with a label is still wrong, and an unreduced one still names the form
    assert not grading.check_keyboard(problem, "x = 987654321").ok
    assert grading.drop_var_labels("x = (6/8)", "x") == "(6/8)"
    # an interval's comma stays inside its piece
    assert grading.commas_between_equations("[1, 2)") == "[1, 2)"
    assert grading.commas_between_equations("x+1=0, x-2=0") == "x+1=0; x-2=0"
    assert grading.commas_between_equations("x+1=0, 3") == "x+1=0, 3"


@pytest.mark.parametrize("recipe", EACH, ids=ids(EACH))
def test_an_each_step_needs_one_equation_per_piece(recipe: Recipe) -> None:
    for problem in problems(recipe, 5):
        for step in problem.steps:
            if step.check != "each" or not step.blankable:
                continue
            pieces = [p.strip() for p in step.result.split(";")]
            if len(pieces) < 2:
                continue
            for typed in ("; ".join(pieces), ", ".join(pieces), "; ".join(reversed(pieces))):
                assert grading.check_step_keyboard(problem, step.index, typed).ok, typed
                assert grading.check_step_typed(problem, step.index, tex_of(typed)).ok, typed
            # retyping the equation the step starts from is not one equation per piece
            prev = problem.steps[step.index - 1].result if step.index else ""
            if prev and prev.count("=") == 1 and ";" not in prev:
                assert not grading.check_step_keyboard(problem, step.index, prev).ok, (
                    recipe.id,
                    prev,
                )
                assert not grading.check_step_typed(problem, step.index, tex_of(prev)).ok


def test_the_factored_equation_is_not_the_each_step() -> None:
    recipe = load(CH03 / "ca.quad.solve_factoring.json")
    each = next(i for i, s in enumerate(recipe.steps) if s.check == "each")
    problem = problems(recipe, 1)[0]
    step = problem.steps[each]
    factored = problem.steps[each - 1].result
    assert "(" in factored and not grading.check_step_keyboard(problem, each, factored).ok
    assert grading.check_step_keyboard(problem, each, step.result).ok
