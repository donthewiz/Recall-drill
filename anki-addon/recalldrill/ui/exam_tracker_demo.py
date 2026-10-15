"""Exam tracker hover test (v0.4 step 1; docs/DECISIONS.md, "v0.4 exam tracker").

A throwaway proof, with FAKE numbers, that the status tag, progress bar and
hover card look and behave right on Anki's deck screen. Off by default
(config ``exam_tracker_test``; Tools → "Recall Drill: exam tracker test"). It
reads and writes no collection and makes no network call. Step 2 replaces
``FAKE`` with real numbers and keeps the rest.

How it is injected (checked against Anki 26.08.1's ``aqt.deckbrowser``):

- ``deck_browser_will_render_content`` runs on every render of the deck screen
  (after studying, sync, collapse, expand), so the display survives redraws.
  It appends one ``<script type="application/json">`` block to the stats
  section: per deck id, the row display and the card as HTML built here (deck
  names escaped), and which card is pinned. The deck tree it walks is the one
  Anki already holds in memory for that render.
- ``webview_will_set_content`` adds ``web/exam_tracker.js`` and ``.css`` to the
  deck browser's web view only, when the flag is on.
- The script finds each row by its ``<tr id="<deck id>">`` and appends the
  display inside the deck cell. The card is a ``position: fixed`` element on
  ``<body>``, so no table CSS (the Redesign add-on's, or stock's) can clip or
  move it. Nothing else in the page is touched, and the deck link keeps its
  stock ``onclick``.
- The pin goes to Python as ``pycmd("rdet:pin:<id>")`` (kept in memory only)
  so it comes back after a redraw.
"""

from __future__ import annotations

import html
import json
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from typing import Any, Literal, Protocol

Status = Literal["green", "amber", "red"]

CONFIG_KEY = "exam_tracker_test"
LABEL = "Recall Drill: exam tracker test"
DATA_ID = "rd-exam-tracker-data"
PIN_PREFIX = "rdet:pin:"
UNPIN_CMD = "rdet:unpin"
WEB_PATTERN = r"web/exam_tracker\.(js|css)"
"""Regex for ``setWebExports``: only the two test files are served."""


@dataclass(frozen=True)
class Fake:
    """One deck's made-up numbers."""

    status: Status
    exam: str
    days_left: int
    needed_a_day: int
    done_today: int
    minutes: int
    drill: int
    new: int
    reviews: int

    @property
    def cards_left(self) -> int:
        return self.drill + self.new + self.reviews


# The fake data, in one place, keyed by full deck name. Step 2 replaces this, and the real
# tracker must key by deck id, not name, so renaming a deck doesn't break it.
FAKE: dict[str, Fake] = {
    "Human Anatomy & Physiology 1::Lab::Lab 2": Fake(
        "red", "Practical · Fri Oct 23", 8, 61, 18, 55, 330, 110, 50
    ),
    "Human Anatomy & Physiology 1::Lecture::Lecture 3::Muscle Tissue Chapter 10": Fake(
        "amber", "Test · Mon Oct 26", 11, 13, 8, 10, 90, 40, 10
    ),
    "Medical Terminology": Fake("green", "Final · Tue Dec 8", 54, 70, 70, 60, 1500, 2100, 180),
}

STATUS_WORD: dict[Status, str] = {"green": "On pace", "amber": "Slightly behind", "red": "Behind"}
STATUS_ICON: dict[Status, str] = {"green": "✓", "amber": "▲", "red": "✖"}
_RANK: dict[Status, int] = {"green": 1, "amber": 2, "red": 3}


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
    descendants: tuple[str, ...]
    """Full names of every deck below this one, depth first (shown or not)."""
    hidden: bool = False
    """An ancestor is collapsed, so the deck screen has no row for it."""


def rows_from_tree(top: TreeNode) -> list[Row]:
    """Flattens the deck tree (``top`` is Anki's invisible root) into rows, parents first."""

    def walk(node: TreeNode, prefix: str, hidden: bool) -> Iterator[Row]:
        full = f"{prefix}::{node.name}" if prefix else node.name
        kids = list(node.children)
        below: list[str] = []

        def names(n: TreeNode, pre: str) -> None:
            for k in n.children:
                nm = f"{pre}::{k.name}"
                below.append(nm)
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


def display_for(row: Row, fake: dict[str, Fake] | None = None) -> tuple[str, Fake] | None:
    """The deck name and numbers a row shows, or None.

    A deck with its own entry shows it. A collapsed deck without one shows its worst
    descendant's (red beats amber beats green; the first in tree order on a tie). An
    expanded deck without an entry shows nothing: its children show their own."""
    data = FAKE if fake is None else fake
    own = data.get(row.name)
    if own is not None:
        return row.name, own
    if not row.collapsed:
        return None
    best: tuple[str, Fake] | None = None
    for name in row.descendants:
        f = data.get(name)
        if f is not None and (best is None or _RANK[f.status] > _RANK[best[1].status]):
            best = (name, f)
    return best


def _n(value: int) -> str:
    return f"{value:,}"


def _e(text: str) -> str:
    return html.escape(text, quote=True)


def row_html(deck_name: str, f: Fake, *, via: str | None, level: int) -> str:
    """The status pill, bar, days and the "N a day" line, shown under the deck name."""
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
    days = f"{f.days_left} day{'' if f.days_left == 1 else 's'} left"
    via_html = f'<span class="rd-via">via {_e(via)}</span>' if via else ""
    return (
        f'<div class="rd-et rd-{f.status}" style="--rd-lvl:{max(level - 1, 0)}">'
        f'<button type="button" class="rd-pill" aria-pressed="false"'
        f' aria-label="{_e(word)}: details for {_e(deck_name)}">'
        f'<span class="rd-icon" aria-hidden="true">{STATUS_ICON[f.status]}</span>'
        f"{_e(word)}</button>"
        f'<span class="rd-bar" role="img" aria-label="{_e(bar_label)}">{segs}</span>'
        f'<span class="rd-days">{_e(days)}</span>'
        f"{via_html}"
        f'<span class="rd-line">{f.needed_a_day} a day needed · {f.done_today} done today</span>'
        "</div>"
    )


def card_html(deck_name: str, f: Fake) -> str:
    """The hover card. The footer says TEST so the numbers can't pass as real."""
    split = f"{_n(f.drill)} drill · {_n(f.new)} new · {_n(f.reviews)} reviews"
    return (
        f'<div class="rd-card rd-{f.status}" role="dialog"'
        f' aria-label="Exam details: {_e(deck_name)}">'
        f'<div class="rd-card-head"><strong class="rd-card-title">{_e(deck_name)}</strong>'
        f'<span class="rd-card-exam">{_e(f.exam)}</span></div>'
        '<div class="rd-card-nums">'
        f"<div><b>{_n(f.cards_left)}</b><span>left</span></div>"
        f"<div><b>{f.needed_a_day}</b><span>a day</span></div>"
        f"<div><b>{f.done_today} of {f.needed_a_day}</b><span>today</span></div>"
        "</div>"
        f'<div class="rd-card-split"><div>{_e(split)}</div>'
        f"<div>Est. {f.minutes} min today</div></div>"
        '<div class="rd-card-test">TEST · fake numbers, not your collection</div>'
        "</div>"
    )


def build_payload(
    rows: Iterable[Row], pinned: int | None, fake: dict[str, Fake] | None = None
) -> dict[str, Any]:
    """``{"decks": {deck id: {status, row, card}}, "pinned": id or None}``. A pin on a
    deck with no display now is dropped."""
    decks: dict[str, dict[str, str]] = {}
    for row in rows:
        if row.hidden:
            continue
        shown = display_for(row, fake)
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
    can end the tag early."""
    text = (
        json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        .replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace(" ", "\\u2028")
        .replace(" ", "\\u2029")
    )
    return f'<script type="application/json" id="{DATA_ID}">{text}</script>'


def inject(top: TreeNode, stats_html: str, pinned: int | None) -> str:
    """``stats_html`` with the data block appended (the deck screen's stats section)."""
    return stats_html + script_tag(build_payload(rows_from_tree(top), pinned))


# --- state and Anki wiring ------------------------------------------------------------

_pinned: int | None = None
"""The pinned card's deck id. In memory only: gone when Anki closes."""


def pinned() -> int | None:
    return _pinned


def handle_message(message: str) -> bool:
    """The pin messages from the page. True when ``message`` was ours."""
    global _pinned
    if message == UNPIN_CMD:
        _pinned = None
        return True
    if message.startswith(PIN_PREFIX):
        tail = message[len(PIN_PREFIX) :]
        _pinned = int(tail) if tail.isdigit() else None
        return True
    return False


class _AddonManager(Protocol):
    def getConfig(self, module: str) -> dict[str, Any] | None: ...  # noqa: N802
    def writeConfig(self, module: str, conf: dict[str, Any]) -> None: ...  # noqa: N802


def is_on(manager: _AddonManager, module: str) -> bool:
    conf = manager.getConfig(module)
    return bool(conf.get(CONFIG_KEY)) if isinstance(conf, dict) else False


def toggle(manager: _AddonManager, module: str, refresh: Any) -> bool:
    """Flips the flag, saves it and asks for a redraw. Returns the new value."""
    global _pinned
    conf = dict(manager.getConfig(module) or {})
    new = not bool(conf.get(CONFIG_KEY))
    conf[CONFIG_KEY] = new
    manager.writeConfig(module, conf)
    if not new:
        _pinned = None
    refresh()
    return new


def register(module: str) -> None:
    """Hooks (called from ``entry.register``). Every hook does nothing while the flag is off."""
    from aqt import gui_hooks, mw
    from aqt.deckbrowser import DeckBrowser
    from aqt.qt import QAction, qconnect

    manager = mw.addonManager
    folder = manager.addonFromModule(module)
    manager.setWebExports(module, WEB_PATTERN)

    def on_content(deck_browser: DeckBrowser, content: Any) -> None:
        if not is_on(manager, module):
            return
        try:
            top = deck_browser._render_data.tree  # pyright: ignore[reportPrivateUsage]
            content.stats = inject(top, content.stats, _pinned)
        except Exception:  # a decoration must never break the deck screen
            return

    def on_web_content(web_content: Any, context: object | None) -> None:
        if isinstance(context, DeckBrowser) and is_on(manager, module):
            web_content.css.append(f"/_addons/{folder}/web/exam_tracker.css")
            web_content.js.append(f"/_addons/{folder}/web/exam_tracker.js")

    def on_message(handled: tuple[bool, Any], message: str, context: Any) -> tuple[bool, Any]:
        if isinstance(context, DeckBrowser) and handle_message(message):
            return True, None
        return handled

    def refresh() -> None:
        if mw.state == "deckBrowser":
            mw.deckBrowser.refresh()

    action = QAction(LABEL, mw)
    action.setCheckable(True)
    action.setChecked(is_on(manager, module))

    def flip() -> None:
        action.setChecked(toggle(manager, module, refresh))

    qconnect(action.triggered, flip)
    mw.form.menuTools.addAction(action)
    gui_hooks.deck_browser_will_render_content.append(on_content)
    gui_hooks.webview_will_set_content.append(on_web_content)
    gui_hooks.webview_did_receive_js_message.append(on_message)
