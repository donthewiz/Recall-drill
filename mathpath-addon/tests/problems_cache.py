"""Problems built once per test run (the 30 Chapter 3 recipes x seeds 1000-1019 are shared)."""

from __future__ import annotations

from functools import cache

from math_path.problem import Problem, make_problem
from math_path.recipe import Recipe

SEEDS = tuple(range(1000, 1020))


@cache
def problems(recipe: Recipe, count: int = 20) -> tuple[Problem, ...]:
    return tuple(make_problem(recipe, seed) for seed in SEEDS[:count])
