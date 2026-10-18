"""The page every Math Path window shows, and the bridge to it (pure).

Each window is one ``AnkiWebView`` showing :func:`shell_body` once. Python owns the state and
sends the whole screen as HTML with :func:`render_call` (``mp.render``); the page only draws it,
types it with MathJax, keeps the math fields' contents, and reports what the learner does through
``pycmd`` as ``mp:<kind>:<args>`` (:func:`parse_command`).

Page → Python commands:

    mp:act:<name>[:<arg>]        a click on an element with ``data-act`` (and ``data-arg``)
    mp:field:<id>:<latex>        a math field changed
    mp:text:<id>:<text>          a text box changed
    mp:select:<id>:<value>       a list changed
    mp:focus:<id>                a math field or text box got the focus
    mp:enter:<id>                Enter (``<id>`` is the field it was pressed in, or empty)
    mp:ctrl-enter:               Ctrl+Enter
    mp:esc:                      Esc
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from html import escape

from . import theme

PREFIX = "mp:"

SCRIPTS: tuple[str, ...] = ("mathlive/mathlive.min.js", "mp_page.js")
"""Under ``web/``, in load order."""
STYLES: tuple[str, ...] = ("mp_page.css",)
MATHJAX_SCRIPTS: tuple[str, ...] = ("js/mathjax.js", "js/vendor/mathjax/tex-chtml-full.js")
"""Anki's own MathJax (served by Anki; the same files the reviewer and Recall Drill use)."""

MIN_TARGET_PX = 48
"""Every palette button is at least this big in both directions."""


def web_pattern() -> str:
    """The ``setWebExports`` regex for ``web/``: the page's files and MathLive with its fonts."""
    return r"web/(mathlive/(mathlive\.min\.js|fonts/KaTeX_[A-Za-z0-9_-]+\.woff2)|mp_page\.(js|css))"


def script_urls(folder: str) -> list[str]:
    """Scripts for ``stdHtml(js=...)``: Anki's MathJax first, then MathLive and the page."""
    return [*MATHJAX_SCRIPTS, *(f"/_addons/{folder}/web/{name}" for name in SCRIPTS)]


def css_urls(folder: str) -> list[str]:
    return [f"/_addons/{folder}/web/{name}" for name in STYLES]


def shell_body() -> str:
    """The page body: the colours as CSS variables and an empty root the screens render into."""
    return f'<style>{theme.css_vars()}</style><div id="mp-root"></div>'


@dataclass(frozen=True)
class PageView:
    html: str
    fields: dict[str, str] = field(default_factory=dict[str, str])
    """Math field id -> LaTeX it holds."""
    texts: dict[str, str] = field(default_factory=dict[str, str])
    """Text box / list id -> value."""
    readonly: tuple[str, ...] = ()
    focus: str = ""
    night: bool = False


KEEP_KINDS: tuple[str, ...] = ("focus", "field", "text")
"""Commands that only change state: the page already shows what was typed, so the redraw that
follows is a *keep* redraw (the live fields stay in the page; ``mp.render`` in ``mp_page.js``)."""


def render_call(view: PageView, keep: bool = False) -> str:
    """The JS that draws ``view``. ``keep``: leave the page's live fields and text boxes in place
    (a redraw after a focus, field or text message) instead of rebuilding them."""
    payload = {
        "html": view.html,
        "fields": view.fields,
        "texts": view.texts,
        "readonly": list(view.readonly),
        "focus": view.focus,
        "night": view.night,
        "keep": keep,
    }
    return f"mp.render({json.dumps(payload)});"


Shown = tuple[str, tuple[str, ...], bool]
"""What the page shows: the HTML, the read-only fields and the night flag."""


def redraw_call(view: PageView, keep: bool, last: Shown | None) -> tuple[str | None, Shown]:
    """The JS for a redraw (None: send nothing) and what is shown afterwards.

    A keep redraw of a screen that has not changed sends nothing: that is what ends the
    ``focusin`` -> ``mp:focus`` -> redraw -> ``focusin`` loop. Every redraw that is sent updates
    what is remembered as shown."""
    shown: Shown = (view.html, view.readonly, view.night)
    if keep and last == shown:
        return None, shown
    return render_call(view, keep), shown


@dataclass(frozen=True)
class Command:
    kind: str
    """``act``, ``field``, ``text``, ``select``, ``focus``, ``enter``, ``ctrl-enter`` or ``esc``."""
    a: str = ""
    b: str = ""


def parse_command(cmd: str) -> Command | None:
    """A ``pycmd`` string from the page, or None when it is not ours."""
    if not cmd.startswith(PREFIX):
        return None
    rest = cmd[len(PREFIX) :]
    kind, _, tail = rest.partition(":")
    if kind == "select":  # the value is the last part (a number or key); the id may hold ':'
        a, _, b = tail.rpartition(":")
        return Command(kind, a, b)
    if kind in ("act", "field", "text"):
        a, _, b = tail.partition(":")
        return Command(kind, a, b)
    if kind in ("focus", "enter"):
        return Command(kind, tail)
    if kind in ("ctrl-enter", "esc"):
        return Command(kind)
    return None


# -- palette --------------------------------------------------------------------------------------


@dataclass(frozen=True)
class PadButton:
    key: str
    glyph: str
    """HTML for the button's face."""
    tip: str
    group: str
    op: str
    """"insert" (MathLive ``insert`` of ``arg``) or "command" (``executeCommand``)."""
    arg: str


PAD_GROUPS = ("build", "symbols", "brackets", "edit")

PALETTE: tuple[PadButton, ...] = (
    PadButton(
        "frac",
        '<span class="mp-g-frac"><span>a</span><span>b</span></span>',
        "Fraction",
        "build",
        "insert",
        "\\frac{#@}{#?}",
    ),
    PadButton("power", "x<sup>n</sup>", "Power (exponent)", "build", "insert", "^{#?}"),
    PadButton("sqrt", "√", "Square root", "build", "insert", "\\sqrt{#0}"),
    PadButton("parens", "( )", "Parentheses", "build", "insert", "\\left(#0\\right)"),
    PadButton("abs", "|x|", "Absolute value", "build", "insert", "\\left|#0\\right|"),
    PadButton("pm", "±", "Plus or minus", "symbols", "insert", "\\pm"),
    PadButton("le", "≤", "Less than or equal to", "symbols", "insert", "\\le"),
    PadButton("ge", "≥", "Greater than or equal to", "symbols", "insert", "\\ge"),
    PadButton("pi", "π", "Pi", "symbols", "insert", "\\pi"),
    PadButton("i", "i", "Imaginary unit", "symbols", "insert", "i"),
    PadButton("inf", "∞", "Infinity", "symbols", "insert", "\\infty"),
    PadButton("cup", "∪", "Union", "symbols", "insert", "\\cup"),
    PadButton("lbracket", "[", "Left square bracket (closed end)", "brackets", "insert", "["),
    PadButton("lparen", "(", "Left parenthesis (open end)", "brackets", "insert", "("),
    PadButton("rparen", ")", "Right parenthesis (open end)", "brackets", "insert", ")"),
    PadButton("rbracket", "]", "Right square bracket (closed end)", "brackets", "insert", "]"),
    PadButton("comma", ",", "Comma", "brackets", "insert", ","),
    PadButton("backspace", "⌫", "Backspace", "edit", "command", "deleteBackward"),
    PadButton("left", "←", "Move left", "edit", "command", "moveToPreviousChar"),
    PadButton("right", "→", "Move right", "edit", "command", "moveToNextChar"),
)
"""The palette in reading order: structure, symbols, interval brackets, editing. The buttons and
sizes of Recall Drill v0.6, plus a comma. The brackets read ``[ ( ) ]`` (Recall Drill has them
``[ ) ( ]``, with no reason recorded for it; changed here 2026-10-18)."""


def pad_html() -> str:
    """The palette: one ``<button>`` per :data:`PALETTE` entry, grouped."""
    parts: list[str] = []
    for group in PAD_GROUPS:
        buttons = "".join(
            f'<button type="button" id="mp-pad-{b.key}" class="mp-padbtn" data-key="{b.key}" '
            f'data-op="{b.op}" data-arg="{escape(b.arg, quote=True)}" '
            f'title="{escape(b.tip, quote=True)}" aria-label="{escape(b.tip, quote=True)}" '
            f'tabindex="-1">{b.glyph}</button>'
            for b in PALETTE
            if b.group == group
        )
        parts.append(f'<div class="mp-padgroup" data-group="{group}">{buttons}</div>')
    return (
        '<div class="mp-padwrap"><div id="mp-pad" class="mp-pad" role="group" '
        f'aria-label="Math palette">{"".join(parts)}</div></div>'
    )


def math_field(field_id: str, *, label: str = "Your answer", cls: str = "") -> str:
    """A MathLive field the page wires up (its content comes from ``PageView.fields``)."""
    extra = f" {cls}" if cls else ""
    return (
        f'<div class="mp-fieldwrap{extra}" data-fieldwrap="{escape(field_id, quote=True)}">'
        f'<math-field class="mp-mf" data-id="{escape(field_id, quote=True)}" '
        f'aria-label="{escape(label, quote=True)}"></math-field></div>'
    )
