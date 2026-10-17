"""The math field and its palette in a real browser (Chromium through Playwright).

The page is the very one the windows load: ``pages.shell_body`` plus ``web/mp_page.css``, the
vendored MathLive and ``web/mp_page.js``, loaded from ``file://`` URLs with ``pycmd`` stubbed to
record what the window would be sent. Skipped where Playwright or its Chromium isn't installed.
"""

from __future__ import annotations

from collections.abc import Callable

import pytest
from page_harness import Browser, needs_playwright
from problems_cache import problems
from recipe_files import all_recipes

from math_path import grading, pages
from math_path.pages import PageView
from math_path.problem import Problem

pytestmark = needs_playwright


def _recipe(rid: str) -> Problem:
    recipe = next(r for r in all_recipes() if r.id == rid)
    return problems(recipe, 1)[0]


class Pad:
    def __init__(self, page: Browser) -> None:
        self.b = page
        page.draw(
            PageView(
                '<div class="mp-main">' + pages.math_field("ans") + pages.pad_html() + "</div>",
                focus="ans",
            )
        )
        page.page.wait_for_function("document.activeElement.tagName === 'MATH-FIELD'", timeout=3000)
        page.page.wait_for_timeout(100)

    def value(self) -> str:
        return str(self.b.page.evaluate("mp.fieldValue('ans')"))

    def clear(self) -> None:
        self.b.page.evaluate("mp.setField('ans', '')")
        self.b.page.evaluate("mp.focus('ans')")
        self.b.clear_cmds()

    def click(self, key: str) -> None:
        self.b.page.click(f"#mp-pad-{key}")

    def type(self, text: str) -> None:
        self.b.page.keyboard.type(text)

    def press(self, key: str) -> None:
        self.b.page.keyboard.press(key)


@pytest.fixture
def pad(make_page: Callable[..., Browser]) -> Pad:
    return Pad(make_page())


INSERTS = {
    "frac": "\\frac{\\placeholder{}}{\\placeholder{}}",
    "sqrt": "\\sqrt{\\placeholder{}}",
    "parens": "\\left(\\placeholder{}\\right)",
    "abs": "\\left|\\placeholder{}\\right|",
    "pm": "\\pm",
    "le": "\\le",
    "ge": "\\ge",
    "pi": "\\pi",
    "i": "i",
    "inf": "\\infty",
    "cup": "\\cup",
    "lbracket": "[",
    "rparen": ")",
    "lparen": "(",
    "rbracket": "]",
    "comma": ",",
}


@pytest.mark.parametrize(("key", "latex"), sorted(INSERTS.items()))
def test_each_palette_button_inserts_its_symbol(pad: Pad, key: str, latex: str) -> None:
    pad.clear()
    pad.click(key)
    assert pad.value() == latex
    assert f"mp:field:ans:{latex}" in pad.b.cmds()  # and Python is told


def test_the_power_button_raises_what_was_typed(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    pad.click("power")
    assert pad.value() == "x^{\\placeholder{}}"
    pad.type("2")
    assert pad.value() == "x^2"
    pad.click("right")
    pad.type("+1")
    assert pad.value() == "x^2+1"


def test_a_multi_digit_exponent_stays_in_the_exponent(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    pad.click("power")
    pad.type("10")
    assert pad.value() == "x^{10}"


def test_backspace_left_and_right(pad: Pad) -> None:
    pad.clear()
    pad.type("ab")
    pad.click("backspace")
    assert pad.value() == "a"
    pad.type("b")
    pad.click("left")
    pad.type("c")
    assert pad.value() == "acb"
    pad.click("right")
    pad.type("d")
    assert pad.value() == "acbd"


def test_every_button_is_big_enough_and_none_takes_the_focus(pad: Pad) -> None:
    for b in pages.PALETTE:
        box = pad.b.page.locator(f"#mp-pad-{b.key}").bounding_box()
        assert box is not None
        assert box["width"] >= pages.MIN_TARGET_PX and box["height"] >= pages.MIN_TARGET_PX, b.key
        assert box["x"] >= 0 and box["x"] + box["width"] <= 1000, b.key
    assert pad.b.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")
    pad.clear()
    pad.click("pi")
    assert pad.b.page.evaluate("document.activeElement.tagName") == "MATH-FIELD"
    pad.type("r")
    assert pad.value() == "\\pi r"


def test_enter_and_the_other_keys_go_to_python_with_the_field(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    for key, cmd in (
        ("Enter", "mp:enter:ans"),
        ("Control+Enter", "mp:ctrl-enter:"),
        ("Escape", "mp:esc:"),
    ):
        pad.b.clear_cmds()
        pad.press(key)
        cmds = pad.b.cmds()
        assert cmds[-1] == cmd, (key, cmds)
        assert "mp:field:ans:x" in cmds  # the latest text always arrives before the command
    assert pad.value() == "x"  # a key never leaves a newline behind


def test_nothing_but_files_is_requested(pad: Pad) -> None:
    pad.type("x")
    pad.click("frac")
    assert pad.b.requests
    assert all(r.startswith(("file:", "data:", "blob:")) for r in pad.b.requests), [
        r for r in pad.b.requests if not r.startswith(("file:", "data:", "blob:"))
    ]


# -- typed with the buttons, graded --------------------------------------------------------------


def _typed(pad: Pad, steps: list[str]) -> str:
    """Type a sequence: plain text is typed; ``@key`` clicks that palette button."""
    pad.clear()
    for s in steps:
        if s.startswith("@"):
            pad.click(s[1:])
        else:
            pad.type(s)
    return pad.value()


def test_a_plus_minus_radical_typed_with_the_buttons_is_graded(pad: Pad) -> None:
    problem = _recipe("ca.quad.solve_square_root")  # answer +-2*sqrt(3)
    key = problem.key
    assert key == "+-2*sqrt(3)"
    latex = _typed(pad, ["@pm", "2", "@sqrt", "3"])
    assert grading.check_typed(problem, latex).ok
    latex = _typed(pad, ["@pm", "@sqrt", "12"])
    verdict = grading.check_typed(problem, latex)
    assert not verdict.ok and verdict.value_ok and "radical isn't simplified" in verdict.headline


def test_a_fraction_typed_with_the_buttons_is_graded(pad: Pad) -> None:
    problem = _recipe("ca.abs.solve_eq")
    a, b = problem.key.split(", ")
    assert (a, b) == ("-17/8", "9/8")
    latex = _typed(
        pad, ["-", "@frac", "17", "@right", "8", "@right", "@comma", "@frac", "9", "@right", "8"]
    )
    assert grading.check_typed(problem, latex).ok, latex
    latex = _typed(
        pad, ["@frac", "9", "@right", "8", "@right", "@comma", "-", "@frac", "17", "@right", "8"]
    )
    assert grading.check_typed(problem, latex).ok  # any order
    latex = _typed(
        pad, ["-", "@frac", "34", "@right", "16", "@right", "@comma", "@frac", "9", "@right", "8"]
    )
    verdict = grading.check_typed(problem, latex)
    assert verdict.value_ok and not verdict.ok and "fraction isn't reduced" in verdict.headline


def test_an_interval_union_typed_with_the_buttons_is_graded(pad: Pad) -> None:
    problem = _recipe("ca.abs.solve_ineq_greater")
    assert problem.key == "(-inf, -17/8) U (9/8, inf)"
    latex = _typed(
        pad,
        ["@lparen", "-", "@inf", "@comma", "-", "@frac", "17", "@right", "8", "@right", "@rparen",
         "@cup", "@lparen", "@frac", "9", "@right", "8", "@right", "@comma", "@inf", "@rparen"],
    )  # fmt: skip
    assert grading.check_typed(problem, latex).ok, latex


def test_a_complex_number_typed_with_the_buttons_is_graded(pad: Pad) -> None:
    problem = _recipe("ca.cx.multiply")  # (5 - 6i)(4 + 3i) = 38 - 9i
    assert problem.key == "38 - 9*i"
    latex = _typed(pad, ["38-9", "@i"])
    assert grading.check_typed(problem, latex).ok, latex
    latex = _typed(pad, ["38-9"])
    assert not grading.check_typed(problem, latex).ok


def test_a_point_typed_with_the_buttons_is_graded(pad: Pad) -> None:
    problem = _recipe("ca.quadgraph.vertex")
    assert problem.key == "(5, -6)"
    latex = _typed(pad, ["@lparen", "5", "@comma", "-6", "@rparen"])
    assert grading.check_typed(problem, latex).ok, latex
    latex = _typed(pad, ["@lparen", "-6", "@comma", "5", "@rparen"])
    assert not grading.check_typed(problem, latex).ok


def test_the_no_solution_button_answer_is_graded(pad: Pad) -> None:
    # The two buttons ("No solution", "All real numbers") sit beside the field on the learn
    # screen (tests/ui/test_learn_page.py); here: what each one means to the grader.
    problem = _recipe("ca.rat.no_solution")
    assert grading.check_choice(problem, "none").ok
    assert not grading.check_choice(problem, "all_reals").ok
    other = _recipe("ca.quad.solve_factoring")
    assert not grading.check_choice(other, "none").ok
    assert not grading.check_choice(other, "all_reals").ok
