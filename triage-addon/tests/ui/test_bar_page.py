"""The bar drawn in real Chromium on a page shaped like Anki's reviewer page."""

from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("playwright")

from card_triage import bar  # noqa: E402

SHOT_DIR = Path(__file__).resolve().parent / "_shots"


def page_html(night: bool) -> str:
    html_cls = ' class="night-mode"' if night else ""
    body_cls = "card card1 nightMode night_mode" if night else "card card1"
    colors = "background:#2c2c2c;color:#eee" if night else "background:#fff;color:#000"
    return f"""<!doctype html><html{html_cls}><head><meta charset="utf-8"></head>
<body class="{body_cls}" style="margin:0;{colors};font:20px sans-serif">
<div id="qa" style="padding:60px 24px;text-align:center">
<p>What attaches a muscle to a bone?</p>
<input id="type" value="tendon" style="font-size:18px"></div>
<script>window.sent = []; function pycmd(m) {{ window.sent.push(m); }}
document.getElementById("type").focus();</script></body></html>"""


@pytest.fixture(scope="module")
def browser() -> Iterator[Any]:
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        try:
            b = p.chromium.launch()
        except Exception:
            # The cloud image's Chromium is not the build this Playwright pin looks for.
            try:
                b = p.chromium.launch(executable_path="/opt/pw-browsers/chromium")
            except Exception as exc:  # no Chromium at all
                pytest.skip(f"Chromium can't start here: {exc}")
        yield b
        b.close()


def open_page(browser: Any, tmp_path: Path, night: bool) -> Any:
    f = tmp_path / ("night.html" if night else "day.html")
    f.write_text(page_html(night), encoding="utf-8")
    page = browser.new_page(viewport={"width": 800, "height": 300})
    page.goto(f.as_uri())
    return page


def test_bar_shows_and_buttons_send_our_messages(browser: Any, tmp_path: Path) -> None:
    page = open_page(browser, tmp_path, night=False)
    page.evaluate(bar.show_js(bar.TIMER_TEXT, "x"))
    el = page.locator(f"#{bar.BAR_ID}")
    assert el.inner_text() == "Stuck on this one? Set aside (X) · Keep going"
    box = el.bounding_box()
    assert box is not None and box["y"] == 0 and box["height"] < 40  # slim, at the very top
    page.get_by_role("button", name="Set aside (X)").click()
    page.get_by_role("button", name="Keep going").click()
    assert page.evaluate("window.sent") == [bar.CMD_SET_ASIDE, bar.CMD_KEEP_GOING]


def test_bar_never_takes_keyboard_focus(browser: Any, tmp_path: Path) -> None:
    page = open_page(browser, tmp_path, night=False)
    page.evaluate(bar.show_js(bar.TIMER_TEXT, "x"))
    assert page.evaluate("document.activeElement.id") == "type"
    page.get_by_role("button", name="Keep going").click()  # a real mouse click
    assert page.evaluate("document.activeElement.id") == "type"
    page.keyboard.type("z")  # typing still goes to the page's own field
    assert page.evaluate("document.getElementById('type').value") == "ztendon"
    page.keyboard.press("Tab")  # tabbing never lands on the bar's buttons
    assert page.evaluate("document.activeElement.closest('#card-triage-bar')") is None


def test_bar_does_not_restyle_the_page_and_hide_removes_it(browser: Any, tmp_path: Path) -> None:
    page = open_page(browser, tmp_path, night=False)
    q = "getComputedStyle(document.getElementById('qa')).%s"
    before = [page.evaluate(q % p) for p in ("color", "fontSize", "paddingTop")]
    page.evaluate(bar.show_js(bar.again_text(2), "x"))
    assert [page.evaluate(q % p) for p in ("color", "fontSize", "paddingTop")] == before
    page.evaluate(bar.show_js(bar.TIMER_TEXT, "x"))  # shown twice: still one bar
    assert page.locator(f"#{bar.BAR_ID}").count() == 1
    page.evaluate(bar.hide_js())
    assert page.locator(f"#{bar.BAR_ID}").count() == 0
    assert page.locator(f"#{bar.STYLE_ID}").count() == 0


def test_bar_follows_ankis_night_mode(browser: Any, tmp_path: Path) -> None:
    colors: dict[bool, str] = {}
    SHOT_DIR.mkdir(exist_ok=True)
    for night in (False, True):
        page = open_page(browser, tmp_path, night)
        page.evaluate(bar.show_js(bar.again_text(2), "x"))
        colors[night] = page.evaluate(
            f"getComputedStyle(document.getElementById('{bar.BAR_ID}')).backgroundColor"
        )
        page.screenshot(path=str(SHOT_DIR / ("bar-dark.png" if night else "bar-light.png")))
    assert colors[False] != colors[True]
    assert colors[False] == "rgb(255, 244, 204)"
    assert colors[True] == "rgb(58, 52, 24)"
