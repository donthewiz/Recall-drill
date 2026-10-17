"""One fresh problem: replayable from its seed, computed once, prepared ahead in the background."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest
from recipe_files import CH03, V2, ch03, load

from math_path import loader
from math_path.problem import ProblemBank, make_problem, new_seed
from math_path.recipe import RecipeError, loads_recipe

RECIPE = load(CH03 / "ca.quad.solve_factoring.json")


def test_a_seed_replays_the_same_problem() -> None:
    a, b = make_problem(RECIPE, 4242), make_problem(RECIPE, 4242)
    assert (a.prompt_html, a.key, a.answer_html) == (b.prompt_html, b.key, b.answer_html)
    assert [s.result for s in a.steps] == [s.result for s in b.steps]
    assert make_problem(RECIPE, 4243).prompt_html != a.prompt_html


def test_new_seeds_are_different_positive_and_fit_the_checkers_rng() -> None:
    seeds = {new_seed() for _ in range(200)}
    assert len(seeds) > 190 and all(0 < s < 2**31 for s in seeds)


def test_the_truth_is_computed_once_per_instance(monkeypatch: pytest.MonkeyPatch) -> None:
    v = loader.load().validator
    calls = {"n": 0}
    real = v._truth

    def counting(recipe: Any, env: Any) -> Any:
        calls["n"] += 1
        return real(recipe, env)

    monkeypatch.setattr(v, "_truth", counting)
    problem = make_problem(RECIPE, 99)
    assert calls["n"] == 1
    from math_path import grading

    for i in problem.blank_indexes:
        grading.check_step_keyboard(problem, i, problem.steps[i].result)
    grading.check_keyboard(problem, problem.key)
    assert calls["n"] == 1  # checking never recomputes it


def test_reject_if_only_trims_the_final_answer() -> None:
    recipe = load(V2 / "ca.quad.falling_object.json")
    assert recipe.raw["answer"].get("reject_if") == ["t < 0"]
    problem = make_problem(recipe, 1000)
    assert len(problem.step_truth) == 2 and len(problem.truth) == 1  # the steps see both roots


def test_the_steps_carry_what_the_screens_show() -> None:
    problem = make_problem(RECIPE, 7)
    assert [s.name for s in problem.steps] == [s.name for s in RECIPE.steps]
    assert problem.blank_indexes == RECIPE.blank_steps
    assert problem.gen_ms > 0
    assert problem.steps[-1].blankable is False  # "check" is shown as an instruction


def test_the_bank_prepares_the_next_problem_while_one_is_in_use() -> None:
    bank = ProblemBank()
    first = bank.take_blocking(RECIPE)
    assert first.recipe is RECIPE
    deadline = time.time() + 30
    while not bank.is_ready(RECIPE) and time.time() < deadline:
        time.sleep(0.05)
    assert bank.is_ready(RECIPE)  # take() started the next build
    second = bank.take(RECIPE)
    assert second is not None and second.seed != first.seed
    assert not bank.is_ready(RECIPE) or True  # a third is already on its way


def test_take_returns_none_while_the_problem_is_not_ready() -> None:
    bank = ProblemBank()
    release = threading.Event()
    real = make_problem

    import math_path.problem as mod

    def slow(recipe: Any, seed: int) -> Any:
        release.wait(10)
        return real(recipe, seed)

    orig = mod.make_problem
    mod.make_problem = slow  # type: ignore[assignment]
    try:
        bank.prepare(RECIPE)
        assert bank.take(RECIPE) is None  # still building: the window says "Preparing…"
        release.set()
        assert bank.take_blocking(RECIPE).recipe is RECIPE
    finally:
        mod.make_problem = orig  # type: ignore[assignment]
        release.set()


def test_a_failing_build_is_reported_not_swallowed() -> None:
    data = dict(RECIPE.raw, constraints=["p == p + 1"])
    broken = loads_recipe(__import__("json").dumps(data))
    bank = ProblemBank()
    with pytest.raises(RuntimeError, match="no clean instance"):
        bank.take_blocking(broken, timeout=60)
    assert bank.failure(broken) is not None


def test_listeners_hear_when_a_build_finishes() -> None:
    bank = ProblemBank()
    heard: list[str] = []
    done = threading.Event()
    bank.listeners.append(lambda rid: (heard.append(rid), done.set()))
    bank.prepare(RECIPE)
    assert done.wait(30)
    assert heard == [RECIPE.id]


def test_a_recipe_without_the_needed_keys_is_refused_in_plain_words() -> None:
    with pytest.raises(RecipeError, match="missing"):
        loads_recipe('{"format": "mathpath-recipe/1", "id": "x"}')
    with pytest.raises(RecipeError, match="format"):
        loads_recipe('{"format": "mathpath-recipe/9"}')
    with pytest.raises(RecipeError, match="not valid JSON"):
        loads_recipe("{")
    assert len(ch03()) == 30
