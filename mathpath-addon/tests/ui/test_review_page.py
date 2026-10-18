"""The review window's screens in a real browser, dark and light."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from drive import note_for, sequential_problems, type_answer
from page_harness import Browser, needs_playwright
from recipe_files import CH03, load

from math_path.pages import Command, PageView
from math_path.review import ReviewSession
from math_path.session import ListHistory
from math_path.views import review_view

pytestmark = needs_playwright

SHOTS = Path(os.environ["MP_SHOTS"]) if os.environ.get("MP_SHOTS") else None
FACTORING = load(CH03 / "ca.quad.solve_factoring.json")


def session() -> ReviewSession:
    return ReviewSession(note_for(FACTORING, 1), 9, sequential_problems(), ListHistory())


def draw(page: Browser, s: ReviewSession, night: bool, notice: str = "") -> None:
    screen = review_view.render(s, notice=notice)
    page.draw(
        PageView(screen.html, screen.fields, screen.texts, screen.readonly, screen.focus, night)
    )
    page.settle()


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_the_review_screens(make_page, night: bool) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page(night=night)
    s = session()
    draw(page, s, night)
    text = page.text()
    assert "Review" in text and "Solve a quadratic equation by factoring" in text
    assert page.page.locator("math-field").count() == 1
    assert page.page.locator('[data-act="choose"]').count() == 2
    assert "Stage" not in text and "Faded" not in text  # a review has no stages
    assert page.page.locator('[data-act="check"]').count() == 1
    if SHOTS is not None:
        page.screenshot(SHOTS / f"review_{'dark' if night else 'light'}.png")
    assert s.run is not None
    type_answer(s.run, right=False)
    s.command(Command("act", "check"))
    type_answer(s.run)
    s.command(Command("act", "check"))
    draw(page, s, night)
    text = page.text()
    assert "Right after a wrong try." in text
    assert "Math Path picked Again for Anki" in text
    pills = page.page.locator(".mp-rating .mp-pill")
    assert [pills.nth(i).inner_text() for i in range(4)] == ["Again", "Hard", "Good", "Easy"]
    assert page.page.locator(".mp-rating .mp-pill.on").inner_text() == "Again"
    assert "Next (Again)" in text and "Worked solution" in text
    assert page.page.locator("math-field").count() == 0
    if SHOTS is not None:
        page.screenshot(SHOTS / f"review_done_{'dark' if night else 'light'}.png")
    page.page.click('.mp-pill[data-arg="4"]')
    assert "mp:act:rate:4" in page.cmds()
    s.command(Command("act", "rate", "4"))
    draw(page, s, night)
    assert page.page.locator(".mp-rating .mp-pill.on").inner_text() == "Easy"
    assert "Next (Easy)" in page.text()


def test_a_notice_is_shown_when_the_card_could_not_be_rated(make_page) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = session()
    assert s.run is not None
    type_answer(s.run)
    s.command(Command("act", "check"))
    draw(page, s, False, "The reviewer is no longer on this card, so it wasn't rated.")
    assert "The reviewer is no longer on this card" in page.text()
    assert page.page.locator(".mp-note.warn").count() >= 1


def test_the_preparing_screen(make_page) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = ReviewSession(note_for(FACTORING, 1), 9, lambda _r: None, ListHistory())
    draw(page, s, False)
    assert "Preparing…" in page.text()
