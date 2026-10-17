"""The import dialog's screens, drawn in a real browser, dark and light."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from page_harness import needs_playwright
from recipe_files import ch03

from math_path.import_controller import ImportController
from math_path.import_plan import DeckChoice, ImportItem, ImportPlan, ImportSummary
from math_path.pages import PageView

pytestmark = needs_playwright

SHOTS = Path(os.environ["MP_SHOTS"]) if os.environ.get("MP_SHOTS") else None
"""Set MP_SHOTS to a folder to also save screenshots (for looking at, never committed)."""


def _plan() -> ImportPlan:
    recipes = ch03()
    decks = (DeckChoice(1, "College Algebra::Ch 03::3.2 Quadratic"), DeckChoice(2, "Other::3.2 X"))
    items = (
        ImportItem("a.json", recipes[0], "add", did=1, candidates=decks[:1]),
        ImportItem("b.json", recipes[1], "update", "version 1 → 2", existing_nid=5),
        ImportItem("c.json", recipes[2], "unchanged", "already imported (version 1)"),
        ImportItem("d.json", recipes[3], "add", "several decks start with '3.2'", candidates=decks),
        ImportItem("e.json", None, "skip", "format 'other/1' is not one Math Path reads"),
    )
    return ImportPlan(items, decks)


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_each_screen_draws(make_page, night: bool, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page = make_page(night=night)
    ctrl = ImportController()
    page.draw(PageView(ctrl.view_html(), night=night))
    assert "Choose folder" in page.text()
    ctrl.folder_chosen("C:/recipes")
    page.draw(PageView(ctrl.view_html(), night=night))
    assert "Checking recipes" in page.text()
    ctrl.scanned(_plan())
    page.draw(PageView(ctrl.view_html(), night=night))
    text = page.text()
    assert (
        "2 to add" in text
        and "1 to update" in text
        and "1 unchanged" in text
        and "1 skipped" in text
    )
    assert "several decks match" in text and "Skip (no deck)" in text
    if SHOTS is not None:
        page.screenshot(SHOTS / f"import_review_{'dark' if night else 'light'}.png")
    ctrl.done(ImportSummary(("a",), ("b",), ("c",), (("e.json", "bad"),)))
    page.draw(PageView(ctrl.view_html(), night=night))
    assert "Added 1, updated 1, unchanged 1, skipped 1." in page.text()


def test_the_deck_list_reports_the_pick(make_page) -> None:  # type: ignore[no-untyped-def]
    page = make_page()
    ctrl = ImportController()
    ctrl.folder_chosen("x")
    ctrl.scanned(_plan())
    page.draw(PageView(ctrl.view_html()))
    rid = ch03()[3].id
    page.page.select_option(f'select[data-id="pick:{rid}"]', "2")
    assert f"mp:select:pick:{rid}:2" in page.cmds()
    page.page.click('[data-act="import"]')
    assert "mp:act:import" in page.cmds()
