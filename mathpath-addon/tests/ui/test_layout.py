"""The page's scroll area ends clear of the palette and the button bar (bug #14, 2026-10-18):
scrolled to the end, the whole "Your answer" box (and the Check button) is on screen."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from drive import new_session, new_store
from page_harness import Browser, needs_playwright
from recipe_files import CH03, load

from math_path.pages import PageView
from math_path.progress import FADED, SOLO, NoteProgress
from math_path.views import learn_view

pytestmark = needs_playwright

SHOTS = Path(os.environ["MP_SHOTS"]) if os.environ.get("MP_SHOTS") else None
FACTORING = load(CH03 / "ca.quad.solve_factoring.json")

RECTS = """() => {
  const r = (sel) => {
    const e = document.querySelector(sel);
    if (!e) { return null; }
    const b = e.getBoundingClientRect();
    return {top: b.top, bottom: b.bottom};
  };
  return {main: r('.mp-main'), pad: r('.mp-padwrap'), foot: r('.mp-foot'),
          box: r('.mp-answer .mp-fieldwrap'), check: r('.mp-foot [data-act="check"]'),
          height: window.innerHeight};
}"""


def _draw(page: Browser, tmp_path: Path, stage: str, level: int, night: bool) -> None:
    st = new_store(tmp_path)
    st.put(100, NoteProgress(stage=stage, faded_level=level))
    s, _st, _h = new_session(tmp_path, [FACTORING], st)
    screen = learn_view.render(s)
    page.draw(PageView(screen.html, screen.fields, screen.texts, screen.readonly, "", night))
    page.settle()


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
@pytest.mark.parametrize("size", [(800, 600), (1000, 700)], ids=["800x600", "1000x700"])
@pytest.mark.parametrize(("stage", "level"), [(FADED, 1), (FADED, 2), (SOLO, 1)])
def test_scrolled_to_the_end_the_whole_answer_box_is_clear_of_the_palette(
    make_page: Any, tmp_path: Path, night: bool, size: tuple[int, int], stage: str, level: int
) -> None:
    page: Browser = make_page(night=night)
    page.page.set_viewport_size({"width": size[0], "height": size[1]})
    _draw(page, tmp_path, stage, level, night)
    page.page.evaluate("document.querySelector('.mp-main').scrollTop = 1e6")
    r = page.page.evaluate(RECTS)
    assert r["pad"] is not None and r["box"] is not None and r["check"] is not None
    assert r["main"]["bottom"] <= r["pad"]["top"] + 0.5  # the scroll area ends above the palette
    assert r["box"]["bottom"] <= r["pad"]["top"] - 8  # the whole box, with room for the caret
    assert r["box"]["top"] >= r["main"]["top"]
    assert r["foot"]["bottom"] <= r["height"] + 0.5  # the button bar is on screen
    assert r["check"]["bottom"] <= r["height"] + 0.5
    if SHOTS is not None and (stage, level) == (FADED, 1) and size == (800, 600):
        page.page.screenshot(path=str(SHOTS / f"faded_end_{'dark' if night else 'light'}.png"))
