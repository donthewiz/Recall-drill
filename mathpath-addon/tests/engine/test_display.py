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


# -- no leading 1 coefficient, the i before the radical (2026-10-18) -----------------------------

_BARE_ONE = re.compile(r"(?<![\w.^/\-)}\]{])(?<!\d )1\s*(?=[A-Za-z(]|\\sqrt|\\left\()")
_RADICAL_THEN_I = re.compile(r"\\sqrt\{[^{}]*\}\s*i(?![A-Za-z])")


def _tex_spans(html: str) -> list[str]:
    return re.findall(r"\\\((.*?)\\\)", html)


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("1 sqrt(-1) sqrt(108)", "sqrt(-1)*sqrt(108)"),
        ("1 i sqrt(108)", "i sqrt(108)"),
        ("1*i sqrt(5)", "i sqrt(5)"),
        ("3 + 1 i", "3 + i"),
        ("1 (x+2)", "(x+2)"),
        ("1(x+2) + 1(x-1)", "(x+2) + (x-1)"),
        ("1/2 x", "1/2 x"),
        ("10 x", "10 x"),
        ("11 x", "11 x"),
        ("1.5 x", "1.5 x"),
        ("1^2 x", "1^2 x"),
        ("(1+x) y", "(1+x) y"),
        ("-1 i sqrt(3)", "-1 i sqrt(3)"),
        ("2 1 x", "2 1 x"),
    ],
)
def test_a_leading_one_is_dropped_only_when_it_is_a_multiplier(text: str, shown: str) -> None:
    from math_path.display import _tidy  # pyright: ignore[reportPrivateUsage]

    assert _tidy(text) == shown


@pytest.mark.parametrize(
    ("text", "shown"),
    [
        ("6 sqrt(3) i", "6 i sqrt(3)"),
        ("-sqrt(3) i", "-i sqrt(3)"),
        ("(6 + 2 sqrt(3) i)/4", "(6 + 2 i sqrt(3))/4"),
        ("i sqrt(490)", "i sqrt(490)"),
        ("7 i sqrt(10)", "7 i sqrt(10)"),
    ],
)
def test_the_i_is_shown_before_the_radical(text: str, shown: str) -> None:
    from math_path.display import _tidy  # pyright: ignore[reportPrivateUsage]

    assert _tidy(text) == shown
    assert "\\sqrt{" in kb_math_html(text)


def test_the_steps_and_answer_of_express_i_read_like_a_textbook() -> None:
    from recipe_files import CH03, load

    p = problems(load(CH03 / "ca.cx.express_i.json"), 1)[0]
    first, second, third = (s.shown_html for s in p.steps)
    assert "\\cdot" in first and not _BARE_ONE.search(first)
    assert "\\sqrt{-1}" in first and "i \\sqrt{" in second and "i \\sqrt{" in p.answer_html
    assert third == p.answer_html or "i \\sqrt{" in third


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_no_step_or_answer_starts_with_a_bare_one_or_puts_i_after_a_root(recipe: Recipe) -> None:
    for problem in problems(recipe, 8):
        shown = [s.shown_html for s in problem.steps] + [problem.answer_html]
        for html in shown:
            for tex in _tex_spans(html):
                assert not _BARE_ONE.search(tex), (recipe.id, tex)
                assert not _RADICAL_THEN_I.search(tex), (recipe.id, tex)
