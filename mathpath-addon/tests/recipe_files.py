"""The fixture recipes, loaded once per test run."""

from __future__ import annotations

from functools import cache
from pathlib import Path

from math_path.recipe import Recipe, loads_recipe

FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recipes"
CH03 = FIXTURES / "ch03"
V2 = FIXTURES / "v2_examples"


@cache
def load(path: Path) -> Recipe:
    return loads_recipe(path.read_text(encoding="utf-8"))


def ch03() -> list[Recipe]:
    return [load(p) for p in sorted(CH03.glob("*.json"))]


def v2() -> list[Recipe]:
    return [load(p) for p in sorted(V2.glob("*.json"))]


def all_recipes() -> list[Recipe]:
    return ch03() + v2()


def ids(recipes: list[Recipe]) -> list[str]:
    return [r.id for r in recipes]
