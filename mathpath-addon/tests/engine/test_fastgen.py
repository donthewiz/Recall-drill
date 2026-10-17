"""The quick exact pre-filter: it must never change which instance a seed gives."""

from __future__ import annotations

from fractions import Fraction

import pytest
from recipe_files import all_recipes, ch03, ids

from math_path import loader
from math_path.fastgen import Prefilter
from math_path.problem import draw_instance
from math_path.recipe import Recipe


def _values(env: dict[str, object]) -> dict[str, str]:
    return {k: str(v) for k, v in env.items()}


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_the_same_instance_as_the_checkers_own_for_every_seed(recipe: Recipe) -> None:
    instance = loader.load().validator.instance
    for seed in (2001, 2002, 2003, 2004):
        assert _values(draw_instance(recipe, seed)) == _values(instance(recipe.raw, seed))


def _rejects(lets: dict[str, str], constraints: list[str], **params: int) -> bool:
    pre = Prefilter.for_recipe(lets, constraints)
    return pre.rejects({k: Fraction(v) for k, v in params.items()})


def test_a_false_constraint_rejects_and_a_true_one_does_not() -> None:
    assert _rejects({}, ["a != b"], a=2, b=2)
    assert not _rejects({}, ["a != b"], a=2, b=3)
    assert _rejects({}, ["a < b"], a=3, b=2)
    assert not _rejects({}, ["a <= b"], a=3, b=3)
    assert _rejects({}, ["gcd(a, b) == 1"], a=4, b=6)


def test_let_values_juxtaposition_and_division() -> None:
    lets = {"S": "C (r1 + r2 - p)", "A": "(S - p)/(3 - p)"}
    assert _rejects(lets, ["A == floor(A)"], C=1, r1=3, r2=2, p=1)  # S = 4, A = 3/2
    assert not _rejects(lets, ["A == floor(A)"], C=1, r1=3, r2=3, p=1)  # S = 5, A = 2
    assert not _rejects({"d": "b^2 - 4 a c"}, ["d != 0"], a=1, b=3, c=1)
    assert _rejects({"d": "b^2 - 4 a c"}, ["d != 0"], a=1, b=2, c=1)
    assert _rejects({"t": "1/2 x"}, ["t == 3"], x=2)  # (1/2)*x, as SymPy reads it


def test_floor_of_a_square_root_is_exact_for_whole_numbers() -> None:
    c = ["floor(sqrt(abs(D)))^2 != abs(D)"]
    assert _rejects({}, c, D=16)  # a perfect square
    assert _rejects({}, c, D=-9)
    assert not _rejects({}, c, D=17)  # irrational root: not rejected here, nor wrongly accepted


def test_what_it_cannot_evaluate_is_never_rejected() -> None:
    assert not _rejects({"std": "expand((a x - p)(x - q))"}, ["std != 0"], a=1, p=2, q=3)
    assert not _rejects({}, ["a/b != 3"], a=1, b=0)  # division by zero: left to the checker
    assert not _rejects({}, ["sqrt(a) != 1"], a=2)  # irrational
    assert not _rejects({}, ["unknown_name > 3"], a=1)
    assert not _rejects({}, ["a > 1 or a < 0"], a=1)  # not a single comparison


def test_the_slow_recipe_is_now_fast() -> None:
    import time

    slow = next(r for r in ch03() if r.id == "ca.rateq.solve_quadratic")
    t0 = time.perf_counter()
    for seed in range(5000, 5006):
        draw_instance(slow, seed)
    assert (time.perf_counter() - t0) / 6 < 0.5
