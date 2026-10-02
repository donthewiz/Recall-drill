"""Tools-menu entry and About box."""

from __future__ import annotations

from anki.utils import version_with_build
from aqt import mw
from aqt.qt import QAction, qconnect
from aqt.utils import showInfo

from .. import __version__

DEV_FOLDER = "recall_drill_dev"
"""The dev junction's folder name (docs/DECISIONS.md, "Dev install")."""


def addon_folder(module: str = __name__) -> str:
    """The add-on's folder name: the first part of its module name."""
    return module.split(".")[0]


def display_name(folder: str | None = None) -> str:
    """"Recall Drill (dev)" when running from the dev folder, else "Recall Drill".
    Used by the Tools menu entry and the About text."""
    folder = addon_folder() if folder is None else folder
    return "Recall Drill (dev)" if folder == DEV_FOLDER else "Recall Drill"


def show_about() -> None:
    showInfo(
        f"{display_name()} {__version__}\n\nAnki {version_with_build()}",
        title="About Recall Drill",
    )


def register_menu() -> None:
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists
    # (and always None under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    action = QAction(display_name(), mw)
    qconnect(action.triggered, show_about)
    mw.form.menuTools.addAction(action)
