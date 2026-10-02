"""Smoke tests for ``recalldrill/ui``: every module imports, and the windows run offscreen.

Runs headless on Qt's offscreen platform. Skipped where aqt isn't installed
(CI's addon-anki job installs anki only) or Qt can't start without a display.
The windows themselves are checked by hand (docs/SMOKE.md).
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


def test_every_ui_module_is_listed() -> None:
    assert {
        "recalldrill.ui.about",
        "recalldrill.ui.context",
        "recalldrill.ui.drill_window",
        "recalldrill.ui.entry",
        "recalldrill.ui.handoff_dialog",
        "recalldrill.ui.mapping_dialog",
        "recalldrill.ui.setup_dialog",
        "recalldrill.ui.tuning_dialog",
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

