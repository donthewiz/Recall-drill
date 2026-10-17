"""A problem must appear in under 1.5 s: generation plus truth, every Chapter 3 recipe."""

from __future__ import annotations

import statistics
import time

from recipe_files import ch03

from math_path import loader
from math_path.problem import make_problem

BUDGET_MS = 1500.0
SEEDS = tuple(range(7000, 7010))


def test_generation_plus_truth_for_every_chapter_3_recipe_is_under_the_budget(
    capsys: object,
) -> None:
    loader.load()
    rows: list[tuple[float, float, str]] = []
    for recipe in ch03():
        times = [make_problem(recipe, seed).gen_ms for seed in SEEDS]
        rows.append((max(times), statistics.median(times), recipe.id))
    rows.sort(reverse=True)
    slowest = rows[0]
    print(
        f"\nslowest: {slowest[2]} max {slowest[0]:.0f} ms, median {slowest[1]:.0f} ms; "
        f"all {len(rows)} recipes: max of maxes {slowest[0]:.0f} ms"
    )
    assert slowest[0] < BUDGET_MS, rows[:3]


def test_the_import_is_off_the_hot_path_and_quick() -> None:
    t0 = time.perf_counter()
    loader.load()  # already loaded by the test above in a full run: a no-op then
    assert time.perf_counter() - t0 < 5.0
