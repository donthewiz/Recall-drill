"""The i before the radical is display only: grading reads every form as before (2026-10-18)."""

from __future__ import annotations

from drive import tex_of
from recipe_files import CH03, load

from math_path import grading
from math_path.problem import Problem, make_problem


def _problem() -> Problem:
    recipe = load(CH03 / "ca.cx.express_i.json")
    for seed in range(1000, 1400):
        p = make_problem(recipe, seed)
        if p.env["k"] == 7 and p.env["m"] == 10:
            return p
    raise AssertionError("no 7*sqrt(10)*i instance")


def test_every_written_form_is_graded_as_before() -> None:
    p = _problem()
    for typed in ("7 sqrt(10) i", "7 i sqrt(10)", "7*sqrt(10)*i"):
        assert grading.check_keyboard(p, typed).ok, typed
        assert grading.check_typed(p, tex_of(typed)).ok, typed
    for typed in ("i sqrt(490)", "sqrt(490) i"):  # the right value, the radical not simplified
        for v in (grading.check_keyboard(p, typed), grading.check_typed(p, tex_of(typed))):
            assert v.value_ok and not v.ok, typed


def test_the_answer_is_shown_with_the_i_before_the_radical() -> None:
    p = _problem()
    assert "7 i \\sqrt{10}" in p.answer_html
    assert "\\sqrt{10} i" not in p.answer_html
