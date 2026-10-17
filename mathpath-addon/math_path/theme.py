"""One look for Math Path's windows (pure): Recall Drill's v0.5 colours and button roles.

:data:`TOKENS` is the only place the colours live, dark (Atom One) and light. The pages get them
as CSS variables (``css_vars``), so ``web/mp_page.css`` has no colour of its own. The window follows
Anki's night mode. Copied from Recall Drill's ``ui/style.py`` (the two add-ons share nothing at
run time).
"""

from __future__ import annotations

from typing import Literal

Theme = Literal["dark", "light"]
Role = Literal["primary", "secondary", "ghost"]

TOKENS: dict[Theme, dict[str, str]] = {
    "dark": {
        "window": "#282c34",
        "card": "#2c313a",
        "footer": "#262a31",
        "input": "#21252b",
        "border": "#3a404b",
        "control_border": "#454c59",
        "text": "#abb2bf",
        "strong": "#dcdfe4",
        "muted": "#8b929e",
        "accent": "#61afef",
        "on_accent": "#1b1f27",
        "ok": "#56d364",
        "warn": "#e3b341",
        "bad": "#ff7b72",
    },
    "light": {
        "window": "#f6f7f9",
        "card": "#ffffff",
        "footer": "#eef0f3",
        "input": "#ffffff",
        "border": "#d9dce1",
        "control_border": "#c4c9d1",
        "text": "#2b3036",
        "strong": "#14171a",
        "muted": "#5c6570",
        "accent": "#1f6feb",
        "on_accent": "#ffffff",
        "ok": "#1a7f37",
        "warn": "#9a6700",
        "bad": "#cf222e",
    },
}

ROLES: tuple[Role, ...] = ("primary", "secondary", "ghost")


def theme_name(night: bool) -> Theme:
    return "dark" if night else "light"


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def mix(top: str, base: str, share: float) -> str:
    """``top`` over ``base`` at ``share`` (0-1), as a solid colour."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(top), _rgb(base)
    r, g, b = (round(a * share + c * (1 - share)) for a, c in ((r1, r2), (g1, g2), (b1, b2)))
    return f"#{r:02x}{g:02x}{b:02x}"


def derived(theme: Theme) -> dict[str, str]:
    """Tokens plus the tints made from them: a warning is its colour at 12 % behind and 35 % on
    the border, an info note the accent the same way."""
    t = dict(TOKENS[theme])
    t["warn_bg"] = mix(t["warn"], t["card"], 0.12)
    t["warn_border"] = mix(t["warn"], t["card"], 0.35)
    t["info_bg"] = mix(t["accent"], t["card"], 0.12)
    t["info_border"] = mix(t["accent"], t["card"], 0.35)
    t["accent_bg"] = mix(t["accent"], t["card"], 0.16)
    t["accent_hover"] = mix(t["accent"], t["on_accent"], 0.88)
    t["secondary_bg"] = mix(t["text"], t["card"], 0.08)
    t["secondary_hover"] = mix(t["text"], t["card"], 0.14)
    t["ghost_hover"] = mix(t["text"], t["window"], 0.10)
    t["ok_bg"] = mix(t["ok"], t["card"], 0.14)
    t["bad_bg"] = mix(t["bad"], t["card"], 0.14)
    return t


def _vars(t: dict[str, str]) -> str:
    return "".join(f"--mp-{k.replace('_', '-')}:{v};" for k, v in t.items())


def css_vars() -> str:
    """The stylesheet that defines every colour: light on ``:root``, dark under ``.night-mode``."""
    return f":root {{ {_vars(derived('light'))} }}\n.night-mode {{ {_vars(derived('dark'))} }}\n"
