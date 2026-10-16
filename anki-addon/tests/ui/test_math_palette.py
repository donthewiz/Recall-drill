"""The math field and its palette in a real browser (Chromium through Playwright).

QtWebEngine can't start on Qt's offscreen platform, so the page the drill window loads into
its math web view (``math_input.shell_body`` plus ``web/mathlive`` and ``web/rd_math_input.js``,
the very files that ship) is loaded here from ``file://`` URLs, with ``pycmd`` stubbed to record
what the window would be sent. Skipped where Playwright or its Chromium isn't installed (the
browser isn't part of Anki or of the add-on's dev set-up on every machine).
"""

from __future__ import annotations

import importlib.util
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

from recalldrill import math_input
from recalldrill.math_answer import check_answer, keyboard_from_palette
from recalldrill.math_parse import latex_to_keyboard
from recalldrill.ui import style

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("playwright") is None, reason="Playwright isn't installed"
)

WEB = Path(__file__).resolve().parents[2] / "web"


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception as exc:  # no Chromium for this Playwright
            pytest.skip(f"Chromium can't start here: {exc}")
        yield b
        b.close()


class Pad:
    """One loaded palette page."""

    def __init__(self, page: Any, requests: list[str]) -> None:
        self.page = page
        self.requests = requests

    def cmds(self) -> list[str]:
        return list(self.page.evaluate("window.__cmds"))

    def value(self) -> str:
        return str(self.page.evaluate("rdMath.value()"))

    def clear(self) -> None:
        self.page.evaluate("rdMath.clear(); window.__cmds.length = 0;")
        self.page.evaluate("rdMath.focus()")

    def click(self, key: str) -> None:
        self.page.click(f"#rd-pad-{key}")

    def type(self, text: str) -> None:
        self.page.keyboard.type(text)

    def press(self, key: str) -> None:
        self.page.keyboard.press(key)


@pytest.fixture
def pad(browser: Any, tmp_path: Path) -> Iterator[Pad]:
    body = math_input.shell_body(style.derived("light"), style.derived("dark"))
    html = f"""<!doctype html><html><head><meta charset="utf-8"></head><body>
<script>window.__cmds = []; window.pycmd = function (c) {{ window.__cmds.push(c); }};</script>
<script src="{(WEB / "mathlive" / "mathlive.min.js").as_uri()}"></script>
<script src="{(WEB / "rd_math_input.js").as_uri()}"></script>
{body}</body></html>"""
    path = tmp_path / "pad.html"
    path.write_text(html, encoding="utf-8")
    page = browser.new_page(viewport={"width": 900, "height": 420})
    requests: list[str] = []
    page.on("request", lambda r: requests.append(r.url))
    page.route(
        "**/*",
        lambda route: (
            route.continue_() if route.request.url.startswith(("file:", "data:")) else route.abort()
        ),
    )
    page.goto(path.as_uri())
    page.wait_for_function("window.rdMath && rdMath.ready()")
    page.wait_for_function("document.activeElement.tagName === 'MATH-FIELD'", timeout=3000)
    yield Pad(page, requests)
    page.close()


def test_the_field_has_focus_when_the_page_opens(pad: Pad) -> None:
    pad.page.wait_for_function("document.activeElement.tagName === 'MATH-FIELD'", timeout=3000)


def test_the_palette_has_every_button_and_all_are_big_enough(pad: Pad) -> None:
    keys = [b.key for b in math_input.PALETTE]
    shown = pad.page.eval_on_selector_all(
        "#rd-pad button", "els => els.map(e => e.getAttribute('data-key'))"
    )
    assert shown == keys
    assert set(keys) >= {
        "frac", "power", "sqrt", "pm", "parens", "abs", "le", "ge", "lbracket", "rparen",
        "lparen", "rbracket", "pi", "i", "inf", "cup", "backspace", "left", "right",
    }  # fmt: skip
    for key in keys:
        box = pad.page.locator(f"#rd-pad-{key}").bounding_box()
        assert box is not None
        assert box["width"] >= math_input.MIN_TARGET_PX, key
        assert box["height"] >= math_input.MIN_TARGET_PX, key
        assert box["x"] >= 0 and box["x"] + box["width"] <= 900, key  # no sideways scrolling
    assert pad.page.evaluate("document.documentElement.scrollWidth <= window.innerWidth")


def test_the_note_says_graded_by_form(pad: Pad) -> None:
    assert pad.page.inner_text("#rd-math-note") == "Graded by form; any order"


# What each button leaves in an empty field (or after the letter x for the power button).
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
}


@pytest.mark.parametrize(("key", "latex"), sorted(INSERTS.items()))
def test_each_palette_button_inserts_its_symbol(pad: Pad, key: str, latex: str) -> None:
    pad.clear()
    pad.click(key)
    assert pad.value() == latex
    assert f"{math_input.VALUE_PREFIX}{latex}" in pad.cmds()  # and Python is told


def test_the_power_button_raises_what_was_typed(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    pad.click("power")
    assert pad.value() == "x^{\\placeholder{}}"
    pad.type("2")
    assert pad.value() == "x^2"
    pad.click("right")  # out of the exponent
    pad.type("+1")
    assert pad.value() == "x^2+1"


def test_a_multi_digit_exponent_stays_in_the_exponent(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    pad.click("power")
    pad.type("10")
    assert pad.value() == "x^{10}"
    assert check_answer(keyboard_from_palette(pad.value()), "x^10").right


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


def test_the_buttons_do_not_steal_the_focus(pad: Pad) -> None:
    pad.clear()
    pad.click("pi")
    assert pad.page.evaluate("document.activeElement.tagName") == "MATH-FIELD"
    pad.type("r")  # keeps typing in the field
    assert pad.value() == "\\pi r"


def test_a_fraction_an_interval_and_the_quadratic_are_graded_as_typed(pad: Pad) -> None:
    pad.clear()
    pad.click("frac")
    pad.type("1")
    pad.click("right")
    pad.type("2")
    assert pad.value() in ("\\frac{1}{2}", "\\frac12")  # MathLive writes one-digit parts bare
    assert check_answer(keyboard_from_palette(pad.value()), "1/2").right

    pad.clear()
    pad.click("lbracket")
    pad.type("-2,5")
    pad.click("rparen")
    assert pad.value() == "[-2,5)"
    assert check_answer(keyboard_from_palette(pad.value()), "[-2,5)").right
    assert not check_answer(keyboard_from_palette(pad.value()), "(-2,5)").right

    pad.clear()
    pad.type("x=")
    pad.click("frac")
    pad.type("-b")
    pad.click("pm")
    pad.click("sqrt")
    pad.type("b")
    pad.click("power")
    pad.type("2")
    pad.click("right")
    pad.type("-4ac")
    # out of the root and across to the denominator
    pad.click("right")
    pad.click("right")
    pad.type("2a")
    typed = keyboard_from_palette(pad.value())
    assert check_answer(typed, "x=(-b+-sqrt(b^2-4ac))/(2a)").right, (pad.value(), typed)


def test_ranges_with_infinity_pi_and_union(pad: Pad) -> None:
    pad.clear()
    pad.click("lparen")
    pad.click("pm")  # a sign inside brackets is kept for the check to refuse
    pad.click("inf")
    pad.type(",3")
    pad.click("rbracket")
    pad.click("cup")
    pad.click("lparen")
    pad.type("5,")
    pad.click("inf")
    pad.click("rparen")
    got = keyboard_from_palette(pad.value())
    assert latex_to_keyboard(pad.value()) == got
    assert not check_answer(got, "(-inf,3]U(5,inf)").right  # +-inf is not -inf


def test_the_drills_keys_work_with_the_focus_in_the_field(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    keys = {
        "Enter": "rd:enter",
        "Control+Enter": "rd:ctrl-enter",
        "Escape": "rd:reveal",
        "Control+i": "rd:extra",
        "Control+e": "rd:edit",
        "Control+r": "rd:replay",
    }
    for key, cmd in keys.items():
        pad.page.evaluate("window.__cmds.length = 0")
        pad.press(key)
        got = pad.cmds()
        assert got[-1] == cmd, key
        assert got[0] == f"{math_input.VALUE_PREFIX}x", key  # the value arrives first
        assert pad.value() == "x", key  # and the key typed nothing
        assert pad.page.evaluate("document.activeElement.tagName") == "MATH-FIELD"


def test_a_locked_field_ignores_typing_and_buttons(pad: Pad) -> None:
    pad.clear()
    pad.type("x")
    pad.page.evaluate("rdMath.configure({readOnly: true, placeholder: '', night: false})")
    pad.page.evaluate("document.querySelector('#rd-pad-pi').click()")
    pad.type("y")
    assert pad.value() == "x"
    assert pad.page.eval_on_selector("#rd-pad-pi", "e => e.disabled")
    pad.page.evaluate("rdMath.configure({readOnly: false, placeholder: '', night: false})")
    pad.click("pi")
    assert pad.value() == "x\\pi"


def test_clear_and_the_value_bridge(pad: Pad) -> None:
    pad.type("12")
    pad.page.wait_for_function(f"window.__cmds.includes('{math_input.VALUE_PREFIX}12')")
    pad.page.evaluate("rdMath.clear()")
    assert pad.value() == ""
    assert pad.cmds()[-1] == math_input.VALUE_PREFIX  # an empty value, sent


def test_nothing_is_fetched_from_the_network_and_no_sound_plays(pad: Pad) -> None:
    pad.click("frac")
    pad.type("1")
    pad.press("Enter")
    assert pad.requests and all(u.startswith(("file:", "data:")) for u in pad.requests)
    assert not any(".wav" in u or ".mp3" in u or "sounds" in u for u in pad.requests)
    assert pad.page.evaluate("document.fonts.size > 0")  # drawn with the shipped fonts


def test_the_night_theme_switches_the_colours(pad: Pad) -> None:
    light = pad.page.evaluate("getComputedStyle(document.body).backgroundColor")
    pad.page.evaluate("rdMath.configure({readOnly: false, placeholder: '', night: true})")
    dark = pad.page.evaluate("getComputedStyle(document.body).backgroundColor")
    assert light != dark
