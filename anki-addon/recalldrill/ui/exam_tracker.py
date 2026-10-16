"""Exam tracker on the deck screen (v0.4 step 2; docs/DECISIONS.md, "Step 2: real numbers").

A status pill, a thin progress bar and a hover card on each exam deck's row, from real numbers
(``anki_io/exam_tracker.py`` reads them; ``exam_tracker.py`` holds the rules). On by default
(config ``exam_tracker``; Tools → "Recall Drill: exam tracker"). It only reads the collection.

How it is injected (checked against Anki 26.08.1's ``aqt.deckbrowser``):

- ``deck_browser_will_render_content`` runs on every render of the deck screen
  (after studying, sync, collapse, expand), so the display survives redraws.
  It appends one ``<script type="application/json">`` block to the stats
  section: per deck id, the row display and the card as HTML built here (deck
  names escaped), and which card is pinned. The deck tree it walks is the one
  Anki already holds in memory for that render. **The hook never computes**: it draws
  what is in the cache, and asks for a background run when the cache is stale.
- ``webview_will_set_content`` adds ``web/exam_tracker.js`` and ``.css`` to the
  deck browser's web view only, when the flag is on.
- The script finds each row by its ``<tr id="<deck id>">`` and appends the
  display inside the deck cell. The card is a ``position: fixed`` element on
  ``<body>``, so no table CSS (the Redesign add-on's, or stock's) can clip or
  move it. Nothing else in the page is touched, and the deck link keeps its
  stock ``onclick``.
- The pin goes to Python as ``pycmd("rdet:pin:<id>")`` and is kept in the profile
  (``exam_tracker.json``), so it comes back after a redraw and after a restart.

The cache and the refresh rule are in ``tracker_cache.py``. The reader runs in a
``QueryOp``; when its result arrives the deck screen is redrawn once, if it is still showing.
"""

from __future__ import annotations

import html
import json
import logging
from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, cast

from .. import exam_tracker as rules
from ..addon_config import parse_config
from ..exam_tracker import STATUS_ICON, STATUS_WORD, Status, TrackerNumbers
from ..pacing import short_date
from ..storage import EXAM_TRACKER, Storage
from ..tracker_cache import NumbersCache, Refresher

log = logging.getLogger(__name__)

CONFIG_KEY = "exam_tracker"
LABEL = "Recall Drill: exam tracker"
DATA_ID = "rd-exam-tracker-data"
PIN_PREFIX = "rdet:pin:"
UNPIN_CMD = "rdet:unpin"
WEB_PATTERN = r"web/exam_tracker\.(js|css)"
"""Regex for ``setWebExports``: only the two tracker files are served."""

_RANK: dict[Status, int] = {"exam": 0, "green": 1, "amber": 2, "red": 3}
"""Which status a collapsed parent shows: the worst one below it. An exam today is neutral,
so it ranks under green."""


class TreeNode(Protocol):
    """What this module reads of ``DeckTreeNode`` (duck-typed, so tests need no Anki)."""

    deck_id: int
    name: str
    level: int
    collapsed: bool

    @property
    def children(self) -> Iterable[Any]: ...


@dataclass(frozen=True)
class Row:
    deck_id: int
    name: str
    """Full name, parents joined with ``::``."""
    level: int
    collapsed: bool
    has_children: bool
    descendants: tuple[tuple[int, str], ...]
    """(deck id, full name) of every deck below this one, depth first (shown or not)."""
    hidden: bool = False
    """An ancestor is collapsed, so the deck screen has no row for it."""


def rows_from_tree(top: TreeNode) -> list[Row]:
    """Flattens the deck tree (``top`` is Anki's invisible root) into rows, parents first."""

    def walk(node: TreeNode, prefix: str, hidden: bool) -> Iterator[Row]:
        full = f"{prefix}::{node.name}" if prefix else node.name
        kids = list(node.children)
        below: list[tuple[int, str]] = []

        def names(n: TreeNode, pre: str) -> None:
            for k in n.children:
                nm = f"{pre}::{k.name}"
                below.append((k.deck_id, nm))
                names(k, nm)

        names(node, full)
        yield Row(
            node.deck_id, full, node.level, bool(node.collapsed), bool(kids), tuple(below), hidden
        )
        for kid in kids:
            yield from walk(kid, full, hidden or bool(node.collapsed))

    out: list[Row] = []
    for child in top.children:
        out.extend(walk(child, "", False))
    return out


def display_for(
    row: Row, numbers: Mapping[int, TrackerNumbers]
) -> tuple[str, TrackerNumbers] | None:
    """The deck name and numbers a row shows, or None.

    A deck with its own numbers (an exam deck) shows them. A collapsed deck without any shows
    its worst descendant's (red beats amber beats green; the first in tree order on a tie). An
    expanded deck without any shows nothing: its children show their own. A deck that only
    inherits a parent's date has no numbers of its own."""
    own = numbers.get(row.deck_id)
    if own is not None:
        return row.name, own
    if not row.collapsed:
        return None
    best: tuple[str, TrackerNumbers] | None = None
    for did, name in row.descendants:
        n = numbers.get(did)
        if n is not None and (best is None or _RANK[n.status] > _RANK[best[1].status]):
            best = (name, n)
    return best


def _n(value: int) -> str:
    return f"{value:,}"


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def days_phrase(f: TrackerNumbers) -> str:
    """ "8 days to finish", or "finish date passed" (the row's and the setup panel's wording)."""
    if f.finish_passed:
        return "finish date passed"
    return f"{f.days_left} day{'' if f.days_left == 1 else 's'} to finish"


def panel_summary(f: TrackerNumbers) -> tuple[str, str]:
    """(the status pill's text, the line beside it) for the setup panel's header: the pill is
    the tracker's icon plus word; the line is "N days to finish · exam Fri Oct 23", or just the
    exam on the exam day."""
    pill = f"{STATUS_ICON[f.status]} {STATUS_WORD[f.status]}"
    exam = f"exam {short_date(f.exam_date)}"
    if f.needed is None:
        return pill, exam
    return pill, f"{days_phrase(f)} · {exam}"


def cached_numbers(deck_id: int | None, day: date | None) -> TrackerNumbers | None:
    """The tracker's last result for exam deck ``deck_id`` on Anki day ``day``, or None (no
    exam, or no result yet). Reads the in-memory cache only, never the collection."""
    if deck_id is None or day is None:
        return None
    return _cache.get(deck_id, day)


def row_html(deck_name: str, f: TrackerNumbers, *, via: str | None, level: int) -> str:
    """The status pill, bar, days and the "N a day" line, shown under the deck name.

    The bar's segments are done today / drill / new / reviews, out of Done today + Cards
    left. On the exam day the pill says "Exam today" and there is no days or "a day" figure."""
    word = STATUS_WORD[f.status]
    parts = (
        ("done", f.done_today, "done today"),
        ("drill", f.drill, "drill to go"),
        ("new", f.new, "new"),
        ("rev", f.reviews, "reviews due"),
    )
    segs = "".join(
        f'<i class="rd-seg rd-seg-{k}" style="flex-grow:{v}"></i>' for k, v, _ in parts if v
    )
    bar_label = ", ".join(f"{_n(v)} {label}" for _, v, label in parts)
    via_html = f'<span class="rd-via">via {_e(via)}</span>' if via else ""
    if f.needed is None:
        days_html = ""
        line = f"{_n(f.done_today)} done today"
    else:
        days = days_phrase(f)
        days_html = f'<span class="rd-days">{_e(days)}</span>'
        # The exam date stays on the row (Don, 2026-10-15): the countdown is to the finish date.
        days_html += f'<span class="rd-exam-on">· exam {_e(short_date(f.exam_date))}</span>'
        line = f"{_n(f.needed)} a day needed · {_n(f.done_today)} done today"
    return (
        f'<div class="rd-et rd-{f.status}" style="--rd-lvl:{max(level - 1, 0)}">'
        f'<button type="button" class="rd-pill" aria-pressed="false"'
        f' aria-label="{_e(word)}: details for {_e(deck_name)}">'
        f'<span class="rd-icon" aria-hidden="true">{STATUS_ICON[f.status]}</span>'
        f"{_e(word)}</button>"
        f'<span class="rd-bar" role="img" aria-label="{_e(bar_label)}">{segs}</span>'
        f"{days_html}"
        f"{via_html}"
        f'<span class="rd-line">{_e(line)}</span>'
        "</div>"
    )


PATH_SEP = " › "


def title_html(deck_name: str, exam: str) -> str:
    """The card's head: the deck's own name (bold) with the exam at the right, and under it, when
    the deck has a parent, the parent path in small gray text. Every part is escaped."""
    *parents, leaf = deck_name.split("::")
    path = f'<div class="rd-card-path">{_e(PATH_SEP.join(parents))}</div>' if parents else ""
    return (
        '<div class="rd-card-head"><div class="rd-card-line">'
        f'<strong class="rd-card-title">{_e(leaf)}</strong>'
        f'<span class="rd-card-exam">{_e(exam)}</span></div>{path}</div>'
    )


def card_html(deck_name: str, f: TrackerNumbers) -> str:
    """The hover card. On the exam day it shows Cards left and Done today only (no "a day",
    no estimate)."""
    split = f"{_n(f.drill)} drill · {_n(f.new)} new · {_n(f.reviews)} reviews"
    if f.needed is None:
        nums = (
            f"<div><b>{_n(f.cards_left)}</b><span>left</span></div>"
            f"<div><b>{_n(f.done_today)}</b><span>done today</span></div>"
        )
        foot = f"<div>{_e(split)}</div>"
    else:
        nums = (
            f"<div><b>{_n(f.cards_left)}</b><span>left</span></div>"
            f"<div><b>{_n(f.needed)}</b><span>a day</span></div>"
            f"<div><b>{_n(f.done_today)} of {_n(f.needed)}</b><span>today</span></div>"
        )
        foot = f"<div>{_e(split)}</div><div>{_e(rules.est_text(f.est_seconds))}</div>"
        if f.finish_date is not None:
            when = short_date(f.finish_date)
            finish = f"Finish date {when} passed" if f.finish_passed else f"Finish by {when}"
            foot += f"<div>{_e(finish)}</div>"
    return (
        f'<div class="rd-card rd-{f.status}" role="dialog"'
        f' aria-label="Exam details: {_e(deck_name)}">'
        f"{title_html(deck_name, rules.exam_text(f.exam_date))}"
        f'<div class="rd-card-nums">{nums}</div>'
        f'<div class="rd-card-split">{foot}</div>'
        "</div>"
    )


def build_payload(
    rows: Iterable[Row], pinned: int | None, numbers: Mapping[int, TrackerNumbers]
) -> dict[str, Any]:
    """``{"decks": {deck id: {status, row, card}}, "pinned": id or None}``. A pin on a
    deck with no display now is not sent (``pin_to_drop`` decides whether to forget it)."""
    decks: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.hidden:
            continue
        shown = display_for(row, numbers)
        if shown is None:
            continue
        name, f = shown
        via = None if name == row.name else name.rsplit("::", 1)[-1]
        decks[str(row.deck_id)] = {
            "status": f.status,
            "row": row_html(name, f, via=via, level=row.level),
            "card": card_html(name, f),
        }
    keep = pinned if pinned is not None and str(pinned) in decks else None
    return {"decks": decks, "pinned": keep}


def script_tag(payload: dict[str, Any]) -> str:
    """The JSON block. ``<``, ``>``, ``&`` and the line separators are escaped so no value
    can end the tag early. The two separators are written as escapes (``"\\u2028"``), never as
    the raw characters: a raw one is invisible and was once lost in an edit, which turned every
    space of the row HTML into U+2028 and broke the display."""
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    return f'<script type="application/json" id="{DATA_ID}">{text}</script>'


def inject(
    top: TreeNode, stats_html: str, pinned: int | None, numbers: Mapping[int, TrackerNumbers]
) -> str:
    """``stats_html`` with the data block appended (the deck screen's stats section)."""
    return stats_html + script_tag(build_payload(rows_from_tree(top), pinned, numbers))


# --- the pin, kept in the profile ------------------------------------------------------


def read_pin(storage: Storage) -> int | None:
    """The pinned deck id from ``exam_tracker.json`` (``{"pinned": <deck id> | null}``)."""
    data = storage.read_json(EXAM_TRACKER, {})
    pin = cast(dict[str, Any], data).get("pinned") if isinstance(data, dict) else None
    return pin if isinstance(pin, int) and not isinstance(pin, bool) else None


def write_pin(storage: Storage, pin: int | None) -> None:
    if read_pin(storage) == pin:
        return
    storage.write_json(EXAM_TRACKER, {"pinned": pin})


def pin_to_drop(pinned: int | None, numbers: Mapping[int, TrackerNumbers], fresh: bool) -> bool:
    """A pin on a deck that is no longer an exam deck is dropped, silently. Only judged on
    fresh numbers: before the first result arrives the pin is kept."""
    return pinned is not None and fresh and pinned not in numbers


def handle_message(message: str, storage: Storage) -> bool:
    """The pin messages from the page. True when ``message`` was ours."""
    if message == UNPIN_CMD:
        write_pin(storage, None)
        return True
    if message.startswith(PIN_PREFIX):
        tail = message[len(PIN_PREFIX) :]
        write_pin(storage, int(tail) if tail.isdigit() else None)
        return True
    return False


# --- the flag --------------------------------------------------------------------------


class _AddonManager(Protocol):
    def getConfig(self, module: str) -> dict[str, Any] | None: ...  # noqa: N802
    def writeConfig(self, module: str, conf: dict[str, Any]) -> None: ...  # noqa: N802


def is_on(manager: _AddonManager, module: str) -> bool:
    """The ``exam_tracker`` flag (default on; a missing or mistyped value is the default). An
    old ``exam_tracker_test`` key is ignored."""
    return parse_config(manager.getConfig(module)).exam_tracker


def toggle(
    manager: _AddonManager, module: str, refresh: Any, storage: Storage | None = None
) -> bool:
    """Flips the flag, saves it and asks for a redraw. Returns the new value. Turning it off
    forgets the pin."""
    conf = dict(manager.getConfig(module) or {})
    new = not is_on(manager, module)
    conf[CONFIG_KEY] = new
    manager.writeConfig(module, conf)
    if not new and storage is not None:
        write_pin(storage, None)
    refresh()
    return new


# --- state and Anki wiring ------------------------------------------------------------

_cache = NumbersCache()
_refresher: Refresher[Any] | None = None


def request_refresh() -> None:
    """Something the numbers depend on changed (a collection change, a sync, a handoff, a
    session, a saved pacing date): recompute in the background, when the deck screen is
    showing; otherwise the next time it is drawn."""
    _cache.invalidate()
    ref = _refresher
    if ref is None:
        return
    from aqt import mw

    if getattr(mw, "state", None) == "deckBrowser":
        ref.request()


def start_reader(storage: Storage, finish: Any) -> None:
    """Runs ``read_trackers`` off the main thread (a ``QueryOp``); ``finish(result)`` on the main
    thread, ``finish(None)`` when it failed."""
    from aqt import mw
    from aqt.operations import QueryOp

    from ..anki_io.exam_tracker import read_trackers

    def failed(exc: Exception) -> None:
        log.warning("Recall Drill: the exam tracker could not read the collection: %s", exc)
        finish(None)

    QueryOp(parent=mw, op=lambda col: read_trackers(col, storage), success=finish).failure(
        failed
    ).run_in_background()


def register(ctx: Any) -> None:
    """Hooks (called from ``entry.register``). Every hook does nothing while the flag is off."""
    global _refresher
    from aqt import gui_hooks, mw
    from aqt.deckbrowser import DeckBrowser
    from aqt.qt import QAction, qconnect

    from ..anki_io.workload import today_for

    module: str = ctx.module
    manager = mw.addonManager
    folder = manager.addonFromModule(module)
    manager.setWebExports(module, WEB_PATTERN)

    def redraw() -> None:
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()

    def run(finish: Any) -> None:
        _cache.started()
        start_reader(ctx.storage(), finish)

    def on_result(result: Any) -> None:
        _cache.store(result.day, result.numbers)
        redraw()  # once per fresh result, only if the deck screen is still showing

    _refresher = Refresher(run, on_result)

    def on_content(deck_browser: DeckBrowser, content: Any) -> None:
        if not is_on(manager, module):
            return
        try:
            col = mw.col
            if col is None:
                return
            today, _rollover = today_for(col)
            if _cache.needs_refresh(today):
                assert _refresher is not None
                # Background; the cache is drawn as it is now. While a run is going, only a
                # change made since it started asks for another one (not every redraw).
                if _cache.dirty or not _refresher.running:
                    _refresher.request()
            numbers = _cache.for_day(today)
            storage = ctx.storage()
            pinned = read_pin(storage)
            if pin_to_drop(pinned, numbers, fresh=not _cache.needs_refresh(today)):
                write_pin(storage, None)
                pinned = None
            top = deck_browser._render_data.tree  # pyright: ignore[reportPrivateUsage]
            content.stats = inject(top, content.stats, pinned, numbers)
        except Exception:  # a decoration must never break the deck screen
            log.warning("Recall Drill: the exam tracker could not draw", exc_info=True)

    def on_web_content(web_content: Any, context: object | None) -> None:
        if isinstance(context, DeckBrowser) and is_on(manager, module):
            web_content.css.append(f"/_addons/{folder}/web/exam_tracker.css")
            web_content.js.append(f"/_addons/{folder}/web/exam_tracker.js")

    def on_message(handled: tuple[bool, Any], message: str, context: Any) -> tuple[bool, Any]:
        if isinstance(context, DeckBrowser) and handle_message(message, ctx.storage()):
            return True, None
        return handled

    def on_operation(changes: Any, handler: object | None) -> None:
        if changes.card or changes.note or changes.deck or changes.study_queues:
            request_refresh()

    def on_profile_closing() -> None:
        _cache.clear()

    action = QAction(LABEL, mw)
    action.setCheckable(True)
    action.setChecked(is_on(manager, module))

    def flip() -> None:
        action.setChecked(toggle(manager, module, redraw, ctx.storage()))

    qconnect(action.triggered, flip)
    mw.form.menuTools.addAction(action)
    gui_hooks.deck_browser_will_render_content.append(on_content)
    gui_hooks.webview_will_set_content.append(on_web_content)
    gui_hooks.webview_did_receive_js_message.append(on_message)
    gui_hooks.operation_did_execute.append(on_operation)
    gui_hooks.sync_did_finish.append(request_refresh)
    gui_hooks.profile_will_close.append(on_profile_closing)
