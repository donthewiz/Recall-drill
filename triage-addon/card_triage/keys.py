"""Which keys the set-aside key may be (pure).

A reviewer shortcut is a Qt ``QShortcut`` on Anki's main window. If two shortcuts there have the
same key, Qt treats it as ambiguous and neither fires. So the key must differ from the reviewer's
own keys (``Reviewer._shortcutKeys``) **and** from the main window's global keys
(``AnkiQt.setupKeys``: d, s, a, b, t, Shift+t, y, Ctrl+:) **and** from the main window's menu
shortcuts (``_aqt/forms/main_qt6.py``: F = Create Filtered Deck, / = Study Deck, Ctrl+Z…).
``tests/test_keys.py`` reads the installed ``aqt`` source and fails if any of those lists has a
key this module doesn't know.
"""

from __future__ import annotations

from dataclasses import dataclass

MODIFIERS = ("ctrl", "alt", "shift", "meta")
NAMED_KEYS = frozenset(
    {
        "space", "return", "enter", "tab", "backspace", "delete", "esc", "escape", "home", "end",
        "insert", "pgup", "pgdown", "up", "down", "left", "right",
        *(f"f{n}" for n in range(1, 13)),
    }
)  # fmt: skip

_REVIEWER = (
    "e space return enter m r f5 * = - ! @ ctrl+alt+n ctrl+alt+e ctrl+backspace ctrl+delete "
    "ctrl+shift+d v shift+v o i ctrl+alt+i 1 2 3 4 u 5 6 7 shift+a "
    "ㄷ ㅡ ㄱ ctrl+alt+ㅜ ㅍ shift+ㅍ ㅐ ㅑ ctrl+alt+ㅑ ㅕ "
    "ctrl+1 ctrl+2 ctrl+3 ctrl+4 ctrl+5 ctrl+6 ctrl+7"
)
_MAIN_WINDOW = "ctrl+: d s a b t shift+t y f11"
_MENUS = (
    "ctrl+q ctrl+p ctrl+z f1 ctrl+shift+p ctrl+e ctrl+shift+i / f ctrl+shift+n ctrl+shift+a "
    "ctrl+shift+z ctrl+0"
)

RESERVED: dict[str, str] = {
    **{k: "the reviewer" for k in _REVIEWER.split()},
    **{k: "Anki's main window" for k in _MAIN_WINDOW.split()},
    **{k: "Anki's menus" for k in _MENUS.split()},
}
"""Normalized key → where Anki already uses it."""


def normalize_key(text: str) -> str | None:
    """A key as typed (``X``, ``Ctrl+Shift+d``) → its canonical form (``x``, ``ctrl+shift+d``);
    ``None`` if it isn't one key with optional modifiers."""
    text = text.strip()
    if not text:
        return None
    if text == "+":
        return "+"
    parts = [p.strip() for p in text.split("+")]
    key = parts[-1].lower()
    mods = [p.lower() for p in parts[:-1]]
    if not key or any(m not in MODIFIERS for m in mods) or len(set(mods)) != len(mods):
        return None
    if len(key) != 1 and key not in NAMED_KEYS:
        return None
    if key.isspace():
        return None
    ordered = [m for m in MODIFIERS if m in mods]
    return "+".join([*ordered, key])


@dataclass(frozen=True)
class KeyCheck:
    ok: bool
    key: str
    """The key to save when ``ok`` (as typed, trimmed)."""
    message: str = ""


def check_key(text: str, extra_reserved: dict[str, str] | None = None) -> KeyCheck:
    """Whether ``text`` may be the set-aside key. ``extra_reserved`` adds keys known only at run
    time (e.g. the reviewer's live keys, which include answer keys the user rebound)."""
    norm = normalize_key(text)
    shown = text.strip()
    if norm is None:
        return KeyCheck(
            False,
            shown,
            "That isn't a single key. Type one key such as X, or a combination such as Ctrl+X.",
        )
    taken = {**RESERVED, **(extra_reserved or {})}
    if norm in taken:
        return KeyCheck(
            False,
            shown,
            f"{shown} is already used by Anki in {taken[norm]}. Pick another key.",
        )
    return KeyCheck(True, shown)
