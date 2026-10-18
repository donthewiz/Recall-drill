"""The bridge between the page and Python."""

from __future__ import annotations

import json

import pytest

from math_path import pages
from math_path.pages import Command, PageView, parse_command


@pytest.mark.parametrize(
    ("cmd", "expected"),
    [
        ("mp:act:check", Command("act", "check", "")),
        ("mp:act:rate:3", Command("act", "rate", "3")),
        ("mp:act:go:a:b", Command("act", "go", "a:b")),
        ("mp:field:ans:\\frac{1}{2}", Command("field", "ans", "\\frac{1}{2}")),
        ("mp:field:s2:a:b", Command("field", "s2", "a:b")),
        ("mp:text:plan1:say the plan: first", Command("text", "plan1", "say the plan: first")),
        (
            "mp:select:pick:ca.quad.solve_factoring:123",
            Command("select", "pick:ca.quad.solve_factoring", "123"),
        ),
        ("mp:select:x:", Command("select", "x", "")),
        ("mp:focus:ans", Command("focus", "ans")),
        ("mp:enter:", Command("enter", "")),
        ("mp:enter:step2", Command("enter", "step2")),
        ("mp:ctrl-enter:", Command("ctrl-enter")),
        ("mp:esc:", Command("esc")),
    ],
)
def test_parse_command(cmd: str, expected: Command) -> None:
    assert parse_command(cmd) == expected


@pytest.mark.parametrize("cmd", ["", "rd:enter", "mp", "mp:nope:x", "play:q:1"])
def test_other_commands_are_not_ours(cmd: str) -> None:
    assert parse_command(cmd) is None


def test_render_call_is_a_json_payload() -> None:
    view = PageView("<b>é</b>", {"ans": "x^{2}"}, {"t": 'a"b'}, ("s1",), "ans", True)
    call = pages.render_call(view)
    assert call.startswith("mp.render(") and call.endswith(");")
    payload = json.loads(call[len("mp.render(") : -2])
    assert payload == {
        "html": "<b>é</b>",
        "fields": {"ans": "x^{2}"},
        "texts": {"t": 'a"b'},
        "readonly": ["s1"],
        "focus": "ans",
        "night": True,
        "keep": False,
    }


def test_the_palette_has_every_button_of_recall_drill_v06_and_a_comma() -> None:
    keys = [b.key for b in pages.PALETTE]
    assert keys == [
        "frac", "power", "sqrt", "parens", "abs", "pm", "le", "ge", "pi", "i", "inf", "cup",
        "lbracket", "lparen", "rparen", "rbracket", "comma", "backspace", "left", "right",
    ]  # fmt: skip
    html = pages.pad_html()
    for key in keys:
        assert f'id="mp-pad-{key}"' in html
    assert html.count("<button") == len(keys)


def test_the_web_exports_pattern_matches_exactly_the_served_files() -> None:
    import re

    pattern = re.compile(pages.web_pattern())
    for ok in (
        "web/mp_page.js",
        "web/mp_page.css",
        "web/mathlive/mathlive.min.js",
        "web/mathlive/fonts/KaTeX_Main-Regular.woff2",
    ):
        assert pattern.fullmatch(ok), ok
    for bad in ("web/vendor/sympy/__init__.py", "user_files/progress.json", "core/verify_math.py",
                "web/mathlive/LICENSE.txt", "__init__.py"):  # fmt: skip
        assert not pattern.fullmatch(bad), bad


def test_script_and_css_urls_are_served_from_the_add_on_folder() -> None:
    urls = pages.script_urls("math_path_dev")
    assert urls[:2] == ["js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js"]
    assert urls[2:] == [
        "/_addons/math_path_dev/web/mathlive/mathlive.min.js",
        "/_addons/math_path_dev/web/mp_page.js",
    ]
    assert pages.css_urls("math_path") == ["/_addons/math_path/web/mp_page.css"]


def test_the_page_has_no_colour_of_its_own() -> None:
    import re
    from pathlib import Path

    css = (Path(__file__).resolve().parents[2] / "web" / "mp_page.css").read_text(encoding="utf-8")
    body = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    assert not re.findall(r"#[0-9a-fA-F]{3,8}\b", body)
    assert not re.findall(r"\brgba?\(", body)
