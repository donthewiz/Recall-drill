"""math_answer: same form / equivalent / wrong, the palette's LaTeX, and the engine strings."""

from __future__ import annotations

import pytest

from recalldrill.engine.grading import grade
from recalldrill.engine.items import build_item, chunk_text, list_items
from recalldrill.math_answer import (
    READ_MESSAGE,
    WRONG_MARK,
    check_answer,
    engine_target,
    engine_typed,
    keyboard_from_palette,
    latex_of,
    usable_target,
)
from recalldrill.math_parse import MathReadError, latex_to_keyboard, parse

QUADRATIC = "x=(-b+-sqrt(b^2-4ac))/(2a)"

# (typed, card answer, expected outcome): the required table, then more.
TABLE: list[tuple[str, str, str]] = [
    ("x^2", "x-2", "wrong"),
    ("1/2", "12", "wrong"),
    ("(x+3)(x-2)", "(x-2)(x+3)", "right"),
    ("-4ac+b^2", "b^2-4ac", "right"),
    (QUADRATIC, "x = ( - b +- sqrt( b^2 - 4*a*c ) ) / ( 2*a )", "right"),
    ("x=(-b-sqrt(b^2-4ac))/(2a)", QUADRATIC, "wrong"),
    ("x=-b/(2a)+-sqrt(b^2-4ac)/(2a)", QUADRATIC, "equivalent"),
    ("m=(y1-y2)/(x2-x1)", "m=(y2-y1)/(x2-x1)", "wrong"),
    ("m=(y_2-y_1)/(x_2-x_1)", "m=(y2-y1)/(x2-x1)", "right"),
    ("a^2-b^2", "(a+b)(a-b)", "equivalent"),
    ("(-2,5)", "[-2,5)", "wrong"),
    ("[-2,5)", "[-2,5)", "right"),
    ("2-3i", "2+3i", "wrong"),
    ("5>=x", "x<=5", "right"),
    ("x<5", "x<=5", "wrong"),
    (")(", "x+1", "unreadable"),
]


@pytest.mark.parametrize(("typed", "answer", "outcome"), TABLE)
def test_required_table(typed: str, answer: str, outcome: str) -> None:
    check = check_answer(typed, answer)
    assert check.outcome == outcome
    assert check.right == (outcome == "right")


def test_messages() -> None:
    eq = check_answer("a^2-b^2", "(a+b)(a-b)")
    assert eq.message.startswith("Equivalent, but this card wants: ")
    assert eq.target_latex in eq.message
    assert check_answer(")(", "x+1").message == READ_MESSAGE == "Couldn't read that as math"
    assert check_answer("x^2", "x-2").message
    assert check_answer("x", "x").message == ""


def test_equiv_tag_accepts_an_equivalent_form() -> None:
    assert check_answer("x=-b/(2a)+-sqrt(b^2-4ac)/(2a)", QUADRATIC, equiv=True).right
    assert check_answer("a^2-b^2", "(a+b)(a-b)", equiv=True).right
    assert check_answer("(a+b)^2", "a^2+2ab+b^2", equiv=True).right
    assert check_answer("2x+2", "2(x+1)", equiv=True).right


def test_equiv_still_rejects_what_is_not_equivalent() -> None:
    assert not check_answer("a^2+b^2", "(a+b)(a-b)", equiv=True).right
    assert not check_answer("2x+3", "2(x+1)", equiv=True).right
    assert not check_answer("sqrt(x^2)", "x", equiv=True).right  # not equal for negative x
    assert not check_answer("x=(-b-sqrt(b^2-4ac))/(2a)", QUADRATIC, equiv=True).right
    assert not check_answer("m=(y1-y2)/(x2-x1)", "m=(y2-y1)/(x2-x1)", equiv=True).right
    assert not check_answer("(-2,5)", "[-2,5)", equiv=True).right  # brackets are part of it


SAME_FORM = [
    ("2a", "2*a"),
    ("a*b", "ba"),
    ("x+1", "1+x"),
    ("y=mx+b", "mx+b=y"),
    ("(x+1)", "x+1"),
    ("((x+1))", "x+1"),
    ("x−y", "x-y"),
    ("2×x", "2x"),
    ("x≤ 5", "x<=5"),
    ("π r^2", "pi*r^2"),
    ("x^(1/2)", "sqrt(x)"),
    ("0.5x", "x/2"),
    ("|x-1|", "abs(x-1)"),
    ("(-inf,3]U(5,inf)", "(5,inf)U(-inf,3]"),
    ("{1,2,3}", "{3,2,1}"),
    ("x>2", "2<x"),
    ("1<x<=5", "5>=x>1"),
    ("1/(2a)", "1/(a*2)"),
    ("x=2,x=-3", "x=-3, x=2"),
    ("(1,2),(3,4)", "(3,4),(1,2)"),
]


@pytest.mark.parametrize(("typed", "answer"), SAME_FORM)
def test_same_form_up_to_trivial_differences(typed: str, answer: str) -> None:
    assert check_answer(typed, answer).outcome == "right"


DIFFERENT_FORM = [
    ("2(x+1)", "2x+2"),
    ("x+1+2", "x+3"),
    ("x/2", "x/3"),
    ("x-y", "y-x"),
    ("x=3", "x=-3"),
    ("-x^2", "(-x)^2"),
    ("x^-1", "x"),
    ("(1,2)", "[1,2]"),
    ("[1,2]", "[2,1]"),
    ("x+-1", "x+1"),
    ("x", "y"),
    ("X", "x"),
    ("x=2", "x=2,x=3"),
    ("(1,2),(3,4)", "(1,2),(3,5)"),
]


@pytest.mark.parametrize(("typed", "answer"), DIFFERENT_FORM)
def test_different_answers_are_not_right(typed: str, answer: str) -> None:
    assert not check_answer(typed, answer).right


def test_one_branch_of_a_plus_minus_answer_is_wrong() -> None:
    both = "x=+-3"
    assert check_answer("x=+-3", both).right
    assert not check_answer("x=-+3", both).right
    assert not check_answer("x=3", both).right
    assert not check_answer("x=-3", both).right


def test_unreadable_input_never_raises() -> None:
    for junk in ("", "   ", "x+", "((x", "x^^2", "1//2", "$$", "sqrt(", "x=", "[1,2", ")(", "x)"):
        c = check_answer(junk, "x+1")
        assert c.outcome == "unreadable" and not c.right and c.typed_latex is None


def test_pathological_input_is_contained() -> None:
    assert not check_answer("(" * 5000 + "x" + ")" * 5000, "x").right
    assert not check_answer("x" + "+-1" * 40, "x").right  # 2**40 branches refused


def test_a_target_that_cant_be_read_never_crashes() -> None:
    """Builds keep such cards out of the math path; if one got in, nothing is right."""
    assert not check_answer("x", "x+(").right
    assert check_answer("x", "x+(").target_latex == ""
    assert not usable_target("x+(")
    assert usable_target(QUADRATIC)


def test_latex_of() -> None:
    assert latex_of("m=(y2-y1)/(x2-x1)") == ("m = \\frac{y_{2} - y_{1}}{x_{2} - x_{1}}")
    assert latex_of("[-2,5)") == "\\left[ -2,\\, 5 \\right)"
    assert latex_of("2+3i") == "2 + 3 i"
    assert latex_of(")(") is None
    assert "\\pm" in (latex_of(QUADRATIC) or "")


# -- the palette's LaTeX ----------------------------------------------------------


PALETTE = [
    (r"x=\frac{-b\pm\sqrt{b^{2}-4ac}}{2a}", QUADRATIC),
    (r"\left[-2,5\right)", "[-2,5)"),
    (r"(-\infty,3]\cup(5,\infty)", "(-inf,3]U(5,inf)"),
    (r"\frac{1}{2}x^{2}", "(1/2)x^2"),
    (r"\left|x-1\right|", "abs(x-1)"),
    (r"\lvert x-1\rvert", "abs(x-1)"),
    (r"x\le5", "x<=5"),
    (r"x\geq5", "x>=5"),
    (r"y_{2}-y_{1}", "y2-y1"),
    (r"\sqrt[3]{x}", "x^(1/3)"),
    (r"2\pi r", "2*pi*r"),
    (r"x^{-1}", "x^(-1)"),
    (r"2+3\mathrm{i}", "2+3i"),
    (r"a\cdot b", "ab"),
    (r"\left(a+b\right)\left(a-b\right)", "(a+b)(a-b)"),
    (r"\sin\left(x\right)", "sin(x)"),
    (r"x^2y", "x^2*y"),
]


@pytest.mark.parametrize(("latex", "answer"), PALETTE)
def test_palette_latex_checks_like_the_keyboard_form(latex: str, answer: str) -> None:
    typed = latex_to_keyboard(latex)
    assert check_answer(typed, answer).right, (latex, typed)
    assert check_answer(keyboard_from_palette(latex), answer).right


def test_palette_junk_is_unreadable() -> None:
    for latex in (r"\frac{1}{\placeholder{}}", r"\frac{1}{", r"\unknown{x}", r"x^", r"\left|x"):
        with pytest.raises(MathReadError):
            latex_to_keyboard(latex)
        assert not check_answer(keyboard_from_palette(latex), "x").right


# -- the engine ---------------------------------------------------------------------

MATH_TARGETS = [
    "[-2,5)",
    "(1,2)",
    "(-inf,3]U(5,inf)",
    "{1,2,3,4,5}",
    "(1,2),(3,4),(5,6)",
    "x=1,2,3",
    "x=(-b+-sqrt(b^2-4ac))/(2a)",
    "A = P ( 1 + r / n ) ^ ( n t ) and then some more words so that this is long enough",
    "a+b+c+d+e+f+g+h+i+j+k+l+m+n+o+p+q+r+s+t+u+v+w+x+y+z+a+b+c+d+e+f+g+h",
    "x;y;z;w",
    "(x+1)(x+2)(x+3)(x+4)(x+5)(x+6)(x+7)(x+8)(x+9)(x+10)",
]


@pytest.mark.parametrize("answer", MATH_TARGETS)
@pytest.mark.parametrize("percent", [15, 35, 60, 100])
@pytest.mark.parametrize("threshold", [0, 1, 2, 8])
def test_a_math_target_is_one_engine_item(answer: str, percent: int, threshold: int) -> None:
    back = engine_target(answer)
    assert chunk_text(back, percent, threshold) is None
    assert list_items(back) is None
    item = build_item({"front": "f", "back": back}, 0, percent, "cumulative", threshold)
    assert item["chunks"] is None and item["stage"] == "full"
    # the engine sees one word
    assert " " not in back and "," not in back and ";" not in back


@pytest.mark.parametrize("answer", MATH_TARGETS)
def test_the_engine_grades_the_target_exact_and_a_wrong_answer_wrong(answer: str) -> None:
    back = engine_target(answer)
    assert grade(back, back)["verdict"] == "exact"
    for typed in ("", "x", answer + "+1", answer.replace("x", "z"), answer[::-1], "a", "the"):
        check = check_answer(typed, answer)
        if check.right:
            continue
        sent = engine_typed(typed, check, back)
        assert sent.startswith(WRONG_MARK)
        assert grade(sent, back)["verdict"] == "wrong", (typed, answer)
        assert grade(sent, back, strict_punctuation=True)["verdict"] == "wrong"


def test_a_right_answer_hands_the_engine_the_target_itself() -> None:
    back = engine_target(QUADRATIC)
    check = check_answer("x = (-b +- sqrt(b^2 - 4ac)) / (2a)", QUADRATIC)
    assert engine_typed("x = (-b +- sqrt(b^2 - 4ac)) / (2a)", check, back) == back


def test_the_engine_would_have_graded_the_table_wrongly_without_this() -> None:
    """The reason for the check: lenient mode keeps letters and digits, so these are equal."""
    assert grade("x^2", "x-2")["verdict"] == "exact"
    assert grade("1/2", "12")["verdict"] == "exact"
    assert grade("(-2,5)", "[-2,5)")["verdict"] == "exact"


def test_parse_reads_what_it_should() -> None:
    parse("x=(-b+-sqrt(b^2-4ac))/(2a)")
    parse("[-2,5)U(7,inf)")
    parse("2+3i")
    with pytest.raises(MathReadError):
        parse("")
