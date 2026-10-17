"""The palette path: what the learner types, as MathLive would send it, graded.

Every right answer of every recipe (20 instances each: the checker's own seeds 1000-1019) is
turned into the LaTeX the palette would make, read back through the adapter and graded; every
named mistake's wrong answer and every ``form_violation`` example comes back the same way.
"""

from __future__ import annotations

from typing import Any

import pytest
from problems_cache import problems
from recipe_files import all_recipes, ch03, ids

from math_path import grading, loader
from math_path.palette import UnreadableAnswer, palette_to_keyboard
from math_path.problem import Problem
from math_path.recipe import Recipe

CH03 = ch03()


def _tex(text: str) -> str:
    """The LaTeX the palette would hold for keyboard ``text`` (Recall Drill's own writer)."""
    core = loader.load()
    try:
        return str(core.parse.to_latex(core.parse.parse(text)))
    except core.parse.MathReadError:
        # a template the drill's reader doesn't take ("1 8 sqrt(7)"): SymPy's LaTeX does
        return str(core.sympy.latex(core.verify.kb_expr(text)))


def _fill(problem: Problem, template: str) -> str:
    return str(loader.load().validator.fill(template, problem.env))


def _grade_text(problem: Problem, text: str) -> grading.AnswerVerdict:
    recipe = problem.recipe
    if recipe.kind == "graph":
        parts = [p.strip() for p in text.split(";")]
        return grading.check_graph(problem, parts[0], _tex(parts[1]), _tex(parts[2]))
    if recipe.kind in ("none", "all_reals"):
        return grading.check_keyboard(problem, text)
    return grading.check_typed(problem, _tex(text))


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_the_right_answer_is_graded_right(recipe: Recipe) -> None:
    for problem in problems(recipe):
        ans = recipe.raw["answer"]
        if recipe.kind in ("none", "all_reals"):
            verdict = grading.check_choice(problem, recipe.kind)
        else:
            verdict = _grade_text(problem, _fill(problem, ans.get("display") or ans["value"]))
        assert verdict.ok, (recipe.id, problem.seed, verdict.headline)


@pytest.mark.parametrize("recipe", all_recipes(), ids=ids(all_recipes()))
def test_every_mistake_is_named(recipe: Recipe) -> None:
    v = loader.load().validator
    equal_rules = [m for m in recipe.mistakes if "answer_equals" in m.rule]
    seen: set[str] = set()
    for problem in problems(recipe):
        for mk in recipe.mistakes:
            if mk.applies_if and not v.cond(mk.applies_if, problem.env):
                continue
            if "answer_equals" in mk.rule:
                text = _fill(problem, mk.rule["answer_equals"])
                verdict = _grade_text(problem, text)
                # two mistakes can give the same wrong answer: the first one listed is named
                wrong = v._answer_obj(recipe.raw, problem.env, mk.rule["answer_equals"])
                expected = next(
                    m.id
                    for m in equal_rules
                    if (not m.applies_if or v.cond(m.applies_if, problem.env))
                    and grading._same(  # pyright: ignore[reportPrivateUsage]
                        problem,
                        v._answer_obj(recipe.raw, problem.env, m.rule["answer_equals"]),
                        wrong,
                    )
                )
                assert not verdict.ok
                assert verdict.mistake is not None and verdict.mistake.id == expected, (
                    recipe.id,
                    problem.seed,
                    mk.id,
                )
                seen.add(mk.id)
            elif "form_violation" in mk.rule:
                verdict = _grade_text(problem, _fill(problem, mk.rule["example"]))
                assert not verdict.ok and verdict.value_ok and verdict.forms, (recipe.id, mk.id)
                assert verdict.mistake is not None and verdict.mistake.id == mk.id
                assert verdict.headline.startswith("Right value, but ")
                seen.add(mk.id)
    # a mistake that never fires on any of the 20 instances (applies_if) is allowed; the rest must
    ruled = {
        m.id for m in recipe.mistakes if "answer_equals" in m.rule or "form_violation" in m.rule
    }
    assert seen <= ruled


def test_the_mistake_checks_above_are_not_vacuous() -> None:
    rules = [
        m.rule
        for recipe in all_recipes()
        for m in recipe.mistakes
        if "answer_equals" in m.rule or "form_violation" in m.rule
    ]
    assert len(rules) >= 50
    assert any("form_violation" in r for r in rules)


# -- the adapter --------------------------------------------------------------------------------


def _key_is_graded(latex: str, key: str, kind: str, forms: list[str]) -> dict[str, Any]:
    core = loader.load()
    return dict(core.verify.check_answer(palette_to_keyboard(latex), key, kind, forms))


def test_an_unreduced_fraction_is_a_form_problem() -> None:
    r = _key_is_graded(r"\frac{6}{8}", "3/4", "list", ["exact", "reduced_fraction"])
    assert r["value_ok"] and not r["ok"]
    assert any("fraction not reduced" in p for p in r["form_problems"])


def test_a_reduced_fraction_is_right() -> None:
    assert _key_is_graded(r"\frac{3}{4}", "3/4", "list", ["exact", "reduced_fraction"])["ok"]


def test_an_unsimplified_radical_is_a_form_problem() -> None:
    r = _key_is_graded(r"\pm\sqrt{8}", "+-2*sqrt(2)", "list", ["exact", "simplified_radical"])
    assert r["value_ok"] and any("radical not simplified" in p for p in r["form_problems"])
    assert _key_is_graded(r"\pm2\sqrt{2}", "+-2*sqrt(2)", "list", ["simplified_radical"])["ok"]


def test_the_quadratic_formula_answer_with_an_unsimplified_radical() -> None:
    r = _key_is_graded(
        r"\frac{-2\pm\sqrt{88}}{6}", "-1/3 +- sqrt(22)/3", "list", ["exact", "simplified_radical"]
    )
    assert r["value_ok"] and any("radical not simplified" in p for p in r["form_problems"])


def test_a_union_of_intervals() -> None:
    key = "(-inf, -2) U (3, inf)"
    assert _key_is_graded(r"(-\infty,-2)\cup(3,\infty)", key, "interval", ["interval"])["ok"]
    assert not _key_is_graded(r"(-\infty,-2]\cup(3,\infty)", key, "interval", ["interval"])["ok"]


def test_the_imaginary_unit_before_a_root_is_not_sympys_isqrt() -> None:
    assert palette_to_keyboard(r"i\sqrt{448}") == "i*sqrt(448)"
    assert palette_to_keyboard(r"2i\sqrt{7}") == "2i*sqrt(7)"
    assert palette_to_keyboard(r"\pi\sqrt{2}") == "pi sqrt(2)"
    assert palette_to_keyboard(r"x\left|y\right|") == "x*abs(y)"
    assert palette_to_keyboard(r"2\sqrt{3}") == "2sqrt(3)"  # a number first: nothing to fix
    assert palette_to_keyboard(r"\sin\left(x\right)") != ""  # real function names stay whole
    core = loader.load()
    key = "8*sqrt(7)*i"
    for typed in (r"8i\sqrt{7}", r"8\sqrt{7}i"):
        assert core.verify.check_answer(palette_to_keyboard(typed), key, "expr", [])["ok"], typed


def test_or_between_inequalities_reads_as_or() -> None:
    assert palette_to_keyboard(r"x<-1\lor x>3") == "x<-1 or x>3"
    assert palette_to_keyboard(r"x\le-2\vee x\ge 5") == "x<=-2 or x>=5"
    core = loader.load()
    assert core.verify.is_inequality(palette_to_keyboard(r"x<-1\lor x>3"))


def test_the_private_use_group_marks_never_reach_the_checker() -> None:
    for latex in (r"\frac{1}{2}", r"\frac{x+1}{2}", r"\sqrt{x+1}", r"(1,2)\cup[3,4]"):
        out = palette_to_keyboard(latex)
        assert "\ue200" not in out and "\ue201" not in out and "∪" not in out


def test_redundant_parentheses_are_dropped_but_real_ones_stay() -> None:
    assert palette_to_keyboard(r"\sqrt{8}") == "sqrt(8)"
    assert palette_to_keyboard(r"\frac{6}{8}") == "(6/8)"
    assert palette_to_keyboard(r"\frac{x+1}{2}") == "((x+1)/2)"


@pytest.mark.parametrize("latex", ["", "  ", r"\frac{\placeholder{}}{2}", r"\sqrt{\placeholder{}}"])
def test_an_empty_or_unfinished_field_is_unreadable_not_wrong(latex: str) -> None:
    with pytest.raises(UnreadableAnswer):
        palette_to_keyboard(latex)


def test_an_unfinished_field_is_not_a_wrong_try(tmp_path: Any) -> None:
    recipe = CH03[0]
    verdict = grading.check_typed(problems(recipe)[0], r"\frac{\placeholder{}}{2}")
    assert not verdict.ok and not verdict.counts_as_try and verdict.unreadable
