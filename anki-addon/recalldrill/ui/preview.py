"""Tools-menu item: a read-only preview of what the drill would read from the
current deck. Temporary (Phase 2); the Phase 3b panel replaces it."""

from __future__ import annotations

from aqt import mw
from aqt.operations import QueryOp
from aqt.qt import (
    QAction,
    QDialog,
    QDialogButtonBox,
    Qt,
    QTextBrowser,
    QVBoxLayout,
    qconnect,
)

from ..anki_io.preview import Preview, build_preview, preview_html
from ..storage import Storage

MENU_LABEL = "Recall Drill (dev): preview current deck"


def show_preview(user_files: str) -> None:
    col = mw.col
    if col is None:
        return
    did = int(col.decks.current()["id"])
    storage = Storage(user_files, mw.pm.name or "")
    QueryOp(
        parent=mw,
        op=lambda col: build_preview(col, storage, did),
        success=show_dialog,
    ).with_progress("Recall Drill: reading cards...").run_in_background()


def show_dialog(preview: Preview) -> QDialog:
    # Parented to the main window, which keeps it alive while it's open.
    dialog = QDialog(mw)
    dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
    dialog.setWindowTitle(f"Recall Drill (dev) preview: {preview.deck_name}")
    browser = QTextBrowser(dialog)
    browser.setHtml(preview_html(preview))
    buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, dialog)
    qconnect(buttons.rejected, dialog.reject)
    layout = QVBoxLayout(dialog)
    layout.addWidget(browser)
    layout.addWidget(buttons)
    dialog.resize(1100, 800)
    dialog.show()
    return dialog


def register_preview_menu(user_files: str) -> None:
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists
    # (and always None under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    action = QAction(MENU_LABEL, mw)
    qconnect(action.triggered, lambda: show_preview(user_files))
    mw.form.menuTools.addAction(action)
