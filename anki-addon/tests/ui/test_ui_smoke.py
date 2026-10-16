"""Smoke tests for ``recalldrill/ui``: every module imports, and the windows run offscreen.

Runs headless on Qt's offscreen platform. Skipped where aqt isn't installed
(CI's addon-anki job installs anki only) or Qt can't start without a display.
The windows themselves are checked by hand (the repo's docs/SMOKE.md, "Anki add-on").
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import pkgutil
from pathlib import Path
from typing import Any

import pytest

pytestmark = pytest.mark.skipif(
    importlib.util.find_spec("aqt") is None, reason="aqt (Anki's GUI package) isn't installed"
)

UI_DIR = Path(__file__).resolve().parents[2] / "recalldrill" / "ui"
UI_MODULES = sorted(
    f"recalldrill.ui.{m.name}" for m in pkgutil.iter_modules([str(UI_DIR)]) if not m.ispkg
)


@pytest.fixture(scope="module")
def qt_app() -> object:
    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from aqt.qt import QApplication
    except ImportError as exc:  # no Qt platform plugin / display
        pytest.skip(f"Qt can't start here: {exc}")
    return QApplication.instance() or QApplication([])


@pytest.fixture(autouse=True)
def _application_style_is_untouched() -> Any:
    """No window of ours may style the application (v0.5): Anki's own windows keep their look."""
    from aqt.qt import QApplication

    def sheet() -> str:
        app = QApplication.instance()
        return app.styleSheet() if isinstance(app, QApplication) else ""

    before = sheet()
    yield
    assert sheet() == before


def test_every_ui_module_is_listed() -> None:
    assert {
        "recalldrill.ui.about",
        "recalldrill.ui.context",
        "recalldrill.ui.drill_window",
        "recalldrill.ui.entry",
        "recalldrill.ui.handoff_dialog",
        "recalldrill.ui.mapping_dialog",
        "recalldrill.ui.setup_dialog",
        "recalldrill.ui.style",
        "recalldrill.ui.tuning_dialog",
        "recalldrill.ui.waiting_dialog",
    } <= set(UI_MODULES)


@pytest.mark.parametrize("module", UI_MODULES)
def test_ui_module_imports(module: str, qt_app: object) -> None:
    importlib.import_module(module)


def test_mapping_dialog_builds_offscreen(qt_app: object, tmp_path: Path) -> None:
    from recalldrill.anki_io.notetypes import NoteMapping, load_overrides
    from recalldrill.anki_io.panel import NoteTypeTemplates
    from recalldrill.storage import Storage
    from recalldrill.ui.mapping_dialog import MappingDialog

    st = Storage(tmp_path, "p")
    m = NoteMapping(
        ntid=5,
        template_ord=1,
        kind="standard",
        notetype_name="Basic Quizlet Extended",
        template_name="Reverse",
        answer_field=None,
        extra_field=None,
        ineligible=False,
        overridden=False,
        why="no candidate",
    )
    nt = NoteTypeTemplates(
        5,
        "Basic Quizlet Extended",
        "standard",
        ((0, "Normal"), (1, "Reverse")),
        ("FrontText", "BackText", "Notes"),
    )
    from aqt.qt import QWidget

    parent = QWidget()
    dialog = MappingDialog(parent, st, [m], [nt], (5, 1))
    dialog.answer.setCurrentText("FrontText")
    dialog.extra.setCurrentText("Notes")
    dialog._save()  # pyright: ignore[reportPrivateUsage]
    o = load_overrides(st)[(5, 1)]
    assert (o.answer_field, o.extra_field, o.ineligible) == ("FrontText", "Notes", False)
    assert dialog.saved


# -- the drill window, offscreen ------------------------------------------------
#
# QtWebEngine can't start on the offscreen platform (the process exits), so the
# web view is a stand-in that records what the window sends it, and ``mw`` is a
# stub with what the window and theme_manager read. Everything else is real:
# the controller, the keys, the timer, the buttons.


class _PM:
    def __init__(self) -> None:
        self.profile: dict[str, object] = {}
        self.name = "test"

    def reduce_motion(self) -> bool:
        return False

    def minimalist_mode(self) -> bool:
        return False


class _Progress:
    def timer(self, *_args: object, **_kwargs: object) -> None:
        return None


class _MW:
    def __init__(self) -> None:
        self.pm = _PM()
        self.col = None
        self.progress = _Progress()

    def geometry(self) -> object:
        from aqt.qt import QRect

        return QRect(50, 50, 900, 700)

    def prepare_card_text_for_display(self, text: str) -> str:
        return text


@pytest.fixture
def window_env(qt_app: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> object:
    import aqt
    from aqt.qt import QWidget

    from recalldrill.ui import drill_window

    class FakeWeb(QWidget):
        def __init__(self, parent: QWidget | None = None, title: str = "") -> None:
            super().__init__(parent)
            self.evals: list[str] = []

        def set_bridge_command(self, fn: object, context: object) -> None:
            self.bridge = fn

        def stdHtml(self, body: str, **_kw: object) -> None:  # noqa: N802
            self.shell = body

        def eval(self, js: str) -> None:
            self.evals.append(js)

        def cleanup(self) -> None:
            pass

    stub = _MW()
    monkeypatch.setattr(aqt, "mw", stub)
    monkeypatch.setattr(drill_window, "mw", stub)
    monkeypatch.setattr(drill_window, "AnkiWebView", FakeWeb)
    return tmp_path


def _window(tmp_path: Path, deck: object = None, **cfg: object) -> object:
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "controller"))
    from controller_support import SHORT, Clock, config, source

    from recalldrill import sessions
    from recalldrill.addon_config import DEFAULT_CONFIG
    from recalldrill.controller import ControllerSettings
    from recalldrill.storage import Storage
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.drill_window import DrillWindow

    items = deck if deck is not None else SHORT
    st = Storage(tmp_path, "p")
    ctrl, store = sessions.start_session(
        st,
        key="deck-1",
        deck_items=items,  # type: ignore[arg-type]
        sources=[source(i) for i in range(len(items))],  # type: ignore[arg-type]
        config=config(**cfg),
        scope=sessions.scope_json(deck_id=1),
        select_options={},
        deck_settings={},
        hints=False,
        settings=ControllerSettings(deck_name="Ch 3"),
        now_ms=Clock(),
    )
    ctx = AddonContext("recall_drill", str(tmp_path))
    ctx.storage = lambda: st  # type: ignore[method-assign]
    ctx.config = lambda: DEFAULT_CONFIG  # type: ignore[method-assign]
    w = DrillWindow(ctx, ctrl, store)
    w.start()
    return w


def _key(w: object, key: object, ctrl: bool = False) -> None:
    from aqt.qt import QEvent, QKeyEvent, Qt

    mods = Qt.KeyboardModifier.ControlModifier if ctrl else Qt.KeyboardModifier.NoModifier
    w.keyPressEvent(QKeyEvent(QEvent.Type.KeyPress, key, mods))  # type: ignore[attr-defined]


def test_drill_window_keys_and_effects(window_env: Path) -> None:
    from aqt.qt import Qt

    w: Any = _window(window_env, encodeReps=1)
    assert w.windowTitle() == "Recall Drill: Ch 3" and w.check_btn.isVisible()
    assert w.web.evals[-1].startswith("rdRender(")

    # Esc reveals (and doesn't close).
    _key(w, Qt.Key.Key_Escape)
    assert w.ctrl.view().revealed and w.isVisible()
    w.reject()
    assert w.isVisible()

    # Enter submits; a correct answer dwells, then flashes and moves on.
    w.input.setText(w.ctrl.view().sub_text)
    _key(w, Qt.Key.Key_Return)
    assert w._dwell.isActive() and any("rdFlash(" in e for e in w.web.evals)
    w._flush_dwell()
    assert w.input.text() == "" and not w.ctrl.view().revealed

    # A wrong answer, then Ctrl+Enter counts it as correct.
    w.input.setText("nope")
    _key(w, Qt.Key.Key_Enter)
    assert w.ctrl.view().buttons.override and w.override_btn.isVisible()
    _key(w, Qt.Key.Key_Return, ctrl=True)
    w._flush_dwell()
    assert w.ctrl.state["stats"]["overrides"] == 1


def test_drill_window_show_extra_holds_a_dwell(window_env: Path) -> None:
    """2026-10-12: Show Extra (button, Ctrl+I in the page) on a feedback screen
    that hides the Extra stops the dwell and holds until Enter."""
    from aqt.qt import Qt

    deck = [
        {"front": "heart", "back": "cardi", "extra": "as in cardiology"},
        {"front": "liver", "back": "hepat", "extra": "as in hepatitis"},
    ]
    w: Any = _window(window_env, deck, encodeReps=2)
    for back in ("cardi", "hepat"):  # first time each: shown and held
        w.input.setText(back)
        _key(w, Qt.Key.Key_Return)
        assert not w._dwell.isActive() and w.ctrl.view().extra is not None
        _key(w, Qt.Key.Key_Return)
    assert not w.extra_btn.isVisible()
    w.input.setText("cardi")
    _key(w, Qt.Key.Key_Return)
    assert w._dwell.isActive() and w.extra_btn.isVisible()
    w.web.bridge("rd:extra")
    assert not w._dwell.isActive() and w.continue_btn.isVisible()
    assert w.ctrl.view().extra == "as in cardiology" and not w.extra_btn.isVisible()
    _key(w, Qt.Key.Key_Return)
    assert w.ctrl.view().feedback is None


def test_drill_window_close_asks_save_discard_cancel(
    window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aqt.qt import QMessageBox

    from recalldrill import sessions

    answers = [QMessageBox.StandardButton.Cancel, QMessageBox.StandardButton.Save]
    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: answers.pop(0))
    w: Any = _window(window_env)
    w.close()
    assert w.isVisible() and w.ctrl.finished is None  # Cancel
    w.close()
    assert w.ctrl.finished == "stopped"  # Save
    saved = sessions.load(w.store.storage, "deck-1")
    assert saved is not None and sessions.save_status(saved) == "resume"


def test_drill_window_discard_deletes_the_save(
    window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aqt.qt import QMessageBox

    from recalldrill import sessions

    monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.StandardButton.Discard)
    w: Any = _window(window_env)
    w.close()
    assert sessions.load(w.store.storage, "deck-1") is None


def test_drill_window_batches_done_screen_and_drill_again(window_env: Path) -> None:
    from aqt.qt import Qt

    from recalldrill.engine.session import select_trial

    deck = [
        {"front": "heart", "back": "cardi"},
        {"front": "liver", "back": "hepat"},
        {"front": "kidney", "back": "nephr"},
        {"front": "lung", "back": "pneum"},
    ]
    w: Any = _window(window_env, deck, encodeReps=1, batchSize=3)
    missed = False
    for _ in range(200):
        v = w.ctrl.view()
        if v.mode == "done":
            break
        if v.mode == "batch_done":
            assert w.next_batch_btn.isVisible() and not w.input.isVisible()
            _key(w, Qt.Key.Key_Return)  # Enter: Next batch
            continue
        if v.buttons.continue_:
            _key(w, Qt.Key.Key_Return)
            continue
        trial = select_trial(w.ctrl.state)
        assert trial is not None
        target = trial["target"]
        if v.label == "Final check" and not missed:
            target, missed = "nope", True
        w.input.setText(target)
        _key(w, Qt.Key.Key_Return)
        w._flush_dwell()
    assert w.ctrl.finished == "complete", w.ctrl.view()
    assert w.close_btn.isVisible() and w.again_btn.isVisible()
    assert w.handoff_btn.isVisible() and w.handoff_btn.isEnabled()
    assert "one undo step" in w.handoff_btn.toolTip()
    w.again_btn.click()
    assert w.store.meta.is_drill_again and len(w.ctrl.state["items"]) == 1
    assert w.windowTitle().endswith("(drill again)")


# -- the setup panel, offscreen, on a scratch collection -------------------------


class _SyncQueryOp:
    """``QueryOp`` run at once on the test's collection (no task manager here)."""

    col: object = None

    def __init__(self, parent: object, op: Any, success: Any) -> None:
        self._op, self._success, self._failure = op, success, None

    def failure(self, fn: Any) -> _SyncQueryOp:
        self._failure = fn
        return self

    def run_in_background(self) -> None:
        try:
            result = self._op(_SyncQueryOp.col)
        except Exception as exc:  # noqa: BLE001 (as QueryOp: hand it to failure)
            assert self._failure is not None
            self._failure(exc)
            return
        self._success(result)


@pytest.fixture
def panel_env(window_env: Path, monkeypatch: pytest.MonkeyPatch) -> Any:
    import sys

    import aqt
    from anki.collection import Collection

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "anki_io"))
    from anki_fixtures import add_bqe_model, add_bqe_note, deck

    from recalldrill.ui import context, drill_window, setup_dialog

    col = Collection(str(window_env / "collection.anki2"))
    add_bqe_model(col)
    did = deck(col, "Medical Terminology::3 - Skeletal System")
    for term, meaning in [("oste/o", "bone"), ("arthr/o", "joint"), ("chondr/o", "cartilage")]:
        add_bqe_note(col, did, term, meaning)
    col.sched.suspend_cards(col.find_cards(f"did:{did}"))

    stub = aqt.mw
    stub.col = col  # type: ignore[attr-defined]
    stub.addonManager = type("AM", (), {"getConfig": lambda self, m: None})()  # type: ignore[attr-defined]
    for module in (setup_dialog, context, drill_window):
        monkeypatch.setattr(module, "mw", stub)
    monkeypatch.setattr(setup_dialog, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(_SyncQueryOp, "col", col)
    yield col, int(did)
    col.close()


def test_setup_panel_reads_filters_and_starts(panel_env: Any, window_env: Path) -> None:
    from recalldrill import deck_settings
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    d: Any = SetupDialog(ctx, did)
    data = d.data
    assert data is not None and data.drillable == 6
    assert d.class_boxes["suspended_new"].text() == "suspended new (6)"
    assert d.proposal_row.isVisibleTo(d) and d.start_btn.isEnabled()
    # No timed session yet: the measured drill time says so (no cold-start figure).
    assert d.estimate_label.text() == "Next 6 cards: no estimate yet (needs 3 timed sessions)"
    assert not hasattr(d, "exposure_combo")
    assert d.pacing_box.isVisibleTo(d) and not d.pace_on.isChecked()
    assert "6 picked cards share a note" in d.sibling_label.text()

    # Reverse only, then terminology settings, batch size 3: nothing saved yet.
    (ntid,) = d._template_boxes
    normal = d._template_boxes[ntid][0][1]
    normal.setChecked(False)
    d._refresh()
    assert d.data.drillable == 3 and "Siblings: 0" in d.sibling_label.text()
    d.proposal_btn.click()
    assert d.data.build.hints_on and not d.proposal_row.isVisibleTo(d)
    d.batch_size.setValue(3)
    d._refresh()
    assert deck_settings.get_saved(ctx.storage(), did) is None

    d._start()
    saved = deck_settings.get_saved(ctx.storage(), did)
    assert saved is not None and saved.get("batchSize") == 3 and saved.get("strictPunctuation")
    assert saved.get("card_ords") == {str(ntid): [1]}
    (w,) = ctx.windows
    assert len(w.ctrl.state["items"]) == 3
    w.save_and_close()

    # Reopened: the saved session is offered.
    d2: Any = SetupDialog(ctx, did)
    assert d2.banner.isVisibleTo(d2) and d2.resume_btn.isVisibleTo(d2)
    d2._resume()
    assert len(ctx.windows) == 1
    ctx.windows[0].save_and_close()


def test_setup_panel_with_nothing_eligible(panel_env: Any, window_env: Path) -> None:
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    _col, _did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    d: Any = SetupDialog(ctx, None, search="tag:no-such-tag")
    assert d.data.drillable == 0 and not d.start_btn.isEnabled()
    assert d.status_label.text().startswith("Nothing to drill")
    d.close()


# -- the handoff, offscreen, on a scratch collection -----------------------------


class _SyncCollectionOp:
    """``CollectionOp`` run at once on the test's collection."""

    col: object = None

    def __init__(self, parent: object, op: Any) -> None:
        self._op, self._success, self._failure = op, None, None

    def success(self, fn: Any) -> _SyncCollectionOp:
        self._success = fn
        return self

    def failure(self, fn: Any) -> _SyncCollectionOp:
        self._failure = fn
        return self

    def run_in_background(self) -> None:
        try:
            result = self._op(_SyncCollectionOp.col)
        except Exception as exc:  # noqa: BLE001 (as CollectionOp: hand it to failure)
            assert self._failure is not None
            self._failure(exc)
            return
        assert self._success is not None
        self._success(result)


@pytest.fixture
def handoff_env(panel_env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The panel's collection, with the handoff's ops run synchronously and its
    confirmation answered by ``env.choices`` (popped in order)."""
    import aqt

    from recalldrill.ui import drill_window, handoff_dialog, setup_dialog

    col, did = panel_env

    class Env:
        choices: list[str] = []
        texts: list[Any] = []
        tips: list[str] = []
        warnings: list[str] = []

    def ask(_parent: object, text: Any) -> str:
        Env.texts.append(text)
        return Env.choices.pop(0)

    stub = aqt.mw
    stub.update_undo_actions = lambda: None  # type: ignore[attr-defined]
    monkeypatch.setattr(handoff_dialog, "mw", stub)
    monkeypatch.setattr(handoff_dialog, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(handoff_dialog, "CollectionOp", _SyncCollectionOp)
    monkeypatch.setattr(_SyncCollectionOp, "col", col)
    monkeypatch.setattr(handoff_dialog, "ask", ask)
    for module in (handoff_dialog, setup_dialog, drill_window):
        monkeypatch.setattr(module, "tooltip", lambda msg, *a, **k: Env.tips.append(msg))
    monkeypatch.setattr(
        handoff_dialog, "showWarning", lambda msg, *a, **k: Env.warnings.append(msg)
    )

    class _Silent:
        def play_tags(self, *_a: object) -> None: ...
        def stop_and_clear_queue(self) -> None: ...

    monkeypatch.setattr(drill_window, "av_player", _Silent())
    Env.col, Env.did = col, did  # type: ignore[attr-defined]
    return Env


def _finish_in_window(ctx: Any, did: int, miss_one: bool = True) -> Any:
    """Start the Reverse cards from the setup panel and drill to the Done screen."""
    from aqt.qt import Qt

    from recalldrill.engine.session import select_trial
    from recalldrill.ui.setup_dialog import SetupDialog

    d: Any = SetupDialog(ctx, did)
    (ntid,) = d._template_boxes
    d._template_boxes[ntid][0][1].setChecked(False)  # Reverse only
    d._refresh()
    d.encode_reps.setValue(1)
    d._refresh()
    d._start()
    (w,) = ctx.windows
    missed = not miss_one
    for _ in range(300):
        v = w.ctrl.view()
        if v.mode == "done":
            break
        if v.mode == "batch_done" or v.buttons.continue_:
            _key(w, Qt.Key.Key_Return)
            continue
        trial = select_trial(w.ctrl.state)
        assert trial is not None
        target = trial["target"]
        if v.label == "Final check" and not missed:
            target, missed = "nope", True
        w.input.setText(target)
        _key(w, Qt.Key.Key_Return)
        w._flush_dwell()
    assert w.ctrl.finished == "complete"
    return w


def test_handoff_from_the_done_screen(handoff_env: Any, window_env: Path) -> None:
    from recalldrill import history_store, sessions
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    env = handoff_env
    col, did = env.col, env.did
    ctx = AddonContext("recall_drill", str(window_env))
    w = _finish_in_window(ctx, did)
    key = w.store.meta.key
    assert w.handoff_btn.isVisible()

    # Not now: nothing changes, the session stays pending.
    env.choices = ["later"]
    w.handoff_btn.click()
    text = env.texts[-1]
    assert text.headline.startswith(
        "Hand off 3 cards: tag, unsuspend, stay new, front of the queue, available from "
    )
    assert "Siblings: 3 (suspended new cards of the same notes)" in text.plain()
    assert text.forecast[0].startswith("Tomorrow in Medical Terminology (from ")
    assert sessions.load(ctx.storage(), key) is not None and w.handoff_btn.isVisible()
    assert col.find_cards("tag:rd::drilled") == []

    # Hand off.
    env.choices = ["handoff"]
    w.handoff_btn.click()
    assert env.tips[-1] == 'Handed off. Edit → Undo "Recall Drill handoff" reverts it.'
    assert not w.handoff_btn.isVisible() and not ctx.handoffs
    assert sessions.load(ctx.storage(), key) is None
    assert [x["type"] for x in history_store.read_all(ctx.storage(), str(did))] == [
        "session",
        "handoff",
    ]
    assert len(col.find_notes("tag:rd::drilled")) == 3
    assert len(col.find_notes("tag:rd::final-miss")) == 1
    assert len(col.find_cards("tag:rd::drilled is:buried")) == 6
    assert col.find_cards("is:suspended") == []
    assert col.undo_status().undo == "Recall Drill handoff"
    w.close()

    # The panel has no banner now.
    d: Any = SetupDialog(ctx, did)
    assert not d.banner.isVisibleTo(d)
    d.close()


def test_handoff_declined_from_the_panel_banner(
    handoff_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recalldrill import history_store, sessions
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    env = handoff_env
    col, did = env.col, env.did
    ctx = AddonContext("recall_drill", str(window_env))
    w = _finish_in_window(ctx, did, miss_one=False)
    key = w.store.meta.key
    w.close()

    d: Any = SetupDialog(ctx, did)
    assert d.banner.isVisibleTo(d) and d.handoff_btn.isVisibleTo(d) and d.handoff_btn.isEnabled()
    assert d.discard_btn.text() == "Don't hand off"
    env.choices = ["decline"]
    d.handoff_btn.click()
    assert sessions.load(ctx.storage(), key) is None
    lines = history_store.read_all(ctx.storage(), str(did))
    assert lines[-1]["type"] == "handoff" and lines[-1]["declined"] is True
    assert col.find_cards("tag:rd::drilled") == [] and len(col.find_cards("is:suspended")) == 6
    assert not d.banner.isVisibleTo(d)
    d.close()


def test_a_failed_handoff_keeps_the_session_pending(
    handoff_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from recalldrill import sessions
    from recalldrill.ui.context import AddonContext

    env = handoff_env
    col, did = env.col, env.did
    ctx = AddonContext("recall_drill", str(window_env))
    w = _finish_in_window(ctx, did)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(col.sched, "bury_cards", boom)
    env.choices = ["handoff"]
    w.handoff_btn.click()
    assert "nothing changed in Anki" in env.warnings[-1] and "disk full" in env.warnings[-1]
    assert sessions.load(ctx.storage(), w.store.meta.key) is not None
    assert w.handoff_btn.isVisible() and not ctx.handoffs
    assert col.find_cards("tag:rd::drilled") == [] and len(col.find_cards("is:suspended")) == 6
    w.close()


def test_handoff_dialog_builds_offscreen(qt_app: object, monkeypatch: pytest.MonkeyPatch) -> None:
    from recalldrill.anki_io.handoff import HandoffText
    from recalldrill.ui.handoff_dialog import HandoffDialog

    text = HandoffText(
        headline="Hand off 6 cards: tag, unsuspend, stay new, front of the queue, available "
        "from Sat Oct 3, 4:00 AM.",
        lines=("Siblings: 6.", "Tags: +7 / −0."),
        forecast=("Tomorrow in Medical Terminology (from Sat Oct 3, 4:00 AM):",),
        warnings=("12 new cards tomorrow, over the deck's new/day limit of 10: 2 spill.",),
    )
    d = HandoffDialog(None, text)
    assert d.choice == "later"
    assert "Hand off 6 cards" in d.headline.text() and "⚠" in d.warnings.text()
    assert d.handoff_btn.isDefault()
    d.decline_btn.click()
    assert d.choice == "decline"
    d2 = HandoffDialog(None, HandoffText("h", (), (), ()))
    assert d2.forecast.isHidden() and d2.warnings.isHidden()
    d2.handoff_btn.click()
    assert d2.choice == "handoff"


def test_hard_cards_menu_actions(
    panel_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aqt

    from recalldrill.ui import entry, setup_dialog
    from recalldrill.ui.context import AddonContext

    col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    monkeypatch.setattr(entry, "_ctx", ctx)
    monkeypatch.setattr(entry, "mw", aqt.mw)
    monkeypatch.setattr(entry, "_current_deck", lambda: did)
    opened: list[tuple[Any, ...]] = []
    monkeypatch.setattr(
        aqt.dialogs, "open", lambda name, *a, **k: opened.append((name, a, k))
    )

    entry.open_hard_filtered_deck()
    assert opened == [("FilteredDeckConfigDialog", (aqt.mw,), {"search": "tag:rd::hard"})]

    entry.open_hard_cards()
    (d,) = ctx.dialogs
    assert isinstance(d, setup_dialog.SetupDialog)
    assert d.data is not None
    assert d.scope.search == "tag:rd::hard" and d.data.drillable == 0
    assert not d.hard_only.isVisibleTo(d)  # no handoff history yet
    d.close()



# -- Phase 5: the holdout in the panel, the tuning report ------------------------


def test_setup_panel_holdout_percent_per_deck(panel_env: Any, window_env: Path) -> None:
    """Holdout % in the card section: off (0) by default, K follows the %, the
    value is saved with the deck's settings and comes back on reopen."""
    from recalldrill import deck_settings, sessions
    from recalldrill.holdout import is_holdout
    from recalldrill.storage import HOLDOUT
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog, holdout_text

    col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    reverse = [int(c) for c in col.db.list("select id from cards where did = ? and ord = 1", did)]
    assert len(reverse) == 3
    # A salt that holds out some but not all Reverse cards at 50% (the hash is the
    # real one): card ids are time-based, so "at least one" alone could hold out
    # all three and leave nothing to Start.
    salt = next(
        f"s{i}"
        for i in range(1000)
        if 0 < sum(is_holdout(f"s{i}", c, 50) for c in reverse) < len(reverse)
    )
    ctx.storage().write_json(HOLDOUT, {"salt": salt})

    d: Any = SetupDialog(ctx, did)
    # 0% (the default): no holdout cards, and the line says so.
    assert d.holdout_pct.value() == 0 and d.holdout_row.isVisibleTo(d)
    assert d.holdout_label.text() == "Holdout: off" and d.data.selection.holdout == []
    assert d.data.drillable == 6
    # Reverse cards only, so no held-out card has a drilled sibling.
    (ntid,) = d._template_boxes
    d._template_boxes[ntid][0][1].setChecked(False)
    d._refresh()

    def k(pct: int) -> int:
        d.holdout_pct.setValue(pct)
        d._refresh()  # what the 300 ms timer runs
        held = {c.snap.cid for c in d.data.selection.holdout}
        assert held == {c for c in reverse if is_holdout(salt, c, pct)}
        assert d.holdout_label.text() == holdout_text(len(held), pct)
        assert d.data.drillable == 3 - len(held)
        return len(held)

    assert k(50) >= 1
    assert d.holdout_label.text().startswith("Holdout: ")
    assert k(0) == 0 and d.holdout_label.text() == "Holdout: off"
    assert k(10) <= k(30) <= k(50)  # the same hash: a higher % only adds cards
    assert holdout_text(1, 15).startswith("Holdout: 1 card skips the drill")
    assert holdout_text(3, 15) == (
        "Holdout: 3 cards skip the drill and go to Anki as new cards (measurement control)."
    )
    assert deck_settings.get_saved(ctx.storage(), did) is None  # nothing saved before Start

    held = d.data.holdout
    d._start()
    saved_settings = deck_settings.get_saved(ctx.storage(), did)
    assert saved_settings is not None and saved_settings.get("holdoutPct") == 50
    saved = sessions.load(ctx.storage(), sessions.deck_key(did))
    assert saved is not None and saved["addon"]["holdout"] == held and held
    assert saved["minWordsToChunk"] == 8
    ctx.windows[0].save_and_close()

    # Reopened: 50% comes back from the deck's settings, with the same cards.
    d2: Any = SetupDialog(ctx, did)
    assert d2.holdout_pct.value() == 50
    assert d2.data.holdout == held
    d2.close()
    # A search scope never holds cards out: no holdout row.
    d3: Any = SetupDialog(ctx, None, search=f"did:{did}")
    assert d3.data.selection.holdout == [] and not d3.holdout_row.isVisibleTo(d3)
    d3.close()


def test_tuning_report_dialog(
    window_env: Path, monkeypatch: pytest.MonkeyPatch, qt_app: object
) -> None:
    import sys

    import aqt
    from aqt.qt import QApplication

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tuning"))
    from tuning_support import Drilled, handoff_line, ms, rating, session_line

    from recalldrill import history_store
    from recalldrill.anki_io.revlog import ReportInputs
    from recalldrill.storage import Storage
    from recalldrill.tuning import CONFOUND_WARNING, CardInfo
    from recalldrill.ui import context, entry, tuning_dialog
    from recalldrill.ui.context import AddonContext

    # Two encodeReps values, 40 outcomes each, same Again rate: suggest the lower.
    lines: list[dict[str, Any]] = []
    revlog: list[Any] = []
    cards: dict[int, CardInfo] = {}
    for sid, reps, base in (("a", 3, 1000), ("b", 2, 2000)):
        drilled = [Drilled(base + i) for i in range(40)]
        lines += [
            session_line(sid, ms(2026, 10, 1, 14), drilled, encode_reps=reps),
            handoff_line(sid, ms(2026, 10, 1, 15), drilled),
        ]
        revlog += [
            rating(d.cid, ms(2026, 10, 2, 10), 1 if i < 4 else 3) for i, d in enumerate(drilled)
        ]
        cards |= {d.cid: CardInfo("Med Term::Ch 1", "Med Term") for d in drilled}
    inputs = ReportInputs(lines=lines, cards=cards, revlog=revlog, rollover=4)

    written: list[dict[str, Any]] = []

    class AM:
        conf: dict[str, Any] = {"min_n": 30, "encode_reps": 3}

        def getConfig(self, module: str) -> dict[str, Any]:  # noqa: N802
            return dict(self.conf)

        def writeConfig(self, module: str, conf: dict[str, Any]) -> None:  # noqa: N802
            written.append(conf)
            AM.conf = conf

    aqt.mw.addonManager = AM()  # type: ignore[attr-defined]
    aqt.mw.col = object()  # type: ignore[attr-defined]
    monkeypatch.setattr(tuning_dialog, "mw", aqt.mw)
    monkeypatch.setattr(context, "mw", aqt.mw)
    monkeypatch.setattr(tuning_dialog, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(tuning_dialog, "read_report_inputs", lambda col, st: inputs)
    monkeypatch.setattr(tuning_dialog, "encode_reps_overrides", lambda col, st, p: ["Med Term (3)"])
    asked: list[str] = []
    monkeypatch.setattr(tuning_dialog, "ask_apply", lambda parent, text: asked.append(text) or True)
    ctx = AddonContext("recall_drill", str(window_env))
    st = Storage(window_env, "p")
    ctx.storage = lambda: st  # type: ignore[method-assign]

    monkeypatch.setattr(entry, "_ctx", ctx)
    monkeypatch.setattr(entry, "mw", aqt.mw)
    entry.open_tuning()
    (d,) = ctx.dialogs
    assert isinstance(d, tuning_dialog.TuningDialog)
    assert d.report is not None and d.report.sessions == 2
    assert CONFOUND_WARNING.split(".")[0] in d.body.toPlainText()
    assert [d.deck.itemText(i) for i in range(d.deck.count())] == ["All decks", "Med Term"]
    buttons = [b.text() for b in d.findChildren(type(d.csv_btn)) if b.text().startswith("Apply")]
    assert buttons == ["Apply 3 → 2…"]

    d.csv_btn.click()
    clip = QApplication.clipboard()
    assert clip is not None and clip.text().startswith("group,cid,nid,deck")

    (s,) = [s for s in d.report.suggestions if s.actionable]
    d._apply(s)
    assert "from 3 to 2" in asked[0] and "Med Term (3)" in asked[0]
    assert written[-1]["encode_reps"] == 2 and written[-1]["min_n"] == 30
    (line,) = history_store.read_all(st, history_store.TUNING_KEY)
    assert (line["type"], line["old"], line["new"]) == ("tuning", 3, 2)
    # Re-rendered with the new default: nothing left to apply.
    assert not any(s.actionable for s in d.report.suggestions)

    # Cancelled: nothing written.
    monkeypatch.setattr(tuning_dialog, "ask_apply", lambda parent, text: False)
    AM.conf = {"encode_reps": 3, "min_n": 30}
    d._render()
    d._apply(next(s for s in d.report.suggestions if s.actionable))
    assert len(written) == 1
    d.close()
    assert ctx.dialogs == []


# -- Phase 6: difficulty line, pacing ---------------------------------------------


def test_setup_panel_difficulty_line_and_pacing(panel_env: Any, window_env: Path) -> None:
    """All-new Med Term: the difficulty line says new cards are unchanged; a target
    date gives today's N, "no estimate yet" for the minutes, and Use N fills Max
    cards; the pacing settings are saved for the deck and come back on reopen."""
    from datetime import date

    from aqt.qt import QDate

    from recalldrill import pacing
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog, stable_text

    col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    d: Any = SetupDialog(ctx, did)
    assert d.difficulty_label.text() == (
        "Difficulty-adjusted: 0 cards +1 rep, 0 cards −1 rep, 0 cards chunk earlier. "
        "New cards (6): no FSRS data, unchanged."
    )
    assert d.difficulty_adjust.isChecked()
    assert stable_text(0, 30, 5) == "" and stable_text(2, 30, 5).startswith("Stable: 2 cards")
    assert d.pacing_box.isVisibleTo(d) and not d.use_n_btn.isEnabled()
    assert d.pace_line.text().startswith("Set a target date")

    today = QDate.currentDate()
    d.pace_on.setChecked(True)
    for box in d.pace_days:
        box.setChecked(True)  # every day, so the count doesn't depend on today's weekday
    d.pace_early.setValue(1)
    d.pace_date.setDate(today.addDays(3))  # last drill day: in 2 days -> 3 drill days
    view = d.pacing_view
    assert view is not None and view.pace.status == "ok"
    assert (view.pace.remaining, view.pace.days_left, view.pace.per_day) == (6, 3, 2)
    assert d.pace_line.text() == view.line()
    assert "drill time: no estimate yet" in d.pace_line.text()
    assert d.pace_sources.text() == (
        "Drill time: no estimate yet (needs 3 timed sessions). "
        "Anki time: no estimate yet. The FSRS simulator wasn't used: FSRS is off or the "
        "preset has no FSRS parameters."
    )
    assert d.use_n_btn.isEnabled() and d.use_n_btn.text() == "Use 2 as max cards"
    d.use_n_btn.click()
    assert d.max_cards.value() == 2
    saved = pacing.load(ctx.storage(), did)
    assert saved.drill_weekdays == frozenset(range(7)) and saved.finish_days_before == 1
    assert saved.target_date is not None
    assert saved.target_date == date.fromisoformat(today.addDays(3).toString("yyyy-MM-dd"))
    d.close()

    again: Any = SetupDialog(ctx, did)
    assert again.pace_on.isChecked() and again.pace_date.date() == today.addDays(3)
    again.pace_on.setChecked(False)
    assert pacing.load(ctx.storage(), did).target_date is None
    assert not again.use_n_btn.isEnabled()
    again.close()


def test_setup_panel_exam_date_and_unrated_line(panel_env: Any, window_env: Path) -> None:
    """The Exam date field saves into pacing.json beside the target, shows
    "Exam: … (N days)", and can be cleared; handed-off cards with no rating yet
    show the amber unrated line."""
    import time
    from datetime import timedelta

    from aqt.qt import QDate

    from recalldrill import history_store, pacing
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    cids = [int(c) for c in col.find_cards(f"did:{did}")]
    col.sched.unsuspend_cards(cids[:1])  # type: ignore[arg-type]
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    history_store.append_handoff(
        ctx.storage(),
        str(did),
        {
            "type": "handoff",
            "sessionId": "x",
            "timestamp": stamp,
            "groups": {"drilled_new": cids[:1]},
            "cards": [{"cid": cids[0], "nid": 0, "ord": 0}],
        },
    )
    d: Any = SetupDialog(ctx, did)
    assert d.data is not None and d.data.today is not None
    assert d.unrated_label.isVisibleTo(d)
    assert d.unrated_label.text().startswith(
        "⚠ 1 drilled card is waiting for its first Anki rating. Rate it by "
    )
    assert not d.exam_on.isChecked() and d.exam_label.text() == ""
    assert not d.exam_date.isEnabled()

    today = d.data.today
    target = today + timedelta(days=10)
    d.exam_on.setChecked(True)
    d.exam_date.setDate(QDate(target.year, target.month, target.day))
    assert d.exam_label.text() == f"Exam: {pacing.short_date(target)} (10 days)"
    assert pacing.load(ctx.storage(), did).exam_date == target
    assert pacing.load(ctx.storage(), did).target_date is None  # the pacing target is separate
    d.close()

    again: Any = SetupDialog(ctx, did)
    assert again.exam_on.isChecked() and again.exam_date.date().day() == target.day
    assert again.exam_label.text() == f"Exam: {pacing.short_date(target)} (10 days)"
    again.exam_on.setChecked(False)
    assert pacing.load(ctx.storage(), did).exam_date is None
    assert again.exam_label.text() == ""
    again.close()


def test_setup_panel_counts_handed_off_cards(panel_env: Any, window_env: Path) -> None:
    """Cards a handoff sent to Anki, still new: left out and counted."""
    from recalldrill import history_store
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    cids = [int(c) for c in col.find_cards(f"did:{did}")]
    col.sched.unsuspend_cards(cids[:3])  # a handoff unsuspends; the 3rd wasn't handed off
    history_store.append_handoff(
        ctx.storage(),
        str(did),
        {"type": "handoff", "sessionId": "x", "groups": {"drilled_new": cids[:2]}},
    )
    d: Any = SetupDialog(ctx, did)
    assert d.data.drillable == 4 and d.data.selection.handed_off == 2
    assert "Handed off, waiting for Anki: 2 (they stay out until Anki reviews them)." in (
        d.summary_label.text()
    )
    d.close()



# -- finish early (Phase 8) -------------------------------------------------------


def _start_batched(ctx: Any, did: int) -> Any:
    """The three Reverse cards from the setup panel, one per batch, encodeReps 1."""
    from recalldrill.ui.setup_dialog import SetupDialog

    d: Any = SetupDialog(ctx, did)
    (ntid,) = d._template_boxes
    d._template_boxes[ntid][0][1].setChecked(False)
    d._refresh()
    d.encode_reps.setValue(1)
    d.batch_size.setValue(1)
    d._refresh()
    d._start()
    (w,) = ctx.windows
    return w


def _to_batch_done(w: Any) -> None:
    from recalldrill.engine.session import select_trial

    for _ in range(100):
        if w.ctrl.view().mode == "batch_done":
            return
        if w.ctrl.view().buttons.continue_:
            w._enter()
            continue
        trial = select_trial(w.ctrl.state)
        assert trial is not None
        w.input.setText(trial["target"])
        w._enter()
        w._flush_dwell()
    raise AssertionError("no interstitial")


@pytest.fixture
def finish_env(handoff_env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    from recalldrill.ui import drill_window, setup_dialog

    env = handoff_env
    env.confirms = []
    env.answers = []

    def confirm(_parent: object, counts: Any) -> bool:
        env.confirms.append(counts)
        return env.answers.pop(0)

    monkeypatch.setattr(drill_window, "QueryOp", _SyncQueryOp)
    for module in (drill_window, setup_dialog):
        monkeypatch.setattr(module, "confirm_finish_early", confirm)
    monkeypatch.setattr(
        drill_window, "showWarning", lambda msg, *a, **k: env.warnings.append(msg)
    )
    monkeypatch.setattr(setup_dialog, "showWarning", lambda msg, *a, **k: env.warnings.append(msg))
    return env


def test_finish_early_from_the_interstitial_and_the_stopped_screen(
    finish_env: Any, window_env: Path
) -> None:
    from recalldrill import sessions
    from recalldrill.ui.context import AddonContext

    env = finish_env
    ctx = AddonContext("recall_drill", str(window_env))
    w = _start_batched(ctx, env.did)
    key = w.store.meta.key
    assert not w.finish_btn.isVisible()  # a card is on screen
    _to_batch_done(w)
    assert w.finish_btn.isVisible() and w.finish_btn.text() == "Finish with 1 card"

    # Cancel: the session is stopped (saved), the button is still offered, nothing is cut.
    env.answers = [False, True]
    w.finish_btn.click()
    assert w.ctrl.finished == "stopped" and len(env.confirms) == 1
    c = env.confirms[0]
    assert (c.kept, c.returned, c.part_way, c.changed, c.missing) == (1, 2, 0, 0, 0)
    saved = sessions.load(ctx.storage(), key)
    assert saved is not None and "cut" not in saved["addon"] and len(saved["items"]) == 3
    assert w.finish_btn.isVisible() and w.again_btn.isVisible() is False

    # Finish, from the stopped screen: the same window now drills the Final check.
    w.finish_btn.click()
    assert w.ctrl.finished is None and w.ctrl.state["phase"] == "final"
    assert len(w.ctrl.state["items"]) == 1 and not w.finish_btn.isVisible()
    cut = sessions.load(ctx.storage(), key)
    assert cut is not None and len(cut["items"]) == 1
    assert [r["reason"] for r in cut["addon"]["cut"]["returned"]] == ["unfinished"] * 2
    w.save_and_close()


def test_finish_early_offers_nothing_when_the_mastered_card_changed(
    finish_env: Any, window_env: Path
) -> None:
    from anki.cards import CardId

    from recalldrill.ui.context import AddonContext

    env = finish_env
    ctx = AddonContext("recall_drill", str(window_env))
    w = _start_batched(ctx, env.did)
    _to_batch_done(w)
    (kept,) = [
        s.cid
        for i, s in enumerate(w.ctrl.sources)
        if w.ctrl.state["items"][i]["status"] == "mastered"
    ]
    note = env.col.get_note(env.col.get_card(CardId(kept)).nid)
    note["FrontText"] = "something else entirely"  # the Reverse card's answer
    env.col.update_note(note)
    # The only mastered card changed: nothing would be kept, so nothing is offered.
    w.finish_btn.click()
    assert env.confirms == [] and "Nothing to finish early" in env.tips[-1]
    assert w.ctrl.finished == "stopped"
    w.save_and_close()


def test_finish_early_from_the_panel_banner(finish_env: Any, window_env: Path) -> None:
    from recalldrill import sessions
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    env = finish_env
    ctx = AddonContext("recall_drill", str(window_env))
    w = _start_batched(ctx, env.did)
    key = w.store.meta.key
    _to_batch_done(w)

    # A window is driving this save: the panel's button is refused, like Resume.
    d: Any = SetupDialog(ctx, env.did)
    assert d.finish_btn.isVisibleTo(d) and d.finish_btn.text() == "Finish with 1 mastered card"
    d.finish_btn.click()
    assert env.confirms == [] and sessions.load(ctx.storage(), key) is not None
    assert "already open" in env.tips[-1]
    d.close()

    w.save_and_close()
    d = SetupDialog(ctx, env.did)
    assert d.finish_btn.isVisibleTo(d) and d.resume_btn.isVisibleTo(d)
    env.answers = [False, True]
    d.finish_btn.click()  # Cancel
    assert ctx.windows == [] and "cut" not in sessions.load(ctx.storage(), key)["addon"]  # type: ignore[index]
    d.finish_btn.click()  # Finish: the drill window opens on the cut session, the panel closes
    (w2,) = ctx.windows
    assert w2.ctrl.state["phase"] == "final" and len(w2.ctrl.state["items"]) == 1
    assert d._closed
    w2.save_and_close()

    # The cut session is all mastered: no Finish button on its banner.
    d3: Any = SetupDialog(ctx, env.did)
    assert d3.resume_btn.isVisibleTo(d3) and not d3.finish_btn.isVisibleTo(d3)
    d3.close()


def test_the_panel_hides_finish_for_a_pending_handoff(
    finish_env: Any, window_env: Path
) -> None:
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    env = finish_env
    ctx = AddonContext("recall_drill", str(window_env))
    w = _finish_in_window(ctx, env.did)
    w.close()
    d: Any = SetupDialog(ctx, env.did)
    assert d.handoff_btn.isVisibleTo(d) and not d.finish_btn.isVisibleTo(d)
    d.close()


def test_the_panel_hides_finish_for_a_save_in_the_final_check(
    finish_env: Any, window_env: Path
) -> None:
    from anki.cards import CardId

    from recalldrill import sessions
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    env = finish_env
    ctx = AddonContext("recall_drill", str(window_env))
    w = _start_batched(ctx, env.did)
    key = w.store.meta.key
    _to_batch_done(w)
    w.save_and_close()
    d: Any = SetupDialog(ctx, env.did)
    assert d.finish_btn.isVisibleTo(d)
    d.close()

    # Put the save in the Final check and change one card: nothing may be offered.
    saved = sessions.load(ctx.storage(), key)
    assert saved is not None
    saved["phase"] = "final"
    ctx.storage().write_json(sessions.save_name(key), saved)
    # An unmastered card, so without the Final-check guard the button would show.
    (idx,) = [i for i, it in enumerate(saved["items"]) if it["status"] == "new"][:1]
    cid = sessions.saved_sources(saved)[idx].cid
    note = env.col.get_note(env.col.get_card(CardId(cid)).nid)
    note["FrontText"] = "changed text"
    env.col.update_note(note)
    d = SetupDialog(ctx, env.did)
    assert d.saved_info is not None and d.saved_info.check is not None
    assert d.saved_info.check.changed and not d.finish_btn.isVisibleTo(d)
    d.close()


def test_waiting_cards_dialog_and_notice(
    panel_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """2026-10-12: Tools → Recall Drill: waiting cards lists the deck's waiting
    drill cards; "Send to Anki undrilled…" plans, asks, applies and logs; the
    notice shows once per Anki day."""
    import aqt

    from recalldrill import history_store
    from recalldrill.storage import Storage
    from recalldrill.ui import context, entry, waiting_dialog
    from recalldrill.ui.context import AddonContext

    col, did = panel_env
    for nid in col.find_notes(f"did:{did}"):
        note = col.get_note(nid)
        note.add_tag("rd::drill::A")
        col.update_note(note)
    stub = aqt.mw
    stub.update_undo_actions = lambda: None  # type: ignore[attr-defined]
    tips: list[str] = []
    asked: list[list[str]] = []
    opened: list[int] = []
    for module in (waiting_dialog, context, entry):
        monkeypatch.setattr(module, "mw", stub)
    monkeypatch.setattr(waiting_dialog, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(waiting_dialog, "CollectionOp", _SyncCollectionOp)
    monkeypatch.setattr(_SyncCollectionOp, "col", col)
    monkeypatch.setattr(waiting_dialog, "tooltip", lambda text, **_k: tips.append(text))
    def pick_default(_parent: Any, offered: list[Any]) -> Any:
        asked.append([label for label, _plan in offered])
        return offered[0][1]  # the default button

    monkeypatch.setattr(waiting_dialog, "ask_send", pick_default)
    ctx = AddonContext("recall_drill", str(window_env))
    st = Storage(window_env, "p")
    ctx.storage = lambda: st  # type: ignore[method-assign]
    monkeypatch.setattr(entry, "_ctx", ctx)
    monkeypatch.setattr(entry, "open_setup_for", lambda d: opened.append(d))

    # Nothing is stale yet: no notice, and the day isn't used up.
    waiting_dialog.maybe_notify(ctx)
    assert tips == [] and history_store.handed_off_at(st) == {}

    entry.open_waiting_cards()
    (w,) = [d for d in ctx.dialogs if isinstance(d, waiting_dialog.WaitingDialog)]
    cell: Any = w.table.item
    assert w.table.rowCount() == 1 and cell(0, 1).text() == "6"
    assert cell(0, 2).text() == "0"
    w._drill(did)
    assert opened == [did]

    # A passed pacing target makes them stale: the notice shows, once a day.
    from datetime import timedelta

    from recalldrill import pacing
    from recalldrill.measure import anki_day

    today = anki_day(time_ms(), col.get_preferences().scheduling.rollover)
    pacing.save(st, did, pacing.PacingSettings(target_date=today - timedelta(days=1)))
    waiting_dialog.maybe_notify(ctx)
    assert len(tips) == 1 and tips[0].startswith("Recall Drill: 6 drill cards are still suspended")
    waiting_dialog.maybe_notify(ctx)
    assert len(tips) == 1

    # Send them to Anki undrilled.
    w.refresh()
    assert cell(0, 2).text() == "6"
    w._send(w.rows[0])
    # All six are stale, so both choices show, "Stale only" first (the default).
    assert asked == [["Stale only (6)", "All waiting (6)"]]
    assert all(col.get_card(c).queue == 0 for c in col.find_cards(f"did:{did}"))
    (line,) = history_store.read_all(st, str(did))
    assert line["type"] == "release" and len(line["groups"]["released"]) == 6
    assert line["scope"] == "stale"
    assert w.table.rowCount() == 0
    w.close()


def test_release_confirmation_buttons(qt_app: object, monkeypatch: pytest.MonkeyPatch) -> None:
    """2026-10-13: the confirmation has "Stale only (N)" (the default) and "All
    waiting (M)"; with nothing stale only "All waiting"; the plan clicked is returned."""
    from aqt.qt import QMessageBox

    from recalldrill.anki_io.release import ReleasePlan
    from recalldrill.ui import waiting_dialog

    def plan(scope: Any, n: int) -> ReleasePlan:
        return ReleasePlan(1, "Lab", tuple(range(n)), (), (), (), 20, scope)

    seen: dict[str, Any] = {}
    click = {"label": "All waiting (5)"}

    def fake_exec(self: Any) -> int:
        buttons = [b for b in self.buttons() if b.text()]
        seen["labels"] = [b.text() for b in buttons]
        seen["default"] = self.defaultButton().text()
        seen["text"] = self.text()
        self._clicked = next((b for b in buttons if b.text() == click["label"]), None)
        return 0

    monkeypatch.setattr(QMessageBox, "exec", fake_exec)
    monkeypatch.setattr(QMessageBox, "clickedButton", lambda self: self._clicked)
    both = [("Stale only (2)", plan("stale", 2)), ("All waiting (5)", plan("all", 5))]
    picked = waiting_dialog.ask_send(None, both)  # type: ignore[arg-type]
    assert picked is both[1][1]
    assert seen["labels"] == ["Stale only (2)", "All waiting (5)", "Cancel"]
    assert seen["default"] == "Stale only (2)"
    assert "Stale only: 2 cards" in seen["text"] and "All waiting: 5 cards" in seen["text"]

    click["label"] = "Cancel"
    assert waiting_dialog.ask_send(None, both) is None  # type: ignore[arg-type]

    click["label"] = "All waiting (5)"
    only = [("All waiting (5)", plan("all", 5))]
    assert waiting_dialog.ask_send(None, only) is only[0][1]  # type: ignore[arg-type]
    assert seen["labels"] == ["All waiting (5)", "Cancel"]
    assert seen["default"] == "All waiting (5)"


def time_ms() -> float:
    import time

    return time.time() * 1000


# -- v0.3: hold back, sections --------------------------------------------------------


@pytest.fixture
def hold_env(panel_env: Any, monkeypatch: pytest.MonkeyPatch) -> Any:
    """The panel's deck with its six cards unsuspended and new (nothing held back
    yet), the hold-back ops run synchronously and the two questions answered from
    ``env.answers``."""
    import types

    from recalldrill.ui import holdback_ui

    col, did = panel_env
    col.sched.unsuspend_cards(col.find_cards(f"did:{did}"))
    env = types.SimpleNamespace(
        col=col, did=did, confirms=[], asks=[], tips=[], answer_confirm=True, answer_ask=True
    )

    def confirm(_parent: Any, plan: Any) -> bool:
        env.confirms.append(plan.cards)
        return env.answer_confirm

    def ask(_parent: Any, n: int) -> bool:
        env.asks.append(n)
        return env.answer_ask

    monkeypatch.setattr(holdback_ui, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(holdback_ui, "CollectionOp", _SyncCollectionOp)
    monkeypatch.setattr(_SyncCollectionOp, "col", col)
    monkeypatch.setattr(holdback_ui, "confirm_hold_back", confirm)
    monkeypatch.setattr(holdback_ui, "ask_release_held", ask)
    monkeypatch.setattr(holdback_ui, "tooltip", lambda text, **_k: env.tips.append(text))
    return env


def _suspended(col: Any, did: int) -> list[int]:
    return [int(c) for c in col.find_cards(f"did:{did}") if col.get_card(c).queue == -1]


def test_setup_panel_hold_back_switch_button_and_order(hold_env: Any, window_env: Path) -> None:
    from recalldrill import deck_settings
    from recalldrill.holdback import TAG_HELD
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    col, did = hold_env.col, hold_env.did
    ctx = AddonContext("recall_drill", str(window_env))
    d: Any = SetupDialog(ctx, did)
    assert d.hold_back_box.isVisibleTo(d) and not d.hold_back.isChecked()
    assert d.hold_back.text() == "Keep new cards out of Anki until drilled"
    assert d.order.currentData() == "priority_first" and not d.hold_back_btn.isVisibleTo(d)
    assert deck_settings.explicit_hold_back(ctx.storage(), did) is None

    # Turning it on: asked first; a No still saves the switch and leaves every card alone.
    hold_env.answer_confirm = False
    d.hold_back.setChecked(True)
    assert hold_env.confirms == [6] and _suspended(col, did) == []
    assert deck_settings.explicit_hold_back(ctx.storage(), did) is True
    assert d.order.currentData() == "deck_order"  # drills in the order the skill added them
    assert d.hold_back_btn.isVisibleTo(d) and d.hold_back_btn.text() == "Hold back 6"

    # The button runs the same write; Yes suspends and tags, one undo step.
    hold_env.answer_confirm = True
    d.hold_back_btn.click()
    assert hold_env.confirms == [6, 6] and len(_suspended(col, did)) == 6
    assert all(TAG_HELD in col.get_note(n).tags for n in col.find_notes(f"did:{did}"))
    assert col.undo_status().undo == "Recall Drill: hold back"
    assert not d.hold_back_btn.isVisibleTo(d)  # nothing left to hold back
    assert hold_env.tips == ["Held back 6 cards. Edit → Undo reverts it."]

    # A new card added to the held-back deck brings the button back.
    from anki_fixtures import add_bqe_note

    add_bqe_note(col, did, "ankyl/o", "stiff")
    d._refresh()
    assert d.hold_back_btn.isVisibleTo(d) and d.hold_back_btn.text() == "Hold back 2"
    d.close()

    # Reopened: the saved switch defaults the order to deck order.
    again: Any = SetupDialog(ctx, did)
    assert again.hold_back.isChecked() and again.order.currentData() == "deck_order"
    # The user can still change it.
    again.order.setCurrentIndex(again.order.findData("priority_first"))
    assert again.order.currentData() == "priority_first"
    again.close()


def test_turning_hold_back_off_with_and_without_release(hold_env: Any, window_env: Path) -> None:
    from recalldrill import deck_settings, history_store
    from recalldrill.anki_io.waiting import read_waiting_cards
    from recalldrill.holdback import TAG_HELD
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    col, did = hold_env.col, hold_env.did
    ctx = AddonContext("recall_drill", str(window_env))
    d: Any = SetupDialog(ctx, did)
    d.hold_back.setChecked(True)  # asked, answered Yes
    assert len(_suspended(col, did)) == 6

    # Off, and No to "Release 6 held cards to Anki now?": they stay held and listed.
    hold_env.answer_ask = False
    d.hold_back.setChecked(False)
    assert hold_env.asks == [6]
    assert deck_settings.explicit_hold_back(ctx.storage(), did) is False
    assert len(_suspended(col, did)) == 6
    assert len(read_waiting_cards(col, ctx.storage(), did)) == 6
    # Only the hold-back's own line so far (v0.3.1); no release.
    assert [x["type"] for x in history_store.read_all(ctx.storage(), str(did))] == ["holdback"]

    # On again (nothing new to hold), off again, Yes: released, keeping queue positions.
    positions = {c: col.get_card(c).due for c in _suspended(col, did)}
    d.hold_back.setChecked(True)
    hold_env.answer_ask = True
    d.hold_back.setChecked(False)
    assert hold_env.asks == [6, 6]
    assert _suspended(col, did) == []
    assert {c: col.get_card(c).due for c in col.find_cards(f"did:{did}")} == positions
    assert not any(TAG_HELD in col.get_note(n).tags for n in col.find_notes(f"did:{did}"))
    (line,) = [x for x in history_store.read_all(ctx.storage(), str(did)) if x["type"] == "release"]
    assert len(line["groups"]["released"]) == 6
    assert "Released 6 cards to Anki. Edit → Undo reverts it." in hold_env.tips
    assert read_waiting_cards(col, ctx.storage(), did) == []
    d.close()

    # Off with nothing held: no question.
    hold_env.answer_confirm = False  # turning it on writes nothing
    quiet: Any = SetupDialog(ctx, did)
    quiet.hold_back.setChecked(True)
    assert _suspended(col, did) == []
    asked = len(hold_env.asks)
    quiet.hold_back.setChecked(False)
    assert len(hold_env.asks) == asked  # nothing was held, so nothing to release
    quiet.close()


def test_the_sections_dialog_lists_subdecks_and_opens_the_setup_panel(
    qt_app: object, monkeypatch: pytest.MonkeyPatch, window_env: Path, tmp_path: Path
) -> None:
    import aqt
    from anki.collection import Collection
    from anki_fixtures import add_note, deck

    from recalldrill.storage import Storage
    from recalldrill.ui import context, sections_dialog
    from recalldrill.ui.context import AddonContext

    col = Collection(str(tmp_path / "sections.anki2"))
    try:
        for name in ("Lab 2::Muscles", "Lab 2::Bones"):
            add_note(col, "Basic", deck(col, name), {"Front": name, "Back": "b"})  # type: ignore[arg-type]
        stub = aqt.mw
        stub.col = col  # type: ignore[attr-defined]
        for module in (sections_dialog, context):
            monkeypatch.setattr(module, "mw", stub)
        monkeypatch.setattr(sections_dialog, "QueryOp", _SyncQueryOp)
        monkeypatch.setattr(_SyncQueryOp, "col", col)
        ctx = AddonContext("recall_drill", str(window_env))
        ctx.storage = lambda: Storage(window_env, "p")  # type: ignore[method-assign]
        opened: list[int] = []
        lab = int(deck(col, "Lab 2"))
        w: Any = sections_dialog.SectionsDialog(ctx, opened.append, lab)
        assert w.deck_combo.currentText() == "Lab 2"
        # Subdecks come in the order their cards were made (Muscles first), v0.3.1.
        assert [r.label for r in w.rows] == ["Muscles", "Bones"]
        assert w.summary.text() == "0 of 2 sections done · Next: Muscles, 1 to go"
        # v0.5: one rounded row per subdeck (it was a table); the counts the other columns
        # showed are in the row's tooltip.
        first = w.row_cards[0]
        assert first.name_label.text() == "Muscles" and first.count_label.text() == "1"
        assert "Not in Anki, not held: 1" in first.toolTip()
        assert "1 new + 0 introduced" in first.toolTip()
        # Clicking a row opens that subdeck's setup panel.
        from PyQt6.QtTest import QTest

        QTest.mouseClick(  # pyright: ignore[reportCallIssue]
            w.row_cards[1], sections_dialog.Qt.MouseButton.LeftButton
        )
        assert opened == [w.rows[1].did]
        w._clicked(1, 0)
        assert opened == [w.rows[1].did] * 2
        w.close()
    finally:
        col.close()


def test_the_progress_dialog_shows_layers_marks_next_and_drills_next(
    qt_app: object, monkeypatch: pytest.MonkeyPatch, window_env: Path, tmp_path: Path
) -> None:
    import sys

    import aqt
    from anki.collection import Collection

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "anki_io"))
    from layer_scene import CHAPTERS, build

    from recalldrill.storage import Storage
    from recalldrill.ui import context, sections_dialog
    from recalldrill.ui.context import AddonContext

    col = Collection(str(tmp_path / "progress.anki2"))
    try:
        ctx = AddonContext("recall_drill", str(window_env))
        storage = Storage(window_env, "p")
        ctx.storage = lambda: storage  # type: ignore[method-assign]
        scene = build(col, storage)
        stub = aqt.mw
        stub.col = col  # type: ignore[attr-defined]
        for module in (sections_dialog, context):
            monkeypatch.setattr(module, "mw", stub)
        monkeypatch.setattr(sections_dialog, "QueryOp", _SyncQueryOp)
        monkeypatch.setattr(_SyncQueryOp, "col", col)
        opened: list[int] = []
        driven: list[tuple[int, str, str | None, frozenset[str]]] = []
        w: Any = sections_dialog.SectionsDialog(
            ctx,
            opened.append,
            scene.lab,
            lambda did, order, tag, classes: driven.append((did, order, tag, classes)),
        )
        assert w.windowTitle() == "Recall Drill: progress"
        assert [r.label for r in w.rows] == ["Layer 1", "Layer 2", "Layer 3", "Layer 4"]
        assert w.summary.text() == "0 of 4 layers done · Next: Layer 1, 6 to go"
        # v0.5: rows instead of a table. One cell per chapter, the Next row has its marker,
        # accent look and the Drill next button, and the numbers the old columns held
        # (can't drill, ...) are in the tooltip.
        cards = w.row_cards
        assert [c.text() for c in cards[0].chapter_captions] == list(CHAPTERS)
        assert cards[0].chapter_cells[CHAPTERS.index("Muscles")].text() == "1/2"
        assert cards[0].next_marker is not None and cards[0].next_marker.text() == "NEXT"
        assert all(c.next_marker is None for c in cards[1:])
        assert [c.property("rdRow") for c in cards] == ["next", "true", "true", "true"]
        assert "Can't drill: 2" in cards[0].toolTip()
        # Drill next: the chosen deck, Order = Deck order. It sits in the Next row.
        assert w.next_btn.text() == "Drill next" and w.next_btn.isEnabled()
        assert cards[0].isAncestorOf(w.next_btn) and w.next_btn.property("rdRole") == "primary"
        w.next_btn.click()
        assert driven == [(scene.lab, "deck_order", "Layer::1", {"new", "suspended_new"})]
        assert opened == []
        # A row opens the setup panel on the chosen deck.
        w._clicked(2, 0)
        assert opened == [scene.lab]
        w.close()
    finally:
        col.close()


class _DrillNext:
    """The progress table and the setup panel its Drill next opened, on a
    ``layer_scene`` deck (``prepare`` changes the deck first)."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch, window_env: Path, col: Any) -> None:
        import sys

        import aqt

        sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "anki_io"))
        from layer_scene import build

        from recalldrill.storage import Storage
        from recalldrill.ui import context, entry, sections_dialog, setup_dialog
        from recalldrill.ui.context import AddonContext

        self.col = col
        self.ctx = AddonContext("recall_drill", str(window_env))
        self.storage = Storage(window_env, "p")
        self.ctx.storage = lambda: self.storage  # type: ignore[method-assign]
        self.scene = build(col, self.storage)
        stub = aqt.mw
        stub.col = col  # type: ignore[attr-defined]
        stub.addonManager = type("AM", (), {"getConfig": lambda self, m: None})()  # type: ignore[attr-defined]
        for module in (sections_dialog, setup_dialog, context, entry):
            monkeypatch.setattr(module, "mw", stub)
        for module in (sections_dialog, setup_dialog):
            monkeypatch.setattr(module, "QueryOp", _SyncQueryOp)
        monkeypatch.setattr(_SyncQueryOp, "col", col)
        monkeypatch.setattr(entry, "_ctx", self.ctx)
        self.panels: list[Any] = []
        monkeypatch.setattr(
            setup_dialog,
            "open_setup",
            lambda c, did, search=None, order=None, tag=None, classes=None: (
                self.panels.append(setup_dialog.SetupDialog(c, did, search, order, tag, classes))
                and self.panels[-1]
            ),
        )
        self.entry, self.sections_dialog, self.setup_dialog = entry, sections_dialog, setup_dialog

    def click(self) -> tuple[Any, Any]:
        """Open the progress table and click Drill next: (table, panel)."""
        w: Any = self.sections_dialog.open_sections(
            self.ctx, self.entry.open_setup_for, self.scene.lab, self.entry.open_setup_for
        )
        w.next_btn.click()
        return w, self.panels[-1]

    def front(self, c: Any) -> str:
        return str(self.col.get_note(c.snap.nid).fields[0])

    def review(self, front: str, *, lapses: int = 0, flag: int = 0, rated: bool = False) -> None:
        """Anki introduced the card: a review due in 2 days (``rated``: a review logged
        now, as when Anki rates a card the add-on handed off)."""
        import time

        from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV

        card = self.scene.cards[front]
        card.load()
        card.type, card.queue = CARD_TYPE_REV, QUEUE_TYPE_REV
        card.ivl, card.due = 4, self.col.sched.today + 2
        card.lapses = lapses
        self.col.update_card(card)
        if flag:
            self.col.set_user_flag_for_cards(flag, [card.id])
        if rated:
            self.col.db.execute(
                "insert into revlog values (?,?,?,?,?,?,?,?,?)",
                int(time.time() * 1000) + 5000,
                card.id,
                -1,
                3,
                4,
                0,
                2500,
                3000,
                1,
            )

    def hold(self, fronts: list[str]) -> None:
        """Held back: suspended and tagged rd::held, as hold back leaves them."""
        cards = [self.scene.cards[f] for f in fronts]
        for c in cards:
            note = c.note()
            note.add_tag("rd::held")
            self.col.update_note(note)
        self.col.sched.suspend_cards([c.id for c in cards])


def test_drill_next_picks_exactly_the_layer_cards_the_table_counts_to_go(
    qt_app: object, monkeypatch: pytest.MonkeyPatch, window_env: Path, tmp_path: Path
) -> None:
    """Lab 2 on 2026-10-14: Layer 1 has 4 held cards to go, and Anki has already
    introduced others (one drilled and rated since, one lapsed, one red-flagged).
    Drill next picks the 4 held cards and no review."""
    from anki.collection import Collection

    col = Collection(str(tmp_path / "drillnext.anki2"))
    try:
        env = _DrillNext(monkeypatch, window_env, col)
        env.review("L1-Muscles-0", rated=True)  # drilled, handed off, then rated by Anki
        env.review("L1-Joints-0", lapses=1)
        env.review("L1-Nerves-0", flag=1)
        held = ["L1-Muscles-1", "L1-Bones-1", "L1-Joints-1", "L1-Nerves-1"]
        env.hold(held)
        w, panel = env.click()
        row = w.progress.next_row
        assert row.label == "Layer 1" and row.to_go == 4 and row.held == 4
        assert panel.order.currentData() == "deck_order"
        assert panel.tag_edit.text() == "Layer::1"
        ticked = {c for c, box in panel.class_boxes.items() if box.isChecked()}
        assert ticked == {"new", "suspended_new"}
        data = panel.data
        layer1 = col.find_cards('deck:"AP Lab::Lab 2" tag:Layer::1')
        assert data.selection.total == len(layer1) == 10
        assert sorted(env.front(c) for c in data.selection.picked) == sorted(held)
        assert {c.card_class for c in data.selection.picked} == {"suspended_new"}
        assert len(data.build.deck_items) == row.to_go
        assert "10 cards in scope; 4 picked" in panel.summary_label.text()
        # The reviews are still there for whoever ticks them (the boxes aren't saved).
        panel.class_boxes["young"].setChecked(True)
        panel.class_boxes["lapsed"].setChecked(True)
        panel.class_boxes["flagged"].setChecked(True)
        panel._refresh()
        assert len(panel.data.selection.picked) == 7
        # The tag and the boxes were applied once: a reload keeps the panel's choices.
        panel.tag_edit.setText("")
        panel._load_scope()
        assert panel.tag_edit.text() == "" and panel.class_boxes["young"].isChecked()
        panel.close()
        # Opening the panel by hand still ticks the default types.
        plain: Any = env.setup_dialog.SetupDialog(env.ctx, env.scene.lab)
        assert plain.class_boxes["young"].isChecked() and plain.tag_edit.text() == ""
        plain.close()
        w.close()
    finally:
        col.close()


def test_drill_next_on_the_no_layer_row_picks_only_the_untagged_new_cards(
    qt_app: object, monkeypatch: pytest.MonkeyPatch, window_env: Path, tmp_path: Path
) -> None:
    """Every numbered layer drilled, two notes without a layer left: no tag to fill,
    the whole deck, but only new cards, so the reviews of every layer stay out."""
    import time

    from anki.collection import Collection
    from anki_fixtures import add_note

    from recalldrill import history_store

    col = Collection(str(tmp_path / "nolayer.anki2"))
    try:
        env = _DrillNext(monkeypatch, window_env, col)
        sc = env.scene
        rest = [c for f, c in sc.cards.items() if c not in sc.drilled]
        history_store.append_handoff(
            env.storage,
            str(sc.lab),
            {
                "type": "handoff",
                "sessionId": "s2",
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime()),
                "groups": {"drilled_new": [c.id for c in rest]},
                "cards": [{"cid": c.id, "nid": c.nid, "ord": 0} for c in rest],
            },
        )
        env.review("L2-Bones-0", rated=True)
        env.review("L1-Muscles-0", rated=True)
        for i in range(2):
            fields = {"Front": f"NOLAYER-{i}", "Back": "x"}
            add_note(col, "Basic", sc.chapters["Joints"], fields, ())  # type: ignore[arg-type]
        w, panel = env.click()
        row = w.progress.next_row
        assert row.label == "No layer" and row.to_go == 2
        assert all(r.done for r in w.progress.rows[:-1])
        assert panel.tag_edit.text() == ""
        picked = sorted(env.front(c) for c in panel.data.selection.picked)
        assert picked == ["NOLAYER-0", "NOLAYER-1"]
        panel.close()
        w.close()
    finally:
        col.close()


def test_a_saved_session_built_with_another_tag_says_so_and_start_fresh_replaces_it(
    qt_app: object, monkeypatch: pytest.MonkeyPatch, window_env: Path, tmp_path: Path
) -> None:
    from anki.collection import Collection

    col = Collection(str(tmp_path / "saved.anki2"))
    try:
        env = _DrillNext(monkeypatch, window_env, col)
        env.hold(["L1-Muscles-1", "L1-Bones-1", "L1-Joints-1", "L1-Nerves-1"])
        w, panel = env.click()
        n = w.progress.next_row.to_go  # 4 held + 2 open Layer 1 cards
        assert n == 6
        panel._start()  # the Layer 1 session, saved for the deck
        (drill,) = env.ctx.windows
        assert len(drill.ctrl.state["items"]) == n
        drill.save_and_close()
        env.ctx.windows.clear()

        # Same tag (Drill next again): the usual banner, no note.
        _w2, again = env.click()
        assert again.resume_btn.isVisibleTo(again)
        assert "built with" not in again.banner_text.text()
        again.close()
        # By hand, no tag: the banner says what the save was built with.
        plain: Any = env.setup_dialog.SetupDialog(env.ctx, env.scene.lab)
        text = plain.banner_text.text()
        assert "It was built with tag Layer::1, the panel now has no tag." in text
        assert "Resume continues it as saved; Start fresh builds from the panel." in text
        # Resume keeps the saved cards, whatever the panel picks now.
        assert len(plain.data.selection.picked) > n
        plain._resume()
        (resumed,) = env.ctx.windows
        assert len(resumed.ctrl.state["items"]) == n
        resumed.save_and_close()
        env.ctx.windows.clear()
        # Start fresh drops the save and builds from the panel (the whole deck's new cards).
        plain2: Any = env.setup_dialog.SetupDialog(env.ctx, env.scene.lab)
        picked = len(plain2.data.build.deck_items)
        plain2._start_fresh()
        (fresh,) = env.ctx.windows
        assert len(fresh.ctrl.state["items"]) == picked > n
        fresh.save_and_close()
        assert env.setup_dialog._saved_tag({"addon": {}}) == ""
        w.close()
    finally:
        col.close()


def test_setup_panel_opens_with_the_order_the_progress_table_asks_for(
    hold_env: Any, window_env: Path
) -> None:
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    ctx = AddonContext("recall_drill", str(window_env))
    plain: Any = SetupDialog(ctx, hold_env.did)
    assert plain.order.currentData() == "priority_first"
    plain.close()
    asked: Any = SetupDialog(ctx, hold_env.did, None, "deck_order")
    assert asked.order.currentData() == "deck_order"
    asked.close()


def test_hold_back_button_offers_to_release_held_undrillable_cards(
    hold_env: Any, window_env: Path
) -> None:
    from anki_fixtures import add_bqe_note, add_io_note

    from recalldrill import deck_settings
    from recalldrill.holdback import TAG_HELD
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    col, did = hold_env.col, hold_env.did
    ctx = AddonContext("recall_drill", str(window_env))
    deck_settings.set_hold_back(ctx.storage(), did, True)
    d: Any = SetupDialog(ctx, did)
    d.hold_back_btn.click()  # holds the six cards back
    assert len(_suspended(col, did)) == 6 and not d.hold_back_btn.isVisibleTo(d)
    # v0.3.0 also held an image-occlusion card; a new card arrived too.
    io = add_io_note(col, did).cards()[0]
    col.tags.bulk_add([io.nid], TAG_HELD)
    col.sched.suspend_cards([io.id])
    d._refresh()
    assert d.hold_back_btn.isVisibleTo(d) and d.hold_back_btn.text() == "Release 1 undrillable"
    add_bqe_note(col, did, "ankyl/o", "stiff")
    d._refresh()
    assert d.hold_back_btn.text() == "Hold back 2 / release 1 undrillable"
    d.hold_back_btn.click()
    io.load()
    assert io.queue == 0 and TAG_HELD not in col.get_note(io.nid).tags
    assert not d.hold_back_btn.isVisibleTo(d)
    d.close()


# -- v0.3: the outcomes export ------------------------------------------------------------


def test_outcomes_export_after_a_handoff_at_open_and_from_tools(
    handoff_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aqt

    from recalldrill.storage import OUTCOMES
    from recalldrill.ui import entry, export_ui, waiting_dialog
    from recalldrill.ui.context import AddonContext

    env = handoff_env
    col, did = env.col, env.did
    stub = aqt.mw
    config: dict[str, Any] = {}
    stub.addonManager = type("AM", (), {"getConfig": lambda self, m: config})()  # type: ignore[attr-defined]
    shown: list[str] = []
    monkeypatch.setattr(export_ui, "mw", stub)
    monkeypatch.setattr(export_ui, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(export_ui, "showInfo", lambda text, **_k: shown.append(text))
    monkeypatch.setattr(waiting_dialog, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(waiting_dialog, "mw", stub)
    monkeypatch.setattr(_SyncQueryOp, "col", col)
    monkeypatch.setattr(entry, "mw", stub)
    ctx = AddonContext("recall_drill", str(window_env))
    monkeypatch.setattr(entry, "_ctx", ctx)
    target = ctx.storage().path(OUTCOMES)
    assert not target.exists()

    # A handoff rewrites it.
    w = _finish_in_window(ctx, did)
    env.choices = ["handoff"]
    w.handoff_btn.click()
    assert target.is_file()
    lines = target.read_text(encoding="utf-8").splitlines()
    assert lines[0].startswith("group,cid,nid,homeDeck,sessionId,t0,status,")
    assert len(lines) == 1 + 3  # the three drilled cards
    assert all(line.startswith("drilled,") for line in lines[1:])
    w.close()

    # Profile open: written once when export_on_open is on, not when it is off.
    target.unlink()
    config["export_on_open"] = False
    entry.on_profile_did_open()
    assert not target.exists()
    config["export_on_open"] = True
    entry.on_profile_did_open()
    assert target.is_file()

    # Tools → export outcomes now: the same file, then the folder path.
    target.unlink()
    entry.export_outcomes_now()
    assert target.is_file()
    assert len(shown) == 1
    assert "Wrote 3 rows" in shown[0] and str(target) in shown[0]
    assert f"Folder: {target.parent}" in shown[0]
    assert entry.EXPORT_LABEL == "Recall Drill: export outcomes now"


def test_a_failing_automatic_export_is_quiet(
    handoff_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    import aqt

    from recalldrill.ui import export_ui
    from recalldrill.ui.context import AddonContext

    stub = aqt.mw
    monkeypatch.setattr(export_ui, "mw", stub)
    monkeypatch.setattr(export_ui, "QueryOp", _SyncQueryOp)
    monkeypatch.setattr(_SyncQueryOp, "col", handoff_env.col)

    def boom(*_a: object, **_k: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(export_ui, "export_outcomes", boom)
    ctx = AddonContext("recall_drill", str(window_env))
    seen: list[Any] = []
    export_ui.export_in_background(ctx, seen.append)  # no exception, no warning dialog
    assert seen == []


# -- v0.5: the shared window style, and the setup panel in it ----------------------------

TABLE_TOKENS = {
    "dark": {
        "window": "#282c34", "card": "#2c313a", "footer": "#262a31", "input": "#21252b",
        "border": "#3a404b", "control_border": "#454c59", "text": "#abb2bf",
        "strong": "#dcdfe4", "muted": "#8b929e", "accent": "#61afef", "on_accent": "#1b1f27",
        "ok": "#56d364", "warn": "#e3b341", "bad": "#ff7b72",
    },
    "light": {
        "window": "#f6f7f9", "card": "#ffffff", "footer": "#eef0f3", "input": "#ffffff",
        "border": "#d9dce1", "control_border": "#c4c9d1", "text": "#2b3036",
        "strong": "#14171a", "muted": "#5c6570", "accent": "#1f6feb", "on_accent": "#ffffff",
        "ok": "#1a7f37", "warn": "#9a6700", "bad": "#cf222e",
    },
}  # fmt: skip
"""The approved mockup's colour table (docs/DECISIONS.md, "v0.5 window redesign")."""


def test_style_tokens_are_the_approved_table() -> None:
    from recalldrill.ui import style

    assert style.TOKENS == TABLE_TOKENS


@pytest.mark.parametrize("night", [True, False])
def test_stylesheet_holds_the_tokens_and_every_role_and_kind(night: bool) -> None:
    import re

    from recalldrill.ui import style

    sheet = style.stylesheet(night)
    tokens = TABLE_TOKENS["dark" if night else "light"]
    for name, value in tokens.items():
        assert value in sheet, name
    other = TABLE_TOKENS["light" if night else "dark"]
    for name in ("window", "card", "accent"):
        assert other[name] not in sheet, name
    for role in style.ROLES:
        assert f'QPushButton[rdRole="{role}"]' in sheet
    for kind in ("chip", "switch"):
        assert f'QCheckBox[rdKind="{kind}"]' in sheet
    for note in ("warn", "info"):
        assert f'QLabel[rdNote="{note}"]' in sheet
    for status in style.PILL_COLOR:
        assert f'QLabel[rdPill="{status}"]' in sheet
    # Every rule is scoped to our own content (or to a property only our widgets carry), so a
    # message box a window opens keeps Anki's look.
    for line in sheet.splitlines():
        head = line.split("{")[0].strip()
        if head and "{" in line:
            assert head.startswith(("#rdRoot", 'QDialog[rdWindow="true"]')), head
    # The switch and arrow images are real files.
    paths = re.findall(r'url\("([^"]+)"\)', sheet)
    assert len(set(paths)) == 4  # two switch images and two arrows for this theme
    assert all(Path(p).is_file() for p in paths), paths
    # Warning notes: the warning colour at about 12 % behind and 35 % on the border.
    t = style.derived("dark" if night else "light")
    assert t["warn_bg"] == style.mix(tokens["warn"], tokens["card"], 0.12)
    assert t["warn_border"] == style.mix(tokens["warn"], tokens["card"], 0.35)


def test_a_theme_change_restyles_the_open_windows(
    panel_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from aqt import gui_hooks

    from recalldrill.ui import style
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    _col, did = panel_env
    monkeypatch.setattr(style, "is_night", lambda: False)
    d: Any = SetupDialog(AddonContext("recall_drill", str(window_env)), did)
    assert d.styleSheet() == style.stylesheet(False)
    monkeypatch.setattr(style, "is_night", lambda: True)
    gui_hooks.theme_did_change()  # Anki's own hook, as the theme manager runs it
    assert d.styleSheet() == style.stylesheet(True)
    d.close()
    gui_hooks.theme_did_change()  # a closed window is skipped, not an error


@pytest.mark.parametrize("night", [True, False])
def test_setup_panel_in_dark_and_light(
    panel_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch, night: bool
) -> None:
    from aqt.qt import QCheckBox, QPushButton, Qt

    from recalldrill.ui import style
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    monkeypatch.setattr(style, "is_night", lambda: night)
    _col, did = panel_env
    d: Any = SetupDialog(AddonContext("recall_drill", str(window_env)), did)
    assert d.styleSheet() == style.stylesheet(night)
    # Roles: Start is the one primary button and the default; Sections secondary; Close ghost.
    assert style.role_of(d.start_btn) == "primary" and d.start_btn.isDefault()
    assert style.role_of(d.sections_btn) == "secondary"
    visible = [b for b in d.findChildren(QPushButton) if b.isVisibleTo(d)]
    assert [b for b in visible if style.role_of(b) == "primary"] == [d.start_btn]
    assert [b.text() for b in visible if style.role_of(b) == "ghost"] == ["Close"]
    assert not any(b.isDefault() for b in visible if b is not d.start_btn)
    # The footer order: Sections…, Close, Start.
    footer = [b.text() for b in visible if b.text() in ("Sections…", "Close", "Start")]
    assert footer == ["Sections…", "Close", "Start"]

    # Chips: the card types and the weekdays are pills with their old text, still checkable.
    box = d.class_boxes["suspended_new"]
    assert box.text() == "suspended new (6)" and box.property("rdKind") == "chip"
    assert all(b.property("rdKind") == "chip" for b in d.pace_days)
    before = set(d.enabled)
    box.setChecked(False)
    assert "suspended_new" not in d.enabled and "suspended_new" in before
    box.setChecked(True)
    (ntid,) = d._template_boxes
    assert all(b.property("rdKind") == "chip" for _o, b in d._template_boxes[ntid])

    # Switches: real, tabbable check boxes that save into the draft as before.
    for sw in (d.strict, d.stem, d.hints, d.difficulty_adjust, d.hold_back, d.pace_on, d.exam_on):
        assert isinstance(sw, QCheckBox) and sw.property("rdKind") == "switch"
        assert sw.focusPolicy() & Qt.FocusPolicy.TabFocus
    d.strict.setChecked(True)
    assert d.draft["strictPunctuation"] is True and not d.stem.isEnabled()
    d.close()


def test_setup_header_shows_the_trackers_numbers_only_when_there_are_some(
    panel_env: Any, window_env: Path
) -> None:
    from datetime import timedelta

    from recalldrill import pacing
    from recalldrill.exam_tracker import TrackerNumbers
    from recalldrill.ui import exam_tracker
    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    _col, did = panel_env
    ctx = AddonContext("recall_drill", str(window_env))
    d: Any = SetupDialog(ctx, did)
    assert d.header_title.text() == "3 - Skeletal System"
    assert d.header_path.text() == "Medical Terminology"
    assert d.data is not None and d.data.today is not None
    today = d.data.today
    # No exam date, nothing cached: no pill and no countdown.
    assert not d.header_pill.isVisibleTo(d) and not d.header_exam.isVisibleTo(d)
    d.close()

    # An exam date on the deck, but no tracker result yet: still nothing (never computed here).
    exam = today + timedelta(days=8)
    pacing.save(ctx.storage(), did, pacing.PacingSettings(None, frozenset(), 1, exam))
    d = SetupDialog(ctx, did)
    assert d.data is not None and d.data.exam_did == did
    assert not d.header_pill.isVisibleTo(d)
    d.close()

    numbers = TrackerNumbers(
        exam_date=exam,
        days_left=7,
        status="green",
        drill=6,
        new=0,
        reviews=0,
        done_today=0,
        needed=1,
        pace=1.0,
        est_seconds=None,
        finish_date=exam - timedelta(days=1),
    )
    exam_tracker._cache.store(today, {did: numbers})  # pyright: ignore[reportPrivateUsage]
    try:
        d = SetupDialog(ctx, did)
        assert d.header_pill.isVisibleTo(d) and d.header_pill.text() == "✓ On pace"
        assert d.header_pill.property("rdPill") == "green"
        assert d.header_exam.text() == f"7 days to finish · exam {pacing.short_date(exam)}"
        d.close()
    finally:
        exam_tracker._cache.clear()  # pyright: ignore[reportPrivateUsage]


def test_setup_header_tiles_appear_only_with_their_data(panel_env: Any, window_env: Path) -> None:
    from aqt.qt import QDate

    from recalldrill.ui.context import AddonContext
    from recalldrill.ui.setup_dialog import SetupDialog

    _col, did = panel_env
    d: Any = SetupDialog(AddonContext("recall_drill", str(window_env)), did)
    assert d.tile_cards.isVisibleTo(d) and d.tile_cards_value.text() == "6"
    assert not d.tile_pace.isVisibleTo(d)  # pacing is off: no "a day"
    d.pace_on.setChecked(True)
    for box in d.pace_days:
        box.setChecked(True)
    d.pace_early.setValue(1)
    d.pace_date.setDate(QDate.currentDate().addDays(3))
    assert d.tile_pace.isVisibleTo(d) and d.tile_pace_value.text() == "2"
    d.pace_on.setChecked(False)
    assert not d.tile_pace.isVisibleTo(d)
    d.close()


def test_building_the_panel_reads_the_collection_no_more_than_before(
    panel_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two background reads (the scope, then the cards), none for the header, which only reads
    what the panel loaded and the tracker's cache (nothing may touch ``mw.col`` there)."""
    import aqt

    from recalldrill.ui import setup_dialog
    from recalldrill.ui.context import AddonContext

    ops: list[object] = []

    class Counting(_SyncQueryOp):
        def run_in_background(self) -> None:
            ops.append(self._op)
            super().run_in_background()

    monkeypatch.setattr(setup_dialog, "QueryOp", Counting)
    _col, did = panel_env
    d: Any = setup_dialog.SetupDialog(AddonContext("recall_drill", str(window_env)), did)
    assert len(ops) == 2

    class NoReads:
        def __getattr__(self, name: str) -> object:
            raise AssertionError(f"the header read mw.col.{name}")

    monkeypatch.setattr(aqt.mw, "col", NoReads())
    d._show_header()  # pyright: ignore[reportPrivateUsage]
    assert len(ops) == 2
    d.close()


# -- v0.5: the sections rows and the drill window in the new style --------------------------


def _visible_primaries(w: Any) -> list[Any]:
    from aqt.qt import QPushButton

    from recalldrill.ui import style

    return [
        b
        for b in w.findChildren(QPushButton)
        if b.isVisibleTo(w) and style.role_of(b) == "primary"
    ]


def test_sections_rows_done_next_and_the_drill_next_button_survives_a_rebuild(
    qt_app: object, monkeypatch: pytest.MonkeyPatch, window_env: Path, tmp_path: Path
) -> None:
    import aqt
    from anki.collection import Collection

    from recalldrill.sections import Chapter, Progress, SectionRow
    from recalldrill.storage import Storage
    from recalldrill.ui import context, sections_dialog
    from recalldrill.ui.context import AddonContext

    col = Collection(str(tmp_path / "rows.anki2"))
    try:
        stub = aqt.mw
        stub.col = col  # type: ignore[attr-defined]
        for module in (sections_dialog, context):
            monkeypatch.setattr(module, "mw", stub)
        monkeypatch.setattr(sections_dialog, "QueryOp", _SyncQueryOp)
        monkeypatch.setattr(_SyncQueryOp, "col", col)
        ctx = AddonContext("recall_drill", str(window_env))
        ctx.storage = lambda: Storage(window_env, "p")  # type: ignore[method-assign]
        w: Any = sections_dialog.SectionsDialog(ctx, lambda _d: None, None)
        chapters = (Chapter(11, "Lab::A", "A"), Chapter(12, "Lab::B", "B"))
        rows = (
            SectionRow(5, "Lab", "Layer 1", 4, 4, 0, 4, 0, 0, 0, 0, 1, ((2, 2), (2, 2))),
            SectionRow(5, "Lab", "Layer 2", 5, 5, 0, 1, 0, 2, 2, 0, 2, ((1, 2), (0, 3))),
            SectionRow(5, "Lab", "Layer 3", 3, 3, 0, 0, 0, 1, 2, 0, 3, ((0, 1), (0, 2))),
        )
        w._show(Progress(5, True, chapters, rows))
        done, nxt, later = w.row_cards
        # Done row: the tick, no marker, no button. Complete chapters are green (kind "ok").
        assert done.done_label is not None and done.done_label.text() == "✓ Done"
        assert done.next_marker is None and not done.isAncestorOf(w.next_btn)
        assert [c.property("rdText") for c in done.chapter_cells] == ["ok", "ok"]
        assert nxt.chapter_cells[0].property("rdText") == "strong"
        # Next row: marker, accent look, count, bar numbers and the primary Drill next button.
        assert nxt.next_marker is not None and nxt.property("rdRow") == "next"
        assert nxt.count_label.text() == "4" and nxt.bar_label.text() == "1 of 5"
        assert nxt.isAncestorOf(w.next_btn) and w.next_btn.isVisibleTo(w)
        assert later.next_marker is None and later.done_label is None
        assert "Held / waiting: 2" in nxt.toolTip() and "Can't drill: 0" in nxt.toolTip()
        assert w.summary.text() == "1 of 3 layers done · Next: Layer 2, 4 to go"
        # A rebuild keeps the same button (its row was deleted around it) and moves it.
        button = w.next_btn
        w._show(Progress(5, True, chapters, (rows[1], rows[0], rows[2])))
        assert w.next_btn is button and w.row_cards[0].isAncestorOf(button)
        # Nothing left to drill: no Next row, no button, a plain summary.
        w._show(Progress(5, True, chapters, (rows[0],)))
        assert not w.next_btn.isVisibleTo(w) and not w.next_btn.isEnabled()
        assert w.summary.text() == "1 of 1 layers done"
        w._show(Progress(5, False, (), ()))
        assert w.summary.text() == "This deck has no subdecks and no cards."
        w.close()
    finally:
        col.close()


@pytest.mark.parametrize("night", [True, False])
def test_every_window_builds_in_dark_and_light(
    panel_env: Any, window_env: Path, monkeypatch: pytest.MonkeyPatch, night: bool
) -> None:
    from recalldrill.ui import style

    monkeypatch.setattr(style, "is_night", lambda: night)
    w: Any = _window(window_env)
    assert w.styleSheet() == style.stylesheet(night)
    # On a card the one primary button is Check; nothing is the default button (Enter is a key).
    assert _visible_primaries(w) == [w.check_btn]
    assert not any(b.isDefault() for b in w.findChildren(type(w.check_btn)))
    assert [style.role_of(b) for b in (w.reveal_btn, w.replay_btn, w.edit_btn, w.end_btn)] == [
        "secondary",
        "ghost",
        "ghost",
        "ghost",
    ]
    assert w.stage_chip.text() == "Encoding" and w.detail_label.text() == "Full item"
    assert w.mastered_label.text() == "0 of 3 mastered"
    assert w.count_chips["New"].text() == "New (2)" and w.count_chips["Encoding"].text() == (
        "Encoding (1)"
    )
    assert w.deck_label.text() == "Ch 3" and not w.section_label.isVisibleTo(w)
    w.save_and_close()


def test_drill_window_primary_follows_the_screen_and_keys_still_work(window_env: Path) -> None:
    from aqt.qt import Qt

    deck = [{"front": "heart", "back": "cardi"}, {"front": "liver", "back": "hepat"}]
    w: Any = _window(window_env, deck, encodeReps=1, batchSize=1)
    # A wrong answer shows feedback: Continue becomes the primary button.
    w.input.setText("nope")
    _key(w, Qt.Key.Key_Return)
    assert w.ctrl.view().buttons.continue_
    assert _visible_primaries(w) == [w.continue_btn]
    _key(w, Qt.Key.Key_Return)
    # Walk to the batch interstitial: Next batch is the primary button.
    from recalldrill.engine.session import select_trial

    for _ in range(100):
        v = w.ctrl.view()
        if v.mode == "batch_done":
            break
        if v.buttons.continue_:
            _key(w, Qt.Key.Key_Return)
            continue
        trial = select_trial(w.ctrl.state)
        assert trial is not None
        w.input.setText(trial["target"])
        _key(w, Qt.Key.Key_Return)
        w._flush_dwell()
    assert w.ctrl.view().mode == "batch_done"
    assert _visible_primaries(w) == [w.next_batch_btn]
    assert not w.stage_chip.isVisibleTo(w)  # "Batch 1 of 2 complete" has no stage
    w.save_and_close()


def test_stage_chip_position_text_and_section() -> None:
    from recalldrill.ui.drill_window import section_text, stage_and_position

    assert stage_and_position("Encoding • Part 1 of 3") == ("Encoding", "Part 1 of 3")
    assert stage_and_position("Spaced Retrieval • Cycling review") == (
        "Cycle",
        "Cycling review",
    )
    assert stage_and_position("Final check • 2 of 9") == ("Final", "2 of 9")
    assert stage_and_position("Batch 1 of 3 complete") == ("", "Batch 1 of 3 complete")
    assert section_text("Layer::2") == "Layer 2" and section_text("layer::10") == "Layer 10"
    assert section_text(" rd::drill::A1 ") == "rd::drill::A1" and section_text("") == ""
