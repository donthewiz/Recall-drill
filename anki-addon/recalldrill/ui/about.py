"""The About box, and its item at the bottom of Tools → Recall Drill → More (v0.5.1)."""

from __future__ import annotations

from anki.utils import version_with_build
from aqt.qt import QAction, QMenu, QWidget, qconnect
from aqt.utils import showInfo

from .. import __version__

ABOUT_LABEL = "About Recall Drill"
"""The About item, last in Tools → Recall Drill → More (v0.5.1: no longer a Tools entry of its
own, so Tools has one Recall Drill entry)."""

DEV_FOLDER = "recall_drill_dev"
"""The dev junction's folder name (docs/DECISIONS.md, "Dev install")."""


def addon_folder(module: str = __name__) -> str:
    """The add-on's folder name: the first part of its module name."""
    return module.split(".")[0]


def display_name(folder: str | None = None) -> str:
    """ "Recall Drill (dev)" when running from the dev folder, else "Recall Drill".
    Used by the About text."""
    folder = addon_folder() if folder is None else folder
    return "Recall Drill (dev)" if folder == DEV_FOLDER else "Recall Drill"


def show_about() -> None:
    showInfo(
        f"{display_name()} {__version__}\n\nAnki {version_with_build()}",
        title="About Recall Drill",
    )


def add_about(menu: QMenu, parent: QWidget) -> QAction:
    """Appends "About Recall Drill" to ``menu`` (the Recall Drill submenu's More)."""
    action = QAction(ABOUT_LABEL, parent)
    qconnect(action.triggered, lambda _checked=False: show_about())
    menu.addAction(action)
    return action


def register_menu() -> None:
    """Kept for older entry points. Until v0.5.1 this added a second "Recall Drill" entry to
    Tools for the About box; that item now sits in the Recall Drill submenu (``add_about``),
    so this adds nothing."""
    return
