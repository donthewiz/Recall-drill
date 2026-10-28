"""The Tools → Card Triage menu and the reviewer hooks."""

from __future__ import annotations

from collections.abc import Callable

from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, qconnect

from ..config import Config, parse_config

MENU_LABEL = "Card Triage"
RELEASE_LABEL = "Release all set-aside cards…"
SHOW_LABEL = "Show set-aside cards"

_module: str | None = None


def config() -> Config:
    """The saved config (defaults for anything missing)."""
    raw = mw.addonManager.getConfig(_module) if _module else None
    return parse_config(raw)


def on_shortcuts(state: str, shortcuts: list[tuple[str, Callable[[], None]]]) -> None:
    """Add the set-aside key to the reviewer's keys (state ``review``: question and answer)."""
    from .actions import set_aside_current

    if state == "review":
        shortcuts.append((config().set_aside_key, set_aside_current))


def build_menu(tools: QMenu) -> QMenu:
    """Tools → Card Triage with its items; returns the submenu."""
    from .actions import release_all, show_set_aside

    menu = tools.addMenu(MENU_LABEL)
    assert menu is not None

    def add(label: str, fn: Callable[[], None]) -> None:
        action = QAction(label, menu)
        qconnect(action.triggered, lambda _checked=False: fn())
        menu.addAction(action)

    add(SHOW_LABEL, show_set_aside)
    add(RELEASE_LABEL, release_all)
    return menu


def register(module: str) -> None:
    """Called once from the add-on's ``__init__``."""
    global _module
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists (and under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    _module = module
    build_menu(mw.form.menuTools)
    gui_hooks.state_shortcuts_will_change.append(on_shortcuts)
