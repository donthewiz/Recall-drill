"""The progress map in a real browser, dark and light: NEXT, locked chips, the amber Recall line,
In Anki chips, the course picker, the empty state."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from page_harness import Browser, needs_playwright
from test_course_model import course, note, section

from math_path.course_model import CardState
from math_path.pages import PageView
from math_path.progress import FADED, LEARNED, NoteProgress
from math_path.progress_controller import ProgressController
from math_path.views import progress_view

pytestmark = needs_playwright

SHOTS = Path(os.environ["MP_SHOTS"]) if os.environ.get("MP_SHOTS") else None


def draw(page: Browser, ctl: ProgressController, night: bool, notice: str = "") -> None:
    page.draw(PageView(html=progress_view.render(ctl, notice=notice), night=night))
    page.settle()


def sample() -> ProgressController:
    s1 = section(
        10,
        "3.1",
        [note("x.a", 1), note("x.b", 2, ["x.a"]), note("x.c", 3, tags=("mp::learned",))],
        20,
        20,
    )
    s2 = section(20, "3.3", [note("y.a", 4, ["x.b"]), note("y.b", 5)], 52, 12)
    c = course([s1, s2], {3: CardState("review", "review, due Mon Oct 19")})
    return ProgressController([c], {1: NoteProgress(stage=FADED, faded_level=2)})


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_the_map(make_page, night: bool) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page(night=night)
    ctl = sample()
    draw(page, ctl, night)
    text = page.text()
    assert "3.1 Name" in text and "3.3 Name" in text
    assert "20 / 20" in text and "12 / 52" in text
    assert page.page.locator("tr.next").count() == 1
    assert "NEXT" in page.page.locator("tr.next").inner_text()
    assert "needs Title x.a" in text  # a Locked chip names what it waits on
    assert "In Anki" in text and "review, due Mon Oct 19" in text
    assert "Faded" in text
    assert page.page.locator('[data-act="learn_next"]').is_enabled()
    assert page.page.locator("select").count() == 0  # one course: no picker
    if SHOTS is not None:
        page.screenshot(SHOTS / f"progress_{'dark' if night else 'light'}.png", height=900)


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_the_amber_recall_line(make_page, night: bool) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page(night=night)
    ctl = sample()
    ctl.confirm = 20
    draw(page, ctl, night)
    text = page.text()
    assert "Recall cards for 3.3: 12 / 52 drilled. Drilling them first helps." in text
    assert page.page.locator('[data-act="learn_anyway"]').count() == 1
    assert page.page.locator('[data-act="cancel"]').count() == 1
    if SHOTS is not None:
        page.screenshot(SHOTS / f"progress_recall_{'dark' if night else 'light'}.png", height=900)


def test_nothing_left_and_the_picker_and_the_empty_map(make_page) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s1 = section(10, "3.1", [note("x.a", 1)])
    done = {1: NoteProgress(stage=LEARNED, handed_off=True)}
    ctl = ProgressController([course([s1])], done)
    draw(page, ctl, False)
    assert page.page.locator("tr.next").count() == 0
    assert page.page.locator('[data-act="learn_next"]').is_disabled()
    assert page.page.locator('tr [data-act="learn"]').is_disabled()
    # two courses: a picker
    c2 = course([section(11, "1.1", [note("z.a", 7)])])
    c2 = type(c2)(2, "Algebra II", c2.sections, c2.states, c2.notes)
    two = ProgressController([course([s1]), c2], done)
    draw(page, two, False)
    assert page.page.locator("select option").count() == 2
    # no notes
    empty = ProgressController([], {})
    draw(page, empty, False)
    assert "No Math Path notes yet" in page.text()
    assert page.page.locator('[data-act="import"]').count() == 1


def test_long_titles_are_shortened_at_a_word() -> None:
    long = "Solve a quadratic equation using the quadratic formula (real solutions only)"
    assert progress_view.short_title(long) == "Solve a quadratic equation using…"
    assert progress_view.short_title("Short one") == "Short one"
