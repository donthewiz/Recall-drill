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
        "math_path.ui.page_window",
    } <= set(UI_MODULES)


@pytest.fixture
def env(qt_app: object, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Iterator[Any]:
    import aqt
    from stubs import FakeWeb, StubMw, SyncCollectionOp, SyncQueryOp

    from math_path.ui import context, import_dialog, page_window

    c = Collection(str(tmp_path / "collection.anki2"))
    stub = StubMw(c)
    monkeypatch.setattr(aqt, "mw", stub)
    for mod in (context, import_dialog, page_window):
        monkeypatch.setattr(mod, "mw", stub)
    monkeypatch.setattr(page_window, "AnkiWebView", FakeWeb)
    monkeypatch.setattr(import_dialog, "QueryOp", SyncQueryOp)
    monkeypatch.setattr(import_dialog, "CollectionOp", SyncCollectionOp)
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
    assert shown == ["Import recipes…", "About Math Path"]
