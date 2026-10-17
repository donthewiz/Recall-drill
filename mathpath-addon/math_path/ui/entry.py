"""The Tools → Math Path menu and the hooks (v0.1)."""

from __future__ import annotations

from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, qconnect
from aqt.utils import showInfo, tooltip

from .. import __version__, pages
from .context import AddonContext

MENU_LABEL = "Math Path"
IMPORT_LABEL = "Import recipes…"
LEARN_NEXT_LABEL = "Learn next"
ABOUT_LABEL = "About Math Path"
DEV_FOLDER = "math_path_dev"

_ctx: AddonContext | None = None


def context() -> AddonContext | None:
    return _ctx


def display_name(folder: str) -> str:
    return "Math Path (dev)" if folder == DEV_FOLDER else "Math Path"


def show_about() -> None:
    from anki.utils import version_with_build

    folder = _ctx.folder if _ctx is not None else "math_path"
    showInfo(
        f"{display_name(folder)} {__version__}\n\nAnki {version_with_build()}",
        title="About Math Path",
    )


def build_menu(tools: QMenu, parent: object) -> QMenu:
    """Tools → Math Path with its items; returns the submenu."""
    menu = tools.addMenu(MENU_LABEL)
    assert menu is not None
    from .import_dialog import open_import_dialog

    def add(label: str, fn: object) -> None:
        action = QAction(label, menu)
        qconnect(action.triggered, lambda _checked=False: fn())  # type: ignore[operator]
        menu.addAction(action)

    from .launch import learn_next

    add(LEARN_NEXT_LABEL, lambda: _ctx is not None and learn_next(_ctx))
    add(IMPORT_LABEL, lambda: _ctx is not None and open_import_dialog(_ctx))
    menu.addSeparator()
    add(ABOUT_LABEL, show_about)
    return menu


def register(module: str, user_files: str) -> None:
    """Called once from the add-on's ``__init__``."""
    global _ctx
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists (and under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    _ctx = AddonContext(module, user_files)
    mw.addonManager.setWebExports(module, pages.web_pattern())
    build_menu(mw.form.menuTools, mw)
    gui_hooks.profile_will_close.append(on_profile_will_close)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)


def on_show_question(card: Any) -> None:
    """The reviewer showed a card's question: a Math Path card opens its window (when
    ``auto_open_in_review`` is on); a window left over from another card closes."""
    from .review_window import ReviewWindow, current_math_path_note, open_review

    if _ctx is None:
        return
    for w in list(_ctx.windows):
        if isinstance(w, ReviewWindow) and w.card_id != card.id:
            w.close()  # the reviewer moved on: nothing was rated
    note = current_math_path_note(card)
    if note is None or not _ctx.config().auto_open_in_review:
        return
    if note.recipe is None:
        tooltip(f"This Math Path note's recipe can't be read: {note.error}")
        return
    open_review(_ctx, note, int(card.id))


def on_js_message(handled: tuple[bool, Any], message: str, context: Any) -> tuple[bool, Any]:
    """The card face's "Solve in Math Path" link (``pycmd('mathpath:open')``)."""
    from ..anki_io.notetype import PYCMD_OPEN
    from .review_window import current_math_path_note, open_review

    if message != PYCMD_OPEN:
        return handled
    card = getattr(context, "card", None)
    if _ctx is not None and card is not None:
        note = current_math_path_note(card)
        if note is not None and note.recipe is not None:
            open_review(_ctx, note, int(card.id))
    return (True, None)


def on_profile_will_close() -> None:
    if _ctx is None:
        return
    for window in list(_ctx.windows):
        window.close()
