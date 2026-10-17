"""Typed steps (the Faded stage): the checker's own step check, with the learner's text."""

from __future__ import annotations

import time

import pytest
from drive import tex_of
from problems_cache import problems
from recipe_files import all_recipes, ch03, ids

from math_path import grading
from math_path.recipe import Recipe

INDISTINGUISHABLE = frozenset({"rejects"})
"""Checks that pass for any value that also fails the equation: another instance's rejected root
fails this one too, so "a different value fails" cannot hold for them."""


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_each_worked_result_passes_and_another_instances_result_fails(recipe: Recipe) -> None:
    probs = problems(recipe, 5)
    for k, problem in enumerate(probs):
        other = probs[(k + 1) % len(probs)]
        for step in problem.steps:
            if not step.blankable:
                continue
            assert grading.check_step_keyboard(problem, step.index, step.result).ok, (
                recipe.id,
                problem.seed,
                step.name,
            )
            raw = recipe.steps[step.index].raw
            wrong = other.steps[step.index].result
            comparable = (
                step.check not in INDISTINGUISHABLE
                and not raw.get("may_add")
                and problem.key != other.key
                and wrong != step.result
            )
            if comparable:
                assert not grading.check_step_keyboard(problem, step.index, wrong).ok, (
                    recipe.id,
                    problem.seed,
                    step.name,
                    wrong,
                )


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_every_worked_result_also_passes_typed_through_the_palette(recipe: Recipe) -> None:
    """Each blank step's worked result, as the palette would hold it, read back by the adapter."""
    for problem in problems(recipe, 5):
        for step in problem.steps:
            if step.blankable:
                verdict = grading.check_step_typed(problem, step.index, tex_of(step.result))
                assert verdict.ok, (recipe.id, problem.seed, step.name, step.result)


def test_a_brace_in_the_answer_is_never_read_as_a_template() -> None:
    recipe = next(r for r in ch03() if r.id == "ca.quad.solve_factoring")
    problem = problems(recipe, 1)[0]
    index = recipe.blank_steps[0]
    assert not grading.check_step_keyboard(problem, index, "{x} = 0").ok  # no KeyError
    assert not grading.check_step_keyboard(problem, index, "{p}").ok


def test_text_and_substitution_steps_are_never_blanked() -> None:
    for recipe in all_recipes():
        for step in recipe.steps:
            if step.check in ("text", "substitution") or not step.result.strip():
                assert not step.blankable, (recipe.id, step.name)


def test_a_step_check_is_quick() -> None:
    slowest = 0.0
    for recipe in ch03():
        problem = problems(recipe, 1)[0]
        for step in problem.steps:
            if step.blankable:
                t0 = time.perf_counter()
                grading.check_step_keyboard(problem, step.index, step.result)
                slowest = max(slowest, time.perf_counter() - t0)
    assert slowest < 1.0, slowest
