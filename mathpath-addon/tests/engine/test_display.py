"""Math is shown as MathJax: prompts, steps and answers over all the fixture recipes."""

from __future__ import annotations

import re

import pytest
from problems_cache import problems
from recipe_files import all_recipes, ids

from math_path.display import kb_html, kb_math_html, tex_of_keyboard
from math_path.recipe import Recipe


def _balanced(html: str) -> bool:
    return html.count("\\(") == html.count("\\)")


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_every_prompt_step_and_answer_is_typeset(recipe: Recipe) -> None:
    for problem in problems(recipe, 6):
        assert _balanced(problem.prompt_html)
        assert "{" not in re.sub(r"\\\(.*?\\\)", "", problem.prompt_html), problem.prompt_html
        assert "{tex:" not in problem.prompt_html
        assert "\\(" in problem.prompt_html or recipe.id == "ca.rat.no_solution"
        for step in problem.steps:
            assert _balanced(step.shown_html)
            assert "\ue200" not in step.shown_html
        assert _balanced(problem.answer_html)
        assert "mp-raw" not in problem.answer_html, (
            problem.answer_html
        )  # answers always read as math


def test_a_prompt_mixes_prose_and_math() -> None:
    from recipe_files import CH03, load

    p = problems(load(CH03 / "ca.abs.solve_ineq_greater_eq.json"), 1)[0]
    assert p.prompt_html.startswith("Solve and write the solution set in interval notation: \\(")
    assert "\\ge" in p.prompt_html and p.prompt_html.count("\\(") == 1  # one island, not three


def test_units_squared_stay_prose_and_numbers_become_math() -> None:
    from recipe_files import CH03, load

    p = problems(load(CH03 / "ca.quad.rectangle_dimensions.json"), 1)[0]
    assert "ft<sup>2</sup>" in p.prompt_html
    assert re.search(r"perimeter \\\(\d+\\\) ft and area \\\(\d+\\\) ft", p.prompt_html)


def test_keyboard_text_with_prose_around_it() -> None:
    html = kb_html("Let u = x^2: u^2 + 3 u + 2 = 0")
    assert html.startswith("Let \\(u = x^{2}\\): \\(u^{2}")
    assert kb_html("x = 3: f(3) = 4, click (3, 4)").count("\\(") == 3
    assert "mp-raw" not in kb_html("the maximum value is (-6) (when x = 4)")
    assert "\\(-6\\)" in kb_html("the maximum value is (-6) (when x = 4)")


def test_text_that_is_not_math_is_never_lost_or_broken() -> None:
    assert kb_html("choose the parabola tool") == "choose the parabola tool"
    assert kb_html("a < b <") == kb_html("a < b <")  # does not raise
    assert "&lt;" in kb_html("x < ")  # escaped, not interpreted as a tag


def test_answers_in_course_notation() -> None:
    assert kb_math_html("(-inf, -2) U (3, inf)").startswith("\\(\\left( -\\infty")
    assert tex_of_keyboard("x = 1; x = -2") is not None
    assert tex_of_keyboard("1 8 sqrt(7)") is None  # the drill's reader can't take it: shown as text
    assert "mp-raw" in kb_math_html("1 8 sqrt(7)")
