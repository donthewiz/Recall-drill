"""Entry points: Tools menu, the deck gear menu, the deck overview's button,
and closing drill windows with the profile.

Tools also has the ``rd::hard`` entries: the setup panel scoped to
``tag:rd::hard``, and Anki's own filtered-deck dialog pre-filled with that
search (Don builds the deck there; the add-on creates nothing by itself). And
the tuning report (Phase 5), and the waiting drill cards (2026-10-12), with
their once-a-day notice after the profile opens, and (v0.3) the section
progress table and the outcomes export (once at profile open, `export_on_open`).

Checked on 26.08.1 (docs/DECISIONS.md, "Entry points"):

- ``deck_browser_will_show_options_menu(menu, deck_id)`` adds to the gear menu.
- ``overview_will_render_bottom(link_handler, links)`` is a filter: the button
  goes into ``links`` and the returned handler answers its ``pycmd``. The
  bottom bar routes its messages to that handler, so
  ``webview_did_receive_js_message`` isn't needed.
- ``profile_will_close()``: open drill windows save and close.
- ``profile_did_open()``: the waiting-cards notice (read in a ``QueryOp``).
"""

from __future__ import annotations

from collections.abc import Callable

import aqt
from aqt import gui_hooks, mw
from aqt.qt import QAction, QMenu, qconnect

from ..anki_io.handoff import HARD_SEARCH
from .context import AddonContext

TOOLS_LABEL = "Recall Drill…"
HARD_LABEL = "Recall Drill: my rd::hard cards"
HARD_FILTERED_LABEL = "Recall Drill: filtered deck for rd::hard"
TUNING_LABEL = "Recall Drill: tuning report"
WAITING_LABEL = "Recall Drill: waiting cards"
SECTIONS_LABEL = "Recall Drill: sections"
EXPORT_LABEL = "Recall Drill: export outcomes now"
GEAR_LABEL = "Recall Drill this deck"
OVERVIEW_LABEL = "Recall Drill"
OVERVIEW_CMD = "recalldrill:setup"

_ctx: AddonContext | None = None


def open_setup_for(deck_id: int | None, order: str | None = None) -> None:
    """The setup panel for a deck, or its drill window if one is running. ``order``
    ("deck_order") opens it with that Order instead of the default."""
    if _ctx is None or mw.col is None:
        return
    from ..sessions import deck_key
    from .setup_dialog import open_setup

    if deck_id is not None and _ctx.raise_window(deck_key(deck_id)):
        return

    open_setup(_ctx, deck_id, order=order)


def open_hard_cards() -> None:
    """The setup panel over ``tag:rd::hard`` (narrowed to the cards that were hard)."""
    if _ctx is None or mw.col is None:
        return
    from ..sessions import search_key
    from .setup_dialog import open_setup

    if _ctx.raise_window(search_key(HARD_SEARCH)):
        return
    open_setup(_ctx, _current_deck(), search=HARD_SEARCH)


def open_hard_filtered_deck() -> None:
    """Anki's filtered-deck dialog, search pre-filled. Nothing is built until Don does."""
    if mw.col is None:
        return
    aqt.dialogs.open("FilteredDeckConfigDialog", mw, search=HARD_SEARCH)


def open_tuning() -> None:
    """The tuning report (next-day Again, holdout, baseline, suggestions)."""
    if _ctx is None or mw.col is None:
        return
    from .tuning_dialog import open_tuning_report

    open_tuning_report(_ctx)


def open_waiting_cards() -> None:
    """The drill cards still suspended and waiting, per deck."""
    if _ctx is None or mw.col is None:
        return
    from .waiting_dialog import open_waiting

    open_waiting(_ctx, open_setup_for)


def open_sections() -> None:
    """Which sections (subdecks) of the current deck are drilled."""
    if _ctx is None or mw.col is None:
        return
    from .sections_dialog import open_sections as show

    show(_ctx, open_setup_for, _current_deck(), open_setup_for)


def export_outcomes_now() -> None:
    """Tools → export outcomes now: the light export, then its folder."""
    if _ctx is None or mw.col is None:
        return
    from .export_ui import export_now

    export_now(_ctx)


def on_profile_did_open() -> None:
    if _ctx is None:
        return
    from .export_ui import export_in_background
    from .waiting_dialog import maybe_notify

    maybe_notify(_ctx)
    if _ctx.config().export_on_open:
        export_in_background(_ctx)


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
    for label, fn in (
        (TOOLS_LABEL, lambda: open_setup_for(_current_deck())),
        (HARD_LABEL, open_hard_cards),
        (HARD_FILTERED_LABEL, open_hard_filtered_deck),
        (TUNING_LABEL, open_tuning),
        (WAITING_LABEL, open_waiting_cards),
        (SECTIONS_LABEL, open_sections),
        (EXPORT_LABEL, export_outcomes_now),
    ):
        action = QAction(label, mw)
        qconnect(action.triggered, fn)
        mw.form.menuTools.addAction(action)
    gui_hooks.deck_browser_will_show_options_menu.append(on_gear_menu)
    gui_hooks.overview_will_render_bottom.append(on_overview_bottom)
    gui_hooks.profile_will_close.append(on_profile_will_close)
    gui_hooks.profile_did_open.append(on_profile_did_open)
