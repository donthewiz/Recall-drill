"""Smoke tests for ``math_path/ui``: every module imports and the windows run offscreen.

Runs headless on Qt's offscreen platform. Skipped where aqt isn't installed (CI's mathpath job
installs anki only) or Qt can't start without a display.
"""

from __future__ import annotations

import importlib
import importlib.util
import pkgutil
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from anki.collection import Collection
from scenes import make_course, recipe_dir

from math_path.anki_io import importer

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None, reason="aqt (Anki's GUI package) isn't installed"
)

UI_DIR = Path(__file__).resolve().parents[2] / "math_path" / "ui"
UI_MODULES = sorted(
    f"math_path.ui.{m.name}" for m in pkgutil.iter_modules([str(UI_DIR)]) if not m.ispkg
)


@pytest.mark.parametrize("module", UI_MODULES)
def test_ui_module_imports(module: str, qt_app: object) -> None:
    importlib.import_module(module)


def test_every_ui_module_is_listed() -> None:
    assert {
        "math_path.ui.context",
        "math_path.ui.entry",
        "math_path.ui.import_dialog",
        "math_path.ui.launch",
        "math_path.ui.learn_window",
        "math_path.ui.page_window",
        "math_path.ui.progress_window",
        "math_path.ui.review_bridge",
        "math_path.ui.review_window",
    } <= set(UI_MODULES)


@pytest.fixture
def env(qt_app: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    import aqt
    from stubs import FakeWeb, StubMw, SyncCollectionOp, SyncQueryOp

    from math_path.ui import (
        context,
        import_dialog,
        launch,
        learn_window,
        page_window,
        progress_window,
    )

    c = Collection(str(tmp_path / "collection.anki2"))
    stub = StubMw(c)
    monkeypatch.setattr(aqt, "mw", stub)
    for mod in (context, import_dialog, page_window, launch, learn_window, progress_window):
        monkeypatch.setattr(mod, "mw", stub, raising=False)
    monkeypatch.setattr(page_window, "AnkiWebView", FakeWeb)
    monkeypatch.setattr(import_dialog, "QueryOp", SyncQueryOp)
    monkeypatch.setattr(import_dialog, "CollectionOp", SyncCollectionOp)
    monkeypatch.setattr(learn_window, "CollectionOp", SyncCollectionOp)
    tips: list[str] = []
    monkeypatch.setattr(launch, "tooltip", tips.append)
    monkeypatch.setattr(learn_window, "tooltip", tips.append)
    monkeypatch.setattr(progress_window, "tooltip", tips.append)
    stub.tips = tips  # type: ignore[attr-defined]
    SyncQueryOp.col = c
    SyncCollectionOp.col = c
    yield stub
    c.close()


def _ctx(tmp_path: Path) -> Any:
    from math_path.ui.context import AddonContext

    return AddonContext("math_path", str(tmp_path / "user_files"))


def test_the_page_is_loaded_once_with_the_shell_and_the_scripts(env: Any, tmp_path: Path) -> None:
    from math_path.ui.import_dialog import ImportDialog

    w: Any = ImportDialog(_ctx(tmp_path))
    assert w.windowTitle() == "Math Path: import recipes"
    assert w.web.shell.startswith("<style>") and 'id="mp-root"' in w.web.shell
    assert w.web.html_args["js"][-1] == "/_addons/math_path/web/mp_page.js"
    assert "/_addons/math_path/web/mathlive/mathlive.min.js" in w.web.html_args["js"]
    assert w.web.html_args["css"] == ["/_addons/math_path/web/mp_page.css"]
    assert w.web.last_render()["night"] in (True, False)
    assert "Choose folder" in w.web.last_render()["html"]


def test_importing_a_folder_through_the_dialog(
    env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aqt.qt import QFileDialog

    from math_path.anki_io import notetype
    from math_path.ui import import_dialog

    make_course(env.col, sections=("3.1", "3.2"))  # 3.3-3.5 have no deck yet
    folder = recipe_dir(tmp_path)
    monkeypatch.setattr(QFileDialog, "getExistingDirectory", lambda *a, **k: str(folder))
    w: Any = import_dialog.ImportDialog(_ctx(tmp_path))
    w.web.bridge("mp:act:choose")
    state = w.ctrl.state
    assert state.stage == "review" and state.plan is not None
    assert len(state.plan.needing_deck) == 18  # 3.3 (10) + 3.4 (3) + 3.5 (5)
    html = w.web.last_render()["html"]
    assert "pick one" in html and "no deck matches" in html
    # The folder is remembered.
    assert w.ctx.storage().read_json("ui_state.json", {})["import_folder"] == str(folder)
    pick = int(env.col.decks.id("Pick") or 0)
    rid = state.plan.needing_deck[0].recipe.id  # type: ignore[union-attr]
    w.web.bridge(f"mp:select:pick:{rid}:{pick}")
    assert w.web.last_render()["texts"][f"pick:{rid}"] == str(pick)
    w.web.bridge("mp:act:import")
    assert w.ctrl.state.stage == "done"
    assert len(notetype.read_notes(env.col)) == 12 + 1  # 3.1 + 3.2 + the one picked
    assert "Added 13" in w.web.last_render()["html"]
    w.web.bridge("mp:act:close")
    assert not w.isVisible() and w not in w.ctx.windows


def test_a_window_cannot_be_closed_while_it_is_working(env: Any, tmp_path: Path) -> None:
    from math_path.ui.import_dialog import ImportDialog

    w: Any = ImportDialog(_ctx(tmp_path))
    w.show()
    w.ctrl.folder_chosen("x")  # scanning
    w.close()
    assert w.isVisible()
    w.ctrl.failed("stop")
    w.close()
    assert not w.isVisible()


def test_unrelated_bridge_messages_are_ignored(env: Any, tmp_path: Path) -> None:
    from math_path.ui.import_dialog import ImportDialog

    w: Any = ImportDialog(_ctx(tmp_path))
    n = len(w.web.evals)
    assert w.web.bridge("rd:enter") is None
    assert w.web.bridge("mp:unknown:x") is None
    assert len(w.web.evals) == n


def test_registration_wires_the_menu_and_the_web_exports(
    env: Any, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from aqt.qt import QMenu, QWidget

    from math_path import pages
    from math_path.ui import entry

    holder = QWidget()

    class Form:
        menuTools = QMenu(holder)

    env.form = Form()
    monkeypatch.setattr(entry, "mw", env)
    entry.register("math_path", str(tmp_path))
    assert env.addonManager.exports == [("math_path", pages.web_pattern())]
    submenu = [a for a in Form.menuTools.actions() if a.text() == "Math Path"][0].menu()
    assert submenu is not None
    shown = [a.text() for a in submenu.actions() if a.text()]
    assert shown == ["Progress…", "Learn next", "Import recipes…", "About Math Path"]
    ctx = entry.context()
    assert ctx is not None and ctx.progress_opener is not None
    from aqt import gui_hooks

    assert entry.on_show_question in gui_hooks.reviewer_did_show_question._hooks  # type: ignore[attr-defined]
    assert entry.on_js_message in gui_hooks.webview_did_receive_js_message._hooks  # type: ignore[attr-defined]
    gui_hooks.reviewer_did_show_question.remove(entry.on_show_question)
    gui_hooks.webview_did_receive_js_message.remove(entry.on_js_message)
    gui_hooks.profile_will_close.remove(entry.on_profile_will_close)


# -- the learn window -----------------------------------------------------------------------------


class SyncBank:
    """A problem source that builds on the spot (the real bank builds on a worker thread)."""

    def __init__(self) -> None:
        from drive import sequential_problems

        self.get = sequential_problems()
        self.prepared: list[str] = []

    def prepare(self, recipe: Any) -> None:
        self.prepared.append(recipe.id)

    def take(self, recipe: Any) -> Any:
        return self.get(recipe)


def _course(env: Any, tmp_path: Path, limit: int | None = None) -> list[Any]:
    from math_path.anki_io import courses

    make_course(env.col)
    files = importer.scan_folder(recipe_dir(tmp_path, limit=limit))
    importer.apply_import(env.col, importer.plan_import(env.col, files))
    return courses.read_courses(env.col)


def _learn_ctx(tmp_path: Path) -> Any:
    ctx = _ctx(tmp_path)
    ctx.bank = SyncBank()
    return ctx


def _open_next(env: Any, ctx: Any) -> Any:
    from math_path.ui import launch

    assert launch.learn_next(ctx)
    return next(w for w in ctx.windows if type(w).__name__ == "LearnWindow")


def test_learn_next_opens_a_session_on_the_next_section(env: Any, tmp_path: Path) -> None:
    _course(env, tmp_path)
    ctx = _learn_ctx(tmp_path)
    w = _open_next(env, ctx)
    s = w.session
    assert [i.note.recipe_id for i in s.items][0].startswith("ca.")
    assert len(s.items) == 3 and w.windowTitle().startswith("Math Path: learn 3.1")
    import re

    dots = re.findall(r'class="mp-dot(?: [a-z]+)?"', w.web.last_render()["html"])
    assert ctx.bank.prepared and len(dots) == 3
    assert "Worked example" in w.web.last_render()["html"].replace(
        "Worked example", "Worked example"
    )
    # a second "Learn next" brings the same window forward
    from math_path.ui import launch

    assert launch.learn_next(ctx) and len([x for x in ctx.windows if x is w]) == 1
    assert len(ctx.windows) == 1


def test_nothing_to_learn_and_no_notes_say_so(env: Any, tmp_path: Path) -> None:
    from math_path.progress import LEARNED, NoteProgress, ProgressStore
    from math_path.ui import launch

    ctx = _learn_ctx(tmp_path)
    assert not launch.learn_next(ctx) and "No Math Path notes yet" in env.tips[-1]
    (course,) = _course(env, tmp_path)
    store = ProgressStore(ctx.storage())
    for n in course.notes:
        store.put(n.nid, NoteProgress(stage=LEARNED, handed_off=True))
    assert not launch.learn_next(ctx) and "Nothing to learn" in env.tips[-1]
    assert ctx.windows == []


def test_a_session_through_the_window_and_the_handoff_to_anki(env: Any, tmp_path: Path) -> None:
    from drive import solve

    from math_path.anki_io import notetype
    from math_path.session import SUMMARY

    _course(env, tmp_path)
    ctx = _learn_ctx(tmp_path)
    w = _open_next(env, ctx)
    s = w.session
    guard = 0
    while s.screen != SUMMARY and guard < 80:
        guard += 1
        solve(s)
        if s.screen == "result":
            w.web.bridge("mp:act:next")
        w._sync_timer()
        if s.learned_notes and s.screen == "result":
            break
    assert s.screen == SUMMARY  # the last Next ended the session and started the handoff
    learned = list(s.summary().handed_off)
    assert len(learned) == 3 and s.learned_notes == ()
    html = w.web.last_render()["html"]
    assert "handed to Anki" in html
    notes = {n.nid: n for n in notetype.read_notes(env.col)}
    for nid in learned:
        assert notes[nid].learned_tag
    assert env.col.undo_status().undo == "Math Path: hand off"
    lines = ctx.storage().read_jsonl("history.jsonl")
    assert lines[-1]["type"] == "handoff" and lines[-1]["nids"] == learned
    assert any(line["type"] == "problem" for line in lines)


def _learn_one(env: Any, tmp_path: Path) -> tuple[Any, Any, int]:
    """A window whose first recipe is one solo from Learned."""
    from math_path.course_model import next_section, session_notes
    from math_path.progress import SOLO, NoteProgress, ProgressStore

    (course,) = _course(env, tmp_path)
    ctx = _learn_ctx(tmp_path)
    store = ProgressStore(ctx.storage())
    section = next_section(course, store.all(), ctx.config())
    assert section is not None
    first = session_notes(section, course, store.all(), ctx.config())[0]
    store.put(first.nid, NoteProgress(stage=SOLO, solo_clean=1))
    w = _open_next(env, ctx)
    assert w.session.items[0].note.nid == first.nid
    return w, ctx, first.nid


def test_closing_after_a_recipe_was_learned_asks_to_hand_it_off(
    env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drive import solve

    from math_path.anki_io import notetype

    w, ctx, nid = _learn_one(env, tmp_path)
    w.show()
    solve(w.session)
    assert w.session.learned_notes == (nid,)
    answers: list[Any] = [None, False, True]
    asked: list[int] = []
    monkeypatch.setattr(w, "_ask_handoff", lambda: (asked.append(1), answers.pop(0))[1])
    w.close()  # Cancel: stays open
    assert w.isVisible() and asked == [1]
    w.close()  # "Not now": closes, the recipe stays learned but not handed off
    assert not w.isVisible()
    note = next(n for n in notetype.read_notes(env.col) if n.nid == nid)
    assert not note.learned_tag
    w2 = _open_next(env, ctx)  # next time the pending handoff comes along
    assert w2.session.pending == (nid,) and w2.session.learned_notes == (nid,)
    w2.show()
    monkeypatch.setattr(w2, "_ask_handoff", lambda: True)  # "Hand off": hands off, then closes
    w2.close()
    from aqt.qt import QApplication

    QApplication.processEvents()
    assert not w2.isVisible()
    assert next(n for n in notetype.read_notes(env.col) if n.nid == nid).learned_tag


def test_end_session_asks_the_same_question(
    env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from drive import solve

    from math_path.session import SUMMARY

    w, _ctx, nid = _learn_one(env, tmp_path)
    solve(w.session)
    monkeypatch.setattr(w, "_ask_handoff", lambda: None)
    w.web.bridge("mp:act:end")
    assert w.session.screen != SUMMARY  # Cancel keeps going
    monkeypatch.setattr(w, "_ask_handoff", lambda: True)
    w.web.bridge("mp:act:end")
    assert w.session.screen == SUMMARY and w.session.summary().handed_off == (nid,)


def test_escape_closes_the_help_text_and_never_the_learn_window(env: Any, tmp_path: Path) -> None:
    from math_path.progress import SOLO, NoteProgress, ProgressStore

    _course(env, tmp_path)
    ctx = _learn_ctx(tmp_path)
    w = _open_next(env, ctx)
    w.show()
    store = ProgressStore(ctx.storage())
    store.put(w.session.items[0].note.nid, NoteProgress(stage=SOLO))
    w.close()
    w = _open_next(env, ctx)
    w.show()
    w.web.bridge("mp:act:help:hint")
    assert w.session.run is not None and w.session.run.help_open
    w.reject()  # Qt's Esc, with the focus outside the page
    assert w.isVisible() and not w.session.run.help_open
    w.web.bridge("mp:act:help:hint")
    w.web.bridge("mp:esc:")  # the page's own Esc
    assert w.isVisible() and not w.session.run.help_open


def test_escape_closes_the_import_dialog(env: Any, tmp_path: Path) -> None:
    from math_path.ui.import_dialog import ImportDialog

    d: Any = ImportDialog(_ctx(tmp_path))
    d.show()
    d.reject()
    assert not d.isVisible()


def test_a_screen_that_is_preparing_polls_until_the_problem_is_ready(
    env: Any, tmp_path: Path
) -> None:
    from math_path.problem import ProblemBank
    from math_path.session import PREPARING, RUN

    _course(env, tmp_path)
    ctx = _ctx(tmp_path)
    ctx.bank = ProblemBank()
    w = _open_next_noprep(env, ctx)
    if w.session.screen == PREPARING:
        assert "Preparing" in w.web.last_render()["html"] and w._timer.isActive()
    for _ in range(300):
        w._poll()
        if w.session.screen == RUN:
            break
        import time

        time.sleep(0.05)
    assert w.session.screen == RUN and not w._timer.isActive()
    assert "Worked example" in w.web.last_render()["html"]


def _open_next_noprep(env: Any, ctx: Any) -> Any:
    return _open_next(env, ctx)


def test_the_progress_button_only_shows_when_there_is_a_map_to_open(
    env: Any, tmp_path: Path
) -> None:
    _course(env, tmp_path)
    ctx = _learn_ctx(tmp_path)
    w = _open_next(env, ctx)
    assert 'data-act="progress"' not in w.web.last_render()["html"]
    opened: list[int] = []
    ctx.progress_opener = lambda: opened.append(1)
    w.redraw()
    assert 'data-act="progress"' in w.web.last_render()["html"]
    w.web.bridge("mp:act:progress")
    assert opened == [1]


@pytest.mark.parametrize(
    ("label", "answer"), [("Hand off", True), ("Not now", False), ("Cancel", None)]
)
def test_the_handoff_question_has_three_answers_and_hand_off_is_the_default(
    env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, label: str, answer: bool | None
) -> None:
    from aqt.qt import QMessageBox
    from drive import solve

    w, _ctx, nid = _learn_one(env, tmp_path)
    solve(w.session)
    seen: dict[str, Any] = {}

    def fake_exec(self: QMessageBox) -> int:
        seen["text"] = self.text()
        default = self.defaultButton()
        seen["default"] = default.text() if default is not None else ""
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(
        QMessageBox,
        "clickedButton",
        lambda self: next(b for b in self.buttons() if b.text() == label),
    )
    assert w._ask_handoff() is answer
    assert seen["text"] == "Hand off the 1 learned problem now?" and seen["default"] == "Hand off"


# -- the progress window ---------------------------------------------------------------------------


def _tag_recall(env: Any, number: str, total: int, drilled: int) -> None:
    """``total`` Recall Drill cards in section ``number``'s deck, ``drilled`` of them drilled."""
    from anki.decks import DeckId

    from math_path.anki_io.courses import SECTION_NUMBER  # noqa: F401

    deck = next(
        int(d["id"])
        for d in env.col.decks.all()
        if str(d["name"]).split("::")[-1].startswith(number + " ")
    )
    model = env.col.models.by_name("Basic")
    assert model is not None
    for i in range(total):
        note = env.col.new_note(model)
        note["Front"], note["Back"] = f"q{number}-{i}", "a"
        note.tags = ["rd::drilled"] if i < drilled else ["rd::drill"]
        env.col.add_note(note, DeckId(deck))


def _open_progress(env: Any, ctx: Any) -> Any:
    from math_path.ui.progress_window import ProgressWindow, open_progress

    w = open_progress(ctx)
    assert isinstance(w, ProgressWindow)
    return w


def test_the_progress_window_shows_the_map_and_learns_a_section(
    env: Any, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from math_path.ui import launch

    _course(env, tmp_path)
    _tag_recall(env, "3.3", 52, 12)
    ctx = _learn_ctx(tmp_path)
    ctx.progress_opener = lambda: None
    w = _open_progress(env, ctx)
    html = w.web.last_render()["html"]
    assert w.windowTitle() == "Math Path: progress"
    assert "3.1 The Complex Numbers" in html and "NEXT" in html
    assert "12 / 52" in html  # the Recall cell; the amber line waits for a click on Learn
    assert "needs " in html  # a later recipe waits on an earlier one
    assert open_progress_again(ctx) is w  # one window
    # Learn on the NEXT section opens a learn session
    w.web.bridge("mp:act:learn_next")
    learn = [x for x in ctx.windows if type(x).__name__ == "LearnWindow"]
    assert len(learn) == 1
    # a second Learn does not open another session
    w.web.bridge("mp:act:learn_next")
    assert len([x for x in ctx.windows if type(x).__name__ == "LearnWindow"]) == 1
    assert "Finish or close" in env.tips[-1]
    assert launch.remembered_course(ctx, [c for c in w.ctl.courses]) is not None
    w.web.bridge("mp:act:close")
    assert w not in ctx.windows


def open_progress_again(ctx: Any) -> Any:
    from math_path.ui.progress_window import open_progress

    return open_progress(ctx)


def test_learn_on_a_section_with_undrilled_recall_asks_first(env: Any, tmp_path: Path) -> None:
    _course(env, tmp_path)
    _tag_recall(env, "3.1", 5, 1)
    ctx = _learn_ctx(tmp_path)
    w = _open_progress(env, ctx)
    row = w.ctl.model().rows[0]  # type: ignore[union-attr]
    w.web.bridge(f"mp:act:learn:{row.section.did}")
    assert not [x for x in ctx.windows if type(x).__name__ == "LearnWindow"]
    assert "Learn anyway" in w.web.last_render()["html"]
    w.web.bridge("mp:act:cancel")
    assert "Learn anyway" not in w.web.last_render()["html"]
    w.web.bridge(f"mp:act:learn:{row.section.did}")
    w.web.bridge(f"mp:act:learn_anyway:{row.section.did}")
    assert [x for x in ctx.windows if type(x).__name__ == "LearnWindow"]


def test_the_progress_window_follows_changes_in_anki(env: Any, tmp_path: Path) -> None:
    from aqt import gui_hooks

    from math_path.progress import LEARNED, NoteProgress, ProgressStore

    (course,) = _course(env, tmp_path)
    ctx = _learn_ctx(tmp_path)
    w = _open_progress(env, ctx)
    before = w.web.last_render()["html"]
    assert "In Anki" not in before
    store = ProgressStore(ctx.storage())
    for n in course.notes:
        store.put(n.nid, NoteProgress(stage=LEARNED, handed_off=True))
    gui_hooks.operation_did_execute(object(), None)  # type: ignore[arg-type]
    assert "In Anki" in w.web.last_render()["html"]
    w.close()
    n = len(w.web.evals)
    gui_hooks.operation_did_execute(object(), None)  # type: ignore[arg-type]
    assert len(w.web.evals) == n  # a closed window no longer listens


def test_the_progress_window_with_no_notes_offers_the_import(env: Any, tmp_path: Path) -> None:
    ctx = _learn_ctx(tmp_path)
    w = _open_progress(env, ctx)
    assert "No Math Path notes yet" in w.web.last_render()["html"]
    w.web.bridge("mp:act:refresh")
    w.close()
