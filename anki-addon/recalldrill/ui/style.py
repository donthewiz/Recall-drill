"""One look for Recall Drill's own windows (v0.5; docs/DECISIONS.md, "v0.5 window redesign").

The colours are the exam tracker's: :data:`TOKENS` is the only place they live, dark and light.
:func:`apply` puts the stylesheet on **one window** (never on the application, never on Anki's
palette), so Anki's own windows and dialogs are untouched. Every rule is scoped to the window's
content (``#rdRoot``, a plain container the window builds with :func:`install`) or to a widget
that carries one of this module's dynamic properties, so a message box a window opens, which
Qt parents to it, keeps Anki's look.

Roles and kinds are Qt dynamic properties the stylesheet selects on:

- ``rdRole`` on a button: ``primary`` (accent), ``secondary`` (grey, the default) or ``ghost``.
- ``rdKind`` on a check box: ``chip`` (a pill) or ``switch`` (a track and a knob). Both stay
  real, keyboard-focusable check boxes with their own text and signals.
- ``rdText`` on a label: ``title``, ``strong``, ``muted``, ``section``, ``value``.
- ``rdNote`` on a label: ``warn`` or ``info`` (a rounded note).
- ``rdPill`` on a label: the tracker's status pill (``green``, ``amber``, ``red``, ``exam``).
- ``rdChip`` on a label: a small chip (``accent``, ``plain``, ``warn``).
- ``rdCard``, ``rdTile``, ``rdRow``, ``rdBar`` on a frame: a section card, a tile, a row card,
  a header or footer strip.

The window follows Anki's night mode and is restyled when Anki's theme changes
(``gui_hooks.theme_did_change``).
"""

from __future__ import annotations

import weakref
from collections.abc import Callable
from pathlib import Path
from typing import Any, Literal

from aqt.qt import QFont, QFrame, QLabel, QPushButton, Qt, QVBoxLayout, QWidget

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
PILL_COLOR = {"green": "ok", "amber": "warn", "red": "bad", "exam": "muted"}
"""The tracker's status -> the token its pill uses (the exam day is neutral)."""

ROOT_NAME = "rdRoot"
IMAGE_DIR = Path(__file__).resolve().parents[2] / "web"
"""Switch and arrow images (``rd_*.svg``), shipped with the tracker's web files."""


def theme_name(night: bool) -> Theme:
    return "dark" if night else "light"


def is_night() -> bool:
    """Anki's night mode (tests replace this)."""
    try:
        from aqt.theme import theme_manager

        return bool(theme_manager.night_mode)
    except Exception:  # noqa: BLE001 (no theme manager yet: light)
        return False


def _rgb(color: str) -> tuple[int, int, int]:
    return int(color[1:3], 16), int(color[3:5], 16), int(color[5:7], 16)


def mix(top: str, base: str, share: float) -> str:
    """``top`` over ``base`` at ``share`` (0-1), as a solid colour."""
    (r1, g1, b1), (r2, g2, b2) = _rgb(top), _rgb(base)
    r, g, b = (round(a * share + c * (1 - share)) for a, c in ((r1, r2), (g1, g2), (b1, b2)))
    return f"#{r:02x}{g:02x}{b:02x}"


def derived(theme: Theme) -> dict[str, str]:
    """Tokens plus the tints made from them: a warning is its colour at 12 % behind and 35 %
    on the border, an info note the accent the same way."""
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


def _image(name: str, theme: Theme) -> str:
    return f'url("{(IMAGE_DIR / f"rd_{name}_{theme}.svg").as_posix()}")'


def stylesheet(night: bool) -> str:
    """The window's stylesheet for dark (``night``) or light."""
    theme = theme_name(night)
    t = derived(theme)
    root = f"#{ROOT_NAME}"
    inputs = ", ".join(
        f"{root} {c}" for c in ("QLineEdit", "QComboBox", "QSpinBox", "QDoubleSpinBox", "QDateEdit")
    )
    inputs_focus = ", ".join(
        f"{root} {c}:focus"
        for c in ("QLineEdit", "QComboBox", "QSpinBox", "QDoubleSpinBox", "QDateEdit")
    )
    spin = ", ".join(f"{root} {c}" for c in ("QSpinBox", "QDoubleSpinBox"))
    pill_rules = "\n".join(
        f'{root} QLabel[rdPill="{k}"] {{ color: {t[v]}; border: 1px solid {t[v]}; '
        f"border-radius: 11px; background: {mix(t[v], t['card'], 0.12)}; }}"
        for k, v in PILL_COLOR.items()
    )
    return f"""
QDialog[rdWindow="true"], {root} {{ background: {t["window"]}; }}
{root} QLabel, {root} QCheckBox {{ color: {t["text"]}; background: transparent; font-size: 13px; }}
{root} QLabel[rdText="strong"] {{ color: {t["strong"]}; font-weight: 600; }}
{root} QLabel[rdText="title"] {{ color: {t["strong"]}; font-size: 20px; font-weight: 700; }}
{root} QLabel[rdText="heading"] {{ color: {t["strong"]}; font-size: 15px; font-weight: 700; }}
{root} QLabel[rdText="value"] {{ color: {t["strong"]}; font-size: 20px; font-weight: 700; }}
{root} QLabel[rdText="muted"] {{ color: {t["muted"]}; font-size: 12px; }}
{root} QLabel[rdText="section"] {{ color: {t["muted"]}; font-size: 12px; font-weight: 600; }}
{root} QLabel[rdText="ok"] {{ color: {t["ok"]}; font-weight: 600; }}

{root} QFrame[rdCard="true"] {{
  background: {t["card"]}; border: 1px solid {t["border"]}; border-radius: 10px; }}
{root} QFrame[rdTile="true"] {{
  background: {t["card"]}; border: 1px solid {t["border"]}; border-radius: 10px; }}
{root} QFrame[rdRow="true"] {{
  background: {t["card"]}; border: 1px solid {t["border"]}; border-radius: 10px; }}
{root} QFrame[rdRow="true"]:hover {{ border-color: {t["control_border"]}; }}
{root} QFrame[rdRow="next"] {{
  background: {t["accent_bg"]}; border: 1px solid {t["accent"]}; border-radius: 10px; }}
{root} QFrame[rdBanner="true"] {{
  background: {t["info_bg"]}; border: 1px solid {t["info_border"]}; border-radius: 10px; }}
{root} QFrame[rdBar="footer"] {{
  background: {t["footer"]}; border: none; border-top: 1px solid {t["border"]}; }}
{root} QFrame[rdBar="header"] {{
  background: {t["footer"]}; border: none; border-bottom: 1px solid {t["border"]}; }}

{root} QLabel[rdNote="warn"] {{
  color: {t["warn"]}; background: {t["warn_bg"]}; border: 1px solid {t["warn_border"]};
  border-radius: 8px; padding: 7px 10px; }}
{root} QLabel[rdNote="info"] {{
  color: {t["text"]}; background: {t["info_bg"]}; border: 1px solid {t["info_border"]};
  border-radius: 8px; padding: 7px 10px; }}
{root} QLabel[rdPill] {{
  border-radius: 11px; padding: 3px 10px; font-size: 12px; font-weight: 600; }}
{pill_rules}
{root} QLabel[rdChip] {{
  border-radius: 10px; padding: 3px 10px; font-size: 12px; font-weight: 600; }}
{root} QLabel[rdChip="accent"] {{
  color: {t["accent"]}; background: {t["accent_bg"]};
  border: 1px solid {t["info_border"]}; border-radius: 10px; }}
{root} QLabel[rdChip="plain"] {{
  color: {t["text"]}; background: {t["card"]};
  border: 1px solid {t["border"]}; border-radius: 10px; }}
{root} QLabel[rdChip="warn"] {{
  color: {t["warn"]}; background: {t["warn_bg"]};
  border: 1px solid {t["warn_border"]}; border-radius: 10px; }}
{root} QLabel[rdChip="ok"] {{
  color: {t["ok"]}; background: {t["ok_bg"]};
  border: 1px solid {t["ok"]}; border-radius: 10px; }}

{root} QPushButton {{
  min-height: 30px; padding: 0 14px; border-radius: 7px; font-size: 13px;
  color: {t["text"]}; background: {t["secondary_bg"]}; border: 1px solid {t["control_border"]}; }}
{root} QPushButton:hover {{ background: {t["secondary_hover"]}; }}
{root} QPushButton:focus {{ border-color: {t["accent"]}; }}
{root} QPushButton:disabled {{ color: {t["muted"]}; background: {t["card"]};
  border-color: {t["border"]}; }}
{root} QPushButton[rdRole="primary"] {{
  color: {t["on_accent"]}; background: {t["accent"]}; border: 1px solid {t["accent"]};
  font-weight: 600; }}
{root} QPushButton[rdRole="primary"]:hover {{ background: {t["accent_hover"]}; }}
{root} QPushButton[rdRole="primary"]:focus {{ border-color: {t["strong"]}; }}
{root} QPushButton[rdRole="primary"]:disabled {{
  color: {t["muted"]}; background: {t["secondary_bg"]}; border-color: {t["border"]}; }}
{root} QPushButton[rdRole="secondary"] {{
  color: {t["text"]}; background: {t["secondary_bg"]}; border: 1px solid {t["control_border"]}; }}
{root} QPushButton[rdRole="ghost"] {{
  color: {t["text"]}; background: transparent; border: 1px solid transparent; }}
{root} QPushButton[rdRole="ghost"]:hover {{ background: {t["ghost_hover"]}; }}
{root} QPushButton[rdRole="ghost"]:focus {{ border-color: {t["accent"]}; }}
{root} QPushButton[rdRole="ghost"]:disabled {{ color: {t["muted"]}; background: transparent; }}

{inputs} {{
  min-height: 30px; padding: 0 8px; border-radius: 7px; color: {t["strong"]};
  background: {t["input"]}; border: 1px solid {t["control_border"]};
  selection-background-color: {t["accent"]}; selection-color: {t["on_accent"]}; }}
{inputs_focus} {{ border-color: {t["accent"]}; }}
{root} QLineEdit:disabled, {root} QComboBox:disabled, {root} QSpinBox:disabled,
{root} QDateEdit:disabled {{ color: {t["muted"]}; background: {t["card"]};
  border-color: {t["border"]}; }}
{root} QLineEdit[rdInput="answer"] {{
  font-size: 16px; min-height: 38px; border-radius: 9px; padding: 0 12px; }}
{root} QLineEdit[rdInput="answer"]:focus {{ border: 2px solid {t["accent"]}; }}
{root} QComboBox::drop-down, {root} QDateEdit::drop-down {{
  border: none; width: 24px; subcontrol-origin: padding; subcontrol-position: center right; }}
{root} QComboBox::down-arrow, {root} QDateEdit::down-arrow {{
  image: {_image("chevron_down", theme)}; width: 12px; height: 12px; }}
{root} QComboBox QAbstractItemView {{
  color: {t["text"]}; background: {t["input"]}; border: 1px solid {t["control_border"]};
  selection-background-color: {t["accent_bg"]}; selection-color: {t["strong"]}; outline: none; }}
{spin} {{ padding-right: 22px; }}
{root} QSpinBox::up-button, {root} QDoubleSpinBox::up-button {{
  subcontrol-origin: border; subcontrol-position: top right; width: 20px; border: none; }}
{root} QSpinBox::down-button, {root} QDoubleSpinBox::down-button {{
  subcontrol-origin: border; subcontrol-position: bottom right; width: 20px; border: none; }}
{root} QSpinBox::up-arrow, {root} QDoubleSpinBox::up-arrow {{
  image: {_image("chevron_up", theme)}; width: 10px; height: 10px; }}
{root} QSpinBox::down-arrow, {root} QDoubleSpinBox::down-arrow {{
  image: {_image("chevron_down", theme)}; width: 10px; height: 10px; }}

{root} QCheckBox {{ spacing: 8px; }}
{root} QCheckBox:disabled {{ color: {t["muted"]}; }}
{root} QCheckBox[rdKind="chip"] {{
  color: {t["text"]}; border: 1px solid {t["control_border"]}; border-radius: 14px;
  padding: 4px 12px; background: transparent; spacing: 0px; }}
{root} QCheckBox[rdKind="chip"]::indicator {{ width: 0px; height: 0px; }}
{root} QCheckBox[rdKind="chip"]:hover {{ background: {t["ghost_hover"]}; }}
{root} QCheckBox[rdKind="chip"]:checked {{
  color: {t["accent"]}; background: {t["accent_bg"]}; border-color: {t["accent"]};
  font-weight: 600; }}
{root} QCheckBox[rdKind="chip"]:focus {{ border: 2px solid {t["accent"]}; padding: 3px 11px; }}
{root} QCheckBox[rdKind="chip"]:disabled {{
  color: {t["muted"]}; border-color: {t["border"]}; background: transparent; }}
{root} QCheckBox[rdKind="switch"] {{
  border: 1px solid transparent; border-radius: 6px; padding: 2px 4px; spacing: 10px; }}
{root} QCheckBox[rdKind="switch"]:focus {{ border-color: {t["accent"]}; }}
{root} QCheckBox[rdKind="switch"]::indicator {{ width: 34px; height: 20px; }}
{root} QCheckBox[rdKind="switch"]::indicator:unchecked {{ image: {_image("switch_off", theme)}; }}
{root} QCheckBox[rdKind="switch"]::indicator:checked {{ image: {_image("switch_on", theme)}; }}

{root} QTableWidget, {root} QTableView {{
  background: transparent; color: {t["text"]}; border: none; gridline-color: transparent;
  selection-background-color: {t["accent_bg"]}; selection-color: {t["strong"]}; outline: none; }}
{root} QTableWidget::item {{ padding: 6px 8px; border-bottom: 1px solid {t["border"]}; }}
{root} QTableWidget::item:selected {{ background: {t["accent_bg"]}; color: {t["strong"]}; }}
{root} QHeaderView {{ background: transparent; }}
{root} QHeaderView::section {{
  background: transparent; color: {t["muted"]}; border: none;
  border-bottom: 1px solid {t["border"]}; padding: 6px 8px; font-size: 12px; font-weight: 600; }}
{root} QTextBrowser {{
  background: {t["card"]}; color: {t["text"]}; border: 1px solid {t["border"]};
  border-radius: 10px; padding: 6px; font-size: 13px; }}

{root} QProgressBar {{
  background: {t["border"]}; border: none; border-radius: 3px; max-height: 6px; min-height: 6px; }}
{root} QProgressBar::chunk {{ background: {t["accent"]}; border-radius: 3px; }}
{root} QProgressBar[rdBar="done"]::chunk {{ background: {t["ok"]}; }}

{root} QScrollArea {{ background: transparent; border: none; }}
{root} QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
{root} QScrollBar::handle:vertical {{
  background: {t["control_border"]}; border-radius: 5px; min-height: 28px; }}
{root} QScrollBar::add-line:vertical, {root} QScrollBar::sub-line:vertical {{ height: 0; }}
{root} QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
{root} QScrollBar::handle:horizontal {{
  background: {t["control_border"]}; border-radius: 5px; min-width: 28px; }}
{root} QScrollBar::add-line:horizontal, {root} QScrollBar::sub-line:horizontal {{ width: 0; }}
"""


def report_css(night: bool) -> str:
    """The tuning report's tables (Qt rich text takes this as the document's default sheet)."""
    t = derived(theme_name(night))
    return (
        f"body {{ color: {t['text']}; font-size: 13px; }}"
        f"h3, h4 {{ color: {t['strong']}; }}"
        f"th {{ color: {t['muted']}; font-size: 12px; font-weight: 600; text-align: left;"
        f" font-variant: small-caps; padding: 6px 8px; }}"
        f"td {{ color: {t['text']}; padding: 6px 8px; }}"
        f"small {{ color: {t['muted']}; }}"
        f"i {{ color: {t['muted']}; }}"
    )


# -- windows ---------------------------------------------------------------------------

_windows: weakref.WeakKeyDictionary[QWidget, Callable[[], None] | None] = (
    weakref.WeakKeyDictionary()
)
_hooked = False


def apply(window: QWidget, on_restyle: Callable[[], None] | None = None) -> None:
    """Styles ``window`` (and only it) for Anki's current theme, and again whenever Anki's
    theme changes while it is open. ``on_restyle`` runs after a change (for rich text the
    window built with colours in it)."""
    global _hooked
    window.setProperty("rdWindow", True)
    window.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    window.setStyleSheet(stylesheet(is_night()))
    _windows[window] = on_restyle
    if not _hooked:
        _hooked = True
        from aqt import gui_hooks

        gui_hooks.theme_did_change.append(restyle_all)


def restyle_all() -> None:
    """Anki's theme changed: every open window of ours gets the other sheet."""
    sheet = stylesheet(is_night())
    for window, again in list(_windows.items()):
        try:
            window.setStyleSheet(sheet)
            if again is not None:
                again()
        except RuntimeError:  # the C++ window is gone
            continue


def install(window: QWidget) -> QWidget:
    """The window's content container: the window gets a zero-margin layout holding one
    ``#rdRoot`` widget, and the caller lays its content out on that. Styles the window."""
    outer = QVBoxLayout(window)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(0)
    root = QWidget()
    root.setObjectName(ROOT_NAME)
    root.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
    outer.addWidget(root)
    apply(window)
    return root


def repolish(widget: QWidget) -> None:
    """After a dynamic property changed on a shown widget."""
    style = widget.style()
    if style is not None:
        style.unpolish(widget)
        style.polish(widget)
    widget.update()


def set_prop(widget: QWidget, name: str, value: Any) -> None:
    if widget.property(name) != value:
        widget.setProperty(name, value)
        repolish(widget)


# -- parts -----------------------------------------------------------------------------


def button(text: str, role: Role = "secondary") -> QPushButton:
    b = QPushButton(text)
    set_role(b, role)
    return b


def set_role(b: QPushButton, role: Role) -> QPushButton:
    b.setProperty("rdRole", role)
    return b


def role_of(b: QPushButton) -> str:
    return str(b.property("rdRole") or "secondary")


def text_label(text: str = "", kind: str = "", wrap: bool = True) -> QLabel:
    """A label of one of the ``rdText`` kinds ("" is the plain text colour)."""
    lab = QLabel(text)
    if kind:
        lab.setProperty("rdText", kind)
    lab.setWordWrap(wrap)
    return lab


def section_label(title: str) -> QLabel:
    """A section's label above its card: muted, upper case, semibold, letter-spaced."""
    lab = QLabel(title.upper())
    lab.setProperty("rdText", "section")
    font = lab.font()
    font.setWeight(QFont.Weight.DemiBold)
    font.setLetterSpacing(QFont.SpacingType.PercentageSpacing, 108)
    lab.setFont(font)
    return lab


def note(text: str = "", kind: Literal["warn", "info"] = "info") -> QLabel:
    """A rounded note: warning (amber tint) or info (accent tint)."""
    lab = QLabel(text)
    lab.setWordWrap(True)
    lab.setProperty("rdNote", kind)
    return lab


def mark_note(lab: QLabel, kind: Literal["warn", "info"]) -> QLabel:
    lab.setProperty("rdNote", kind)
    return lab


def chip(box: Any) -> Any:
    """A check box that renders as a pill (same widget, same signals, same text)."""
    box.setProperty("rdKind", "chip")
    box.setCursor(_pointing_hand())
    return box


def switch(box: Any) -> Any:
    """A check box that renders as a 34 x 20 track-and-knob switch."""
    box.setProperty("rdKind", "switch")
    box.setCursor(_pointing_hand())
    return box


def _pointing_hand() -> Any:
    from aqt.qt import QCursor

    return QCursor(Qt.CursorShape.PointingHandCursor)


def frame(prop: str, value: Any = True) -> QFrame:
    f = QFrame()
    f.setProperty(prop, value)
    return f


def section(title: str) -> tuple[QWidget, QVBoxLayout]:
    """A section: its label above a rounded card. Returns the whole thing (add it to a
    layout, show or hide it) and the layout inside the card (14 px padding)."""
    box = QWidget()
    outer = QVBoxLayout(box)
    outer.setContentsMargins(0, 0, 0, 0)
    outer.setSpacing(6)
    outer.addWidget(section_label(title))
    card = frame("rdCard")
    inner = QVBoxLayout(card)
    inner.setContentsMargins(15, 14, 15, 14)
    inner.setSpacing(9)
    outer.addWidget(card)
    return box, inner


def card_frame() -> tuple[QFrame, QVBoxLayout]:
    """A bare rounded card (no label)."""
    card = frame("rdCard")
    inner = QVBoxLayout(card)
    inner.setContentsMargins(15, 14, 15, 14)
    inner.setSpacing(8)
    return card, inner


def tile(label: str, value: str = "") -> tuple[QFrame, QLabel]:
    """A small tile: a big number over a muted caption. Returns it and the value label."""
    f = frame("rdTile")
    lay = QVBoxLayout(f)
    lay.setContentsMargins(14, 10, 14, 10)
    lay.setSpacing(0)
    v = text_label(value, "value", wrap=False)
    lay.addWidget(v)
    lay.addWidget(text_label(label, "muted", wrap=False))
    return f, v


def status_pill(status: str, text: str) -> QLabel:
    """The tracker's pill: icon plus word, in the status colour (never colour alone)."""
    lab = QLabel(text)
    lab.setProperty("rdPill", status if status in PILL_COLOR else "exam")
    return lab


def chip_label(text: str, kind: str = "plain") -> QLabel:
    lab = QLabel(text)
    lab.setProperty("rdChip", kind)
    return lab
