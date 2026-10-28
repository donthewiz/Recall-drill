"""The Tools → Card Triage menu and the reviewer hooks."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from aqt import gui_hooks, mw
from aqt.qt import QAction, QKeySequence, QMenu, QTimer, QWidget, qconnect

from .. import bar
from ..config import Config, parse_config
from .prompt import PromptController

MENU_LABEL = "Card Triage"
RELEASE_LABEL = "Release all set-aside cards…"
SHOW_LABEL = "Show set-aside cards"
SETTINGS_LABEL = "Settings…"

_module: str | None = None
_prompt: PromptController | None = None
_timer: QTimer | None = None


def config() -> Config:
    """The saved config (defaults for anything missing)."""
    raw = mw.addonManager.getConfig(_module) if _module else None
    return parse_config(raw)


def on_shortcuts(state: str, shortcuts: list[tuple[str, Callable[[], None]]]) -> None:
    """Add the set-aside key to the reviewer's keys (state ``review``: question and answer)."""
    from .actions import set_aside_current

    if state == "review":
        shortcuts.append((config().set_aside_key, set_aside_current))


def _schedule(seconds: int, fn: Callable[[], None]) -> None:
    global _timer
    _cancel()
    timer = QTimer(mw)
    timer.setSingleShot(True)
    qconnect(timer.timeout, fn)
    timer.start(seconds * 1000)
    _timer = timer


def _cancel() -> None:
    global _timer
    if _timer is not None:
        _timer.stop()
        _timer.deleteLater()
        _timer = None


def _run_js(js: str) -> None:
    if mw.reviewer is not None and mw.reviewer.web is not None:
        mw.reviewer.web.eval(js)


def _again_count(card_id: int) -> int:
    from anki.cards import CardId

    from ..anki_io import triage

    return triage.learn_again_count(mw.col, CardId(card_id))  # pyright: ignore[reportArgumentType]


def _current_card_id() -> int | None:
    card = mw.reviewer.card if mw.state == "review" else None
    return int(card.id) if card is not None else None


def make_prompt() -> PromptController:
    from .actions import set_aside_current

    return PromptController(
        config=config,
        run_js=_run_js,
        again_count=_again_count,
        schedule=_schedule,
        cancel=_cancel,
        current_card_id=_current_card_id,
        set_aside=set_aside_current,
    )


def on_show_question(card: Any) -> None:
    if _prompt is not None:
        _prompt.question_shown(card)


def on_answered(_reviewer: Any, _card: Any, _ease: int) -> None:
    if _prompt is not None:
        _prompt.card_answered()


def on_reviewer_will_end() -> None:
    if _prompt is not None:
        _prompt.reviewer_ended()


def on_js_message(handled: tuple[bool, Any], message: str, _context: Any) -> tuple[bool, Any]:
    """The bar's buttons (``pycmd('card_triage:...')``). This filter sees every web view's
    messages: anything that isn't ours goes on unchanged."""
    if not bar.is_ours(message):
        return handled
    if _prompt is not None:
        _prompt.command(message)
    return (True, None)


def live_reviewer_keys() -> dict[str, str]:
    """The reviewer's keys right now (answer keys can be rebound), minus our own."""
    from ..keys import normalize_key
    from .actions import set_aside_current

    found: dict[str, str] = {}
    try:
        for key, fn in mw.reviewer._shortcutKeys():  # pyright: ignore[reportPrivateUsage]
            norm = normalize_key(key) if isinstance(key, str) else None
            if norm is not None and fn is not set_aside_current:
                found[norm] = "the reviewer"
    except Exception:  # a custom reviewer, or no collection loaded: the built-in list still applies
        return {}
    return found


def action_keys(window: QWidget) -> dict[str, str]:
    """The menu shortcuts on ``window`` right now (Anki's and other add-ons'). A state shortcut
    with one of these keys is ambiguous to Qt, and then neither fires."""
    from ..keys import normalize_key

    actions: list[QAction] = list(window.findChildren(QAction))
    for menu in window.findChildren(QMenu):
        actions.extend(menu.actions())
    found: dict[str, str] = {}
    for action in actions:
        name = action.text().replace("&", "").strip()
        for seq in action.shortcuts():
            norm = normalize_key(seq.toString(QKeySequence.SequenceFormat.PortableText))
            if norm is not None:
                found[norm] = f"the menu item \u201c{name}\u201d" if name else "a menu"
    return found


def live_keys() -> dict[str, str]:
    """Every key Anki's main window is using right now: the reviewer's and the menus'."""
    found = live_reviewer_keys()
    try:
        found.update(action_keys(mw))
    except Exception:  # no main window: the built-in lists still apply
        pass
    return found


def save_config(conf: dict[str, Any]) -> None:
    assert _module is not None
    mw.addonManager.writeConfig(_module, conf)
    if mw.state == "review":  # the new key works now, not at the next review session
        mw.clearStateShortcuts()
        mw.setStateShortcuts(list(mw.reviewer._shortcutKeys()))  # type: ignore  # pyright: ignore


def open_settings() -> bool:
    """Tools → Card Triage → Settings… and the Add-ons screen's Config button."""
    from .settings_dialog import SettingsDialog

    SettingsDialog(config(), save_config, live_keys, parent=mw).exec()
    return True


def build_menu(tools: QMenu) -> QMenu:
    """Tools → Card Triage with its items; returns the submenu."""
    from .actions import release_all, show_set_aside

    menu = tools.addMenu(MENU_LABEL)
    assert menu is not None

    def add(label: str, fn: Callable[[], object]) -> None:
        action = QAction(label, menu)
        qconnect(action.triggered, lambda _checked=False: fn())
        menu.addAction(action)

    add(SHOW_LABEL, show_set_aside)
    add(RELEASE_LABEL, release_all)
    menu.addSeparator()
    add(SETTINGS_LABEL, open_settings)
    return menu


def register(module: str) -> None:
    """Called once from the add-on's ``__init__``."""
    global _module, _prompt
    # aqt.mw is typed AnkiQt but is None until Anki's main window exists (and under pytest).
    if mw is None:  # pyright: ignore[reportUnnecessaryComparison]
        return
    _module = module
    mw.addonManager.setConfigAction(module, open_settings)
    _prompt = make_prompt()
    build_menu(mw.form.menuTools)
    gui_hooks.state_shortcuts_will_change.append(on_shortcuts)
    gui_hooks.reviewer_did_show_question.append(on_show_question)
    gui_hooks.reviewer_did_answer_card.append(on_answered)
    gui_hooks.reviewer_will_end.append(on_reviewer_will_end)
    gui_hooks.webview_did_receive_js_message.append(on_js_message)
