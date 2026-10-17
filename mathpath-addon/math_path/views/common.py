"""Small HTML pieces shared by the screens (pure)."""

from __future__ import annotations

from html import escape

from ..theme import Role


def esc(text: str) -> str:
    return escape(text, quote=True)


def button(
    label: str,
    act: str,
    arg: str = "",
    *,
    role: Role = "secondary",
    disabled: bool = False,
    tip: str = "",
    small: bool = False,
    key: str = "",
) -> str:
    """A ``.mp-btn``. ``role``: primary (accent), secondary (grey) or ghost (plain)."""
    cls = "mp-btn" + ("" if role == "secondary" else f" {role}") + (" small" if small else "")
    attrs = f' data-act="{esc(act)}"'
    if arg != "":
        attrs += f' data-arg="{esc(arg)}"'
    if tip:
        attrs += f' title="{esc(tip)}"'
    if disabled:
        attrs += ' disabled aria-disabled="true"'
    ident = f' id="{esc(key)}"' if key else ""
    return f'<button type="button"{ident} class="{cls}"{attrs}>{label}</button>'


def chip(text: str, kind: str = "plain") -> str:
    """A small pill. ``kind``: plain, accent, ok, warn, bad or muted."""
    cls = "mp-chip" + ("" if kind == "plain" else f" {kind}")
    return f'<span class="{cls}">{esc(text)}</span>'


def note(html: str, kind: str = "info") -> str:
    """A rounded note. ``html`` is already HTML. ``kind``: info, warn, bad or ok."""
    cls = "mp-note" + ("" if kind == "info" else f" {kind}")
    return f'<div class="{cls}">{html}</div>'


def bar(inner: str, *, foot: bool = False) -> str:
    return f'<div class="mp-bar{" mp-foot" if foot else ""}">{inner}</div>'


def card(inner: str, label: str = "") -> str:
    head = f'<div class="mp-label">{esc(label)}</div>' if label else ""
    return f'<div class="mp-card">{head}{inner}</div>'


def plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"
