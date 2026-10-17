"""The learn window's screens drawn in a real browser, dark and light: every stage, the result and
summary screens, typing with the palette, the help ladder, the choice buttons, the graph answer."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest
from drive import new_session, new_store, solve, type_answer
from page_harness import Browser, needs_playwright
from recipe_files import CH03, V2, load

from math_path.pages import Command, PageView
from math_path.progress import FADED, PLAN, SOLO, NoteProgress
from math_path.run import ANSWER_FIELD
from math_path.session import LearnSession
from math_path.views import learn_view

pytestmark = needs_playwright

SHOTS = Path(os.environ["MP_SHOTS"]) if os.environ.get("MP_SHOTS") else None
"""Set MP_SHOTS to a folder to also save screenshots (for looking at, never committed)."""

FACTORING = load(CH03 / "ca.quad.solve_factoring.json")
SQUARE_ROOT = load(CH03 / "ca.quad.solve_square_root.json")
GRAPH = load(CH03 / "ca.quadgraph.graph.json")
NO_SOLUTION = load(V2 / "ca.rat.no_solution.json")
INEQ = load(CH03 / "ca.abs.solve_ineq_greater.json")


def draw(page: Browser, s: LearnSession, night: bool = False) -> None:
    screen = learn_view.render(s)
    page.draw(
        PageView(screen.html, screen.fields, screen.texts, screen.readonly, screen.focus, night)
    )
    page.settle()


def shot(page: Browser, name: str, night: bool) -> None:
    if SHOTS is not None:
        page.screenshot(SHOTS / f"{name}_{'dark' if night else 'light'}.png", height=1200)


def staged(tmp_path: Path, stage: str, level: int = 1, **kw: Any) -> LearnSession:
    st = new_store(tmp_path)
    st.put(100, NoteProgress(stage=stage, faded_level=level, **kw))
    s, _st, _h = new_session(tmp_path, [FACTORING], st)
    return s


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_every_stage_draws(make_page, tmp_path: Path, night: bool) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page(night=night)
    s, _st, _h = new_session(tmp_path, [FACTORING])
    draw(page, s, night)  # Study
    text = page.text()
    assert "Solve a quadratic equation by factoring" in text and "Study" in text
    assert "Worked example" in text and "write it in standard form" in text
    assert "The answer" in text and "Your answer" not in text
    assert page.page.locator("mjx-container").count() > 5  # the worked results are typeset
    assert "\\(" not in text and "\\frac" not in text  # nothing raw is left on screen
    shot(page, "study", night)
    page.page.click('[data-act="next"]')
    assert "mp:act:next" in page.cmds()
    solve(s)  # to Faded level 1
    draw(page, s, night)
    assert "Faded · level 1" in page.text()
    assert page.page.locator("math-field").count() == 3  # two blanks and the answer
    assert page.page.locator('[data-act="check_step"]').count() == 2
    shot(page, "faded1", night)
    solve(s)
    s.command(Command("act", "next"))
    draw(page, s, night)
    assert page.page.locator("math-field").count() == 5  # four blanks and the answer
    shot(page, "faded2", night)
    solve(s)
    s.command(Command("act", "next"))
    draw(page, s, night)  # Plan
    assert "Say the plan" in page.text() and page.page.locator("input.mp-input").count() == 5
    shot(page, "plan", night)
    solve(s)
    s.command(Command("act", "next"))
    draw(page, s, night)  # Solo
    assert page.page.locator("math-field").count() == 1
    assert page.page.locator('[data-act="choose"]').count() == 2  # both buttons, every solve task
    shot(page, "solo", night)
    s.command(Command("act", "end"))


@pytest.mark.parametrize("night", [False, True], ids=["light", "dark"])
def test_result_and_summary_screens(make_page, tmp_path: Path, night: bool) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page(night=night)
    s = staged(tmp_path, SOLO, solo_clean=1)
    solve(s)  # the second solo: learned
    draw(page, s, night)
    text = page.text()
    assert "Learned!" in text and "Your answer" in text and "The answer" in text
    assert "Worked solution" in text and "no wrong tries and no help" in text
    assert page.page.locator('[data-act="next"]').count() == 1
    shot(page, "result_learned", night)
    s.command(Command("act", "next"))
    draw(page, s, night)
    text = page.text()
    assert "1 recipe learned" in text and "Handing 1 problem to Anki" in text
    s.handoff_done([100], [555])
    draw(page, s, night)
    assert "1 problem handed to Anki" in page.text() and "Undo" in page.text()
    shot(page, "summary", night)
    s2 = staged(tmp_path / "b", FADED, 2)
    s2.end_early()
    draw(page, s2, night)
    assert "No recipe reached Learned this time" in page.text()
    assert "1 recipe not learned yet" in page.text()
    s2.handoff_failed("boom")
    draw(page, s2, night)
    assert "The handoff failed" not in page.text()  # nothing was learned: no failure to show


def test_a_wrong_answer_shows_the_named_mistake_as_typeset_math(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = staged(tmp_path, SOLO)
    assert s.run is not None
    mk = FACTORING.mistakes[0]
    from drive import tex_of

    wrong = s.run.problem.env  # a wrong answer: the first named mistake's
    from math_path import loader

    text = loader.load().validator.fill(mk.rule["answer_equals"], wrong)
    s.command(Command("field", ANSWER_FIELD, tex_of(text)))
    s.command(Command("act", "check"))
    draw(page, s)
    assert "Not right yet." in page.text() and mk.name in page.text()
    assert page.page.locator(".mp-note.warn mjx-container").count() >= 1
    assert page.page.locator("math-field").evaluate("e => e.value") != ""  # what was typed stays
    shot(page, "wrong", False)


def test_the_help_row_climbs_one_rung_at_a_time(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = staged(tmp_path, SOLO)
    draw(page, s)
    enabled = lambda: [  # noqa: E731
        b.get_attribute("data-arg")
        for b in page.page.locator('[data-act="help"]:not([disabled])').all()
    ]
    assert enabled() == ["hint", "answer"]
    page.page.click('[data-act="help"][data-arg="hint"]')
    s.command(Command("act", "help", "hint"))  # the window would have done this on the message
    draw(page, s)
    assert enabled() == ["why", "answer"] and "Hint" in page.text()
    s.command(Command("act", "help", "why"))
    s.command(Command("act", "help", "show"))
    draw(page, s)
    assert "Step" in page.text() and "Help" in page.text()
    shot(page, "help", False)
    s.command(Command("esc"))
    draw(page, s)
    assert page.page.locator(".mp-card .mp-label", has_text="Help").count() == 0
    s.command(Command("act", "help", "answer"))
    draw(page, s)
    assert "the answer was shown" in page.text()
    assert page.page.locator("math-field").count() == 0  # a finished problem has no field


def test_a_graph_recipe_asks_for_a_shape_and_two_points(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    st = new_store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO))
    s, _st, _h = new_session(tmp_path, [GRAPH], st)
    draw(page, s)
    assert page.page.locator("button.mp-pill").count() == 3
    assert page.page.locator("math-field").count() == 2
    assert page.page.locator('[data-act="choose"]').count() == 0  # not a solve task
    s.command(Command("act", "shape", "parabola"))
    draw(page, s)
    assert page.page.locator("button.mp-pill.on").inner_text() == "Parabola"
    assert s.run is not None
    type_answer(s.run)
    s.command(Command("act", "check"))
    draw(page, s)
    assert "Right" in page.text() or "learned" in page.text().lower() or "1 of 2" in page.text()
    shot(page, "graph", False)


def test_the_choice_buttons_and_units(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    st = new_store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO))
    s, _st, _h = new_session(tmp_path, [NO_SOLUTION], st)
    draw(page, s)
    page.page.click('[data-act="choose"][data-arg="none"]')
    assert "mp:act:choose:none" in page.cmds()
    units = load(CH03 / "ca.quad.rectangle_dimensions.json")
    s2, _st2, _h2 = new_session(tmp_path / "u", [units], st)
    draw(page, s2)
    assert page.page.locator(".mp-units").inner_text() == "ft"


def test_the_plan_screen_marks_each_box_and_shows_the_right_name(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = staged(tmp_path, PLAN)
    assert s.run is not None
    names = [x.name for x in s.run.problem.steps]
    for i, name in enumerate(names):
        s.command(Command("text", f"plan{i}", name if i != 2 else "nonsense"))
    s.command(Command("act", "check"))
    draw(page, s)
    assert page.page.locator("input.mp-input.ok").count() == 4
    assert page.page.locator("input.mp-input.bad").count() == 1
    assert names[2] in page.text() and "Type it to go on" in page.text()
    assert page.page.locator('input[data-id="plan0"]').input_value() == names[0]
    assert page.page.locator('input[data-id="plan2"]').input_value() == ""
    page.page.fill('input[data-id="plan2"]', "x")
    assert "mp:text:plan2:x" in page.cmds()
    shot(page, "plan_checked", False)


def test_enter_and_escape_reach_python_from_a_step_field(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = staged(tmp_path, FADED, 2)
    draw(page, s)
    page.page.evaluate("mp.focus('s0')")
    page.page.wait_for_timeout(150)
    page.clear_cmds()
    page.page.keyboard.type("x")
    page.page.keyboard.press("Enter")
    cmds = page.cmds()
    assert "mp:enter:s0" in cmds and any(c.startswith("mp:field:s0:") for c in cmds)
    page.page.keyboard.press("Escape")
    assert "mp:esc:" in page.cmds()


def test_a_redraw_keeps_what_was_typed_and_the_focus(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    page: Browser = make_page()
    s = staged(tmp_path, FADED, 2)
    draw(page, s)
    page.page.evaluate("mp.focus('s1')")
    page.page.wait_for_function(
        "document.activeElement && document.activeElement.getAttribute('data-id') === 's1'",
        timeout=5000,
    )
    page.page.keyboard.type("ab")
    page.page.wait_for_function("mp.fieldValue('s1') === 'ab'", timeout=5000)
    for c in page.cmds():  # the window feeds every field message back into the session
        if c.startswith("mp:field:") or c.startswith("mp:focus:"):
            from math_path.pages import parse_command

            cmd = parse_command(c)
            assert cmd is not None
            s.command(cmd)
    draw(page, s)
    page.page.wait_for_function("mp.fieldValue('s1') === 'ab'", timeout=5000)
    page.page.wait_for_function(
        "document.activeElement && document.activeElement.getAttribute('data-id') === 's1'",
        timeout=5000,
    )
