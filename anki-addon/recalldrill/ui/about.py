"""Tools-menu entry and About box."""

from __future__ import annotations

from anki.utils import version_with_build
from aqt import mw
from aqt.qt import QAction, qconnect
from aqt.utils import showInfo

from .. import __version__

MENU_LABEL = "Recall Drill (dev)"


def show_about() -> None:
    showInfo(
        f"Recall Drill {__version__} (dev)\n\nAnki {version_with_build()}",
        title="About Recall Drill",
    )


def register_menu() -> None:
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists
    # (and always None under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    action = QAction(MENU_LABEL, mw)
    qconnect(action.triggered, show_about)
    mw.form.menuTools.addAction(action)
