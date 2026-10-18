"""Typing into the page through a real round trip (bug #11).

The page's ``pycmd`` is replaced by an async bridge like Anki's: each command goes to Python
(``LearnSession.command``), and the JS Python answers with (``pages.redraw_call``, the code
``PageWindow`` uses) runs in the page afterwards. The older tests never got real focus events or a
round trip, so a redraw that destroyed the field being typed in went unnoticed.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from drive import key_text, new_session, new_store, solve
from page_harness import Browser, needs_playwright
from recipe_files import CH03, load

from math_path import pages
from math_path.pages import PageView
from math_path.progress import FADED, PLAN, SOLO, NoteProgress
from math_path.session import RESULT, LearnSession
from math_path.views import learn_view

pytestmark = needs_playwright

FACTORING = load(CH03 / "ca.quad.solve_factoring.json")
DELAYS = [0, 30]


class Trip:
    """A page wired to a session the way ``PageWindow`` wires it."""

    def __init__(self, page: Browser, session: LearnSession) -> None:
        self.page = page
        self.s = session
        self.shown: pages.Shown | None = None
        self.log: list[str] = []
        self.sent: list[str] = []
        page.page.expose_function("__py", self.handle)
        page.page.evaluate(
            "window.pycmd = function (c) { window.__cmds.push(c);"
            " window.__py(c).then(function (js) { if (js) { (0, eval)(js); } }); }"
        )
        self.show(self.redraw(keep=False))
        page.settle()

    def view(self) -> PageView:
        sc = learn_view.render(self.s)
        return PageView(sc.html, sc.fields, sc.texts, sc.readonly, sc.focus, False)

    def redraw(self, keep: bool) -> str:
        js, self.shown = pages.redraw_call(self.view(), keep, self.shown)
        if js is not None:
            self.sent.append(js)
        return js or ""

    def show(self, js: str) -> None:
        self.page.page.evaluate(js.rstrip(";"))
        self.wait(50)

    def handle(self, cmd: str) -> str:
        self.log.append(cmd)
        parsed = pages.parse_command(cmd)
        if parsed is None:
            return ""
        self.s.command(parsed)
        return self.redraw(parsed.kind in pages.KEEP_KINDS)

    def wait(self, ms: int = 300) -> None:
        self.page.page.wait_for_timeout(ms)

    def click_field(self, fid: str) -> None:
        self.page.page.click(f'math-field[data-id="{fid}"]')
        self.wait()

    def value(self, fid: str) -> str:
        return str(self.page.page.evaluate(f"mp.fieldValue({fid!r})"))

    def active(self) -> str:
        return str(
            self.page.page.evaluate(
                "(() => { const a = document.activeElement;"
                " return a && a.getAttribute ? a.getAttribute('data-id') || '' : ''; })()"
            )
        )

    def type(self, text: str, delay: int) -> None:
        self.page.page.keyboard.type(text, delay=delay)
        self.wait()

    def pad(self, key: str) -> None:
        self.page.page.click(f"#mp-pad-{key}")
        self.wait(100)

    def commands(self, kind: str) -> list[str]:
        return [c for c in self.log if c.startswith(f"mp:{kind}:")]


def trip(
    make_page: Any, tmp_path: Path, stage: str, level: int = 1, recipe: Any = FACTORING
) -> Trip:
    st = new_store(tmp_path)
    st.put(100, NoteProgress(stage=stage, faded_level=level))
    s, _st, _h = new_session(tmp_path, [recipe], st)
    return Trip(make_page(), s)


@pytest.mark.parametrize("delay", DELAYS)
def test_a_faded_step_field_takes_what_is_typed(make_page, tmp_path: Path, delay: int) -> None:  # type: ignore[no-untyped-def]
    t = trip(make_page, tmp_path, FADED)
    t.click_field("s3")
    t.type("(x+2)(x+3)=0", delay)
    assert t.value("s3") == "(x+2)(x+3)=0"
    assert t.active() == "s3"
    assert t.s.run is not None and t.s.run.fields["s3"] == "(x+2)(x+3)=0"


def test_the_final_answer_takes_what_is_typed(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    t = trip(make_page, tmp_path, FADED)
    t.click_field("ans")
    t.type("-2, -3", 0)
    assert t.value("ans") == "-2,-3"
    assert t.active() == "ans"


def test_focusing_a_field_does_not_start_a_loop(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    t = trip(make_page, tmp_path, FADED)
    t.click_field("s3")
    t.type("x", 0)
    n = len(t.log)
    t.wait(500)
    assert len(t.log) == n  # nothing new arrives once typing stops
    t.log.clear()
    t.click_field("ans")
    t.wait(500)
    assert len(t.commands("focus")) <= 2
    assert t.active() == "ans"


@pytest.mark.parametrize("delay", DELAYS)
def test_a_correction_after_a_wrong_step_check_keeps_every_key(  # type: ignore[no-untyped-def]
    make_page, tmp_path: Path, delay: int
) -> None:
    """After a wrong check the red note is on screen; click back into the field, select what is
    typed and type the correction over the selection at once (no Backspace, no wait). The focus
    and field messages and the redraws they cause race with these keys: every key must land."""
    t = trip(make_page, tmp_path, FADED)
    t.click_field("s2")
    t.type("x=1", 0)
    t.page.page.click('[data-act="check_step"][data-arg="2"]')
    t.wait()
    assert "Not right yet." in t.page.text()
    assert "mp:act:check_step:2" in t.log
    t.page.page.click('math-field[data-id="s2"]')
    t.page.page.keyboard.press("Control+A")
    t.page.page.keyboard.type("2x+3=0;x+6=0", delay=delay)
    t.wait()
    assert t.value("s2") == "2x+3=0;x+6=0"
    assert "Not right yet." not in t.page.text()
    assert t.active() == "s2"
    assert t.s.run is not None and t.s.run.fields["s2"] == "2x+3=0;x+6=0"


def test_the_palette_keys_all_land(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    t = trip(make_page, tmp_path, FADED)
    t.click_field("ans")
    t.pad("sqrt")
    t.type("108", 0)
    t.pad("right")
    t.pad("i")
    assert t.value("ans") == "\\sqrt{108}i"
    assert t.active() == "ans"


def test_the_plan_box_takes_what_is_typed(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    t = trip(make_page, tmp_path, PLAN)
    t.page.page.click('input[data-id="plan0"]')
    t.wait()
    t.type("move the 6 to the other side", 0)
    assert t.page.page.input_value('input[data-id="plan0"]') == "move the 6 to the other side"
    assert t.active() == "plan0"
    assert t.s.run is not None and t.s.run.plan_typed[0] == "move the 6 to the other side"


def test_enter_in_a_field_checks_it_after_its_value(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    t = trip(make_page, tmp_path, FADED)
    t.click_field("ans")
    t.type("x", 0)
    t.log.clear()
    t.page.page.keyboard.press("Enter")
    t.wait()
    assert t.log[:2] == ["mp:field:ans:x", "mp:enter:ans"]


def test_a_full_redraw_still_starts_a_new_problem_with_empty_fields(  # type: ignore[no-untyped-def]
    make_page, tmp_path: Path
) -> None:
    t = trip(make_page, tmp_path, FADED)
    solve(t.s)  # Python holds typed values; the session reaches the result screen
    assert t.s.screen == RESULT
    t.show(t.redraw(keep=False))
    t.page.page.click('[data-act="next"]')
    t.wait()
    assert t.s.screen != RESULT
    assert t.page.page.locator("math-field").count() > 0
    for mf in t.page.page.locator("math-field").all():
        assert mf.evaluate("e => e.value") == ""


def _enter(t: Trip, text: str) -> None:
    """Type keyboard ``text`` the way a learner would: ``sqrt(`` is the palette's root key, the
    closing bracket is its right arrow, everything else is a key press."""
    depth = 0
    i = 0
    while i < len(text):
        if text.startswith("sqrt(", i):
            t.pad("sqrt")
            depth += 1
            i += 5
        elif text[i] == ")" and depth:
            t.pad("right")
            depth -= 1
            i += 1
        else:
            if text[i] != " ":
                t.type(text[i], 0)
            i += 1


def test_a_whole_faded_problem_through_the_round_trip(make_page, tmp_path: Path) -> None:  # type: ignore[no-untyped-def]
    recipe = load(CH03 / "ca.cx.express_i.json")
    t = trip(make_page, tmp_path, FADED, 1, recipe)
    run = t.s.run
    assert run is not None
    typed: dict[str, str] = {}
    for st in run.steps:
        if st.blank:
            fid = f"s{st.index}"
            t.click_field(fid)
            _enter(t, run.problem.steps[st.index].result)
            typed[fid] = t.value(fid)
            assert typed[fid] and t.active() == fid
            t.page.page.click(f'[data-act="check_step"][data-arg="{st.index}"]')
            t.wait()
            assert run.steps[st.index].ok is True, (fid, typed[fid])
            assert t.value(fid) == typed[fid]
    t.click_field("ans")
    _enter(t, key_text(run.problem))
    typed["ans"] = t.value("ans")
    t.page.page.keyboard.press("Enter")  # checks the answer
    t.wait(500)
    assert t.s.screen == RESULT, t.page.text()
    for fid, latex in typed.items():
        assert run.fields[fid] == latex
    t.page.page.click('[data-act="next"]')
    t.wait()
    assert t.s.screen != RESULT


@pytest.mark.parametrize("focus_first", [True, False], ids=["field-focused", "nothing-focused"])
@pytest.mark.parametrize("delay", DELAYS)
@pytest.mark.parametrize("stage", [FADED, SOLO])
def test_the_sqrt_key_keeps_the_digits_inside_the_root(  # type: ignore[no-untyped-def]
    make_page, tmp_path: Path, stage: str, delay: int, focus_first: bool
) -> None:
    """Click the root key and type straight away (no wait): the digits go inside the root (the
    recording of the first real Anki check showed them right of an empty box)."""
    t = trip(make_page, tmp_path, stage)
    if focus_first:
        t.click_field("ans")
    # the key goes to the field that last had the focus, else to the page's first field
    target = t.active() or str(
        t.page.page.evaluate("document.querySelector('math-field').getAttribute('data-id')")
    )
    t.page.page.click("#mp-pad-sqrt")
    t.page.page.keyboard.type("108", delay=delay)
    t.wait()
    assert t.value(target) == "\\sqrt{108}"
    assert t.active() == target
    assert t.s.run is not None and t.s.run.fields[target] == "\\sqrt{108}"
