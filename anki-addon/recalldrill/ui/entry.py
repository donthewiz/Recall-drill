"""Entry points: Tools menu, the deck gear menu, the deck overview's button,
and closing drill windows with the profile.

Checked on 26.08.1 (docs/DECISIONS.md, "Entry points"):

- ``deck_browser_will_show_options_menu(menu, deck_id)`` adds to the gear menu.
- ``overview_will_render_bottom(link_handler, links)`` is a filter: the button
  goes into ``links`` and the returned handler answers its ``pycmd``. The
  bottom bar routes its messages to that handler, so
  ``webview_did_receive_js_message`` isn't needed.
- ``profile_will_close()``: open drill windows save and close.
"""

from __future__ import annotations

from collections.abc import Callable

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, qconnect

from .context import AddonContext

TOOLS_LABEL = "Recall Drill…"
GEAR_LABEL = "Recall Drill this deck"
OVERVIEW_LABEL = "Recall Drill"
OVERVIEW_CMD = "recalldrill:setup"

_ctx: AddonContext | None = None


def open_setup_for(deck_id: int | None) -> None:
    """The setup panel for a deck, or its drill window if one is running."""
    if _ctx is None or mw.col is None:
        return
    from ..sessions import deck_key
    from .setup_dialog import open_setup

    if deck_id is not None and _ctx.raise_window(deck_key(deck_id)):
        return

    open_setup(_ctx, deck_id)


def _current_deck() -> int | None:
    col = mw.col
    if col is None:
        return None
    return int(col.decks.current()["id"])


def on_gear_menu(menu: QMenu, deck_id: int) -> None:
    action = menu.addAction(GEAR_LABEL)
    if action is not None:
        qconnect(action.triggered, lambda: open_setup_for(int(deck_id)))


def on_overview_bottom(
    link_handler: Callable[[str], bool], links: list[list[str]]
) -> Callable[[str], bool]:
    links.append(["", OVERVIEW_CMD, OVERVIEW_LABEL])

    def handler(url: str) -> bool:
        if url == OVERVIEW_CMD:
            open_setup_for(_current_deck())
            return False
        return link_handler(url)

    return handler


def on_profile_will_close() -> None:
    if _ctx is None:
        return
    for w in list(_ctx.windows):
        w.save_and_close()
    for d in list(_ctx.dialogs):
        d.close()


def register(module: str, user_files: str) -> None:
    """Called once from the add-on's ``__init__``."""
    global _ctx
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists
    # (and always None under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    _ctx = AddonContext(module, user_files)
    action = QAction(TOOLS_LABEL, mw)
    qconnect(action.triggered, lambda: open_setup_for(_current_deck()))
    mw.form.menuTools.addAction(action)
    gui_hooks.deck_browser_will_show_options_menu.append(on_gear_menu)
    gui_hooks.overview_will_render_bottom.append(on_overview_bottom)
    gui_hooks.profile_will_close.append(on_profile_will_close)
