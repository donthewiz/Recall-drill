"""The math answer field and its palette: the page's HTML, CSS and the bridge (pure).

A math card's answer row is a second web view (``web/rd_math_input.js`` plus the vendored
MathLive in ``web/mathlive/``) holding one MathLive field and an always-visible palette of
click targets, so no symbol needs a keyboard shortcut; letters and digits come from the
physical keyboard. The page sends the field's LaTeX to Python on every change
(:data:`VALUE_PREFIX`) and the drill's keys (Enter, Ctrl+Enter, Esc, Ctrl+I/E/R) as the same
bridge commands the card page uses. ``math_answer.keyboard_from_palette`` reads the LaTeX.

The colours come from ``ui/style.py``'s tokens (passed in, so this module needs no Qt).
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from html import escape

VALUE_PREFIX = "rd:math:"
"""Bridge command carrying the field's LaTeX: ``rd:math:\\frac{1}{2}``."""

GRADED_NOTE = "Graded by form; any order"
"""The note under the palette (the mockup's "Graded on meaning" says something else)."""

MIN_TARGET_PX = 44
"""Every palette button is at least this big in both directions."""


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


GROUPS = ("build", "symbols", "brackets", "edit")

PALETTE: tuple[PadButton, ...] = (
    PadButton(
        "frac",
        '<span class="rd-g-frac"><span>a</span><span>b</span></span>',
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
    PadButton("rparen", ")", "Right parenthesis (open end)", "brackets", "insert", ")"),
    PadButton("lparen", "(", "Left parenthesis (open end)", "brackets", "insert", "("),
    PadButton("rbracket", "]", "Right square bracket (closed end)", "brackets", "insert", "]"),
    PadButton("backspace", "⌫", "Backspace", "edit", "command", "deleteBackward"),
    PadButton("left", "←", "Move left", "edit", "command", "moveToPreviousChar"),
    PadButton("right", "→", "Move right", "edit", "command", "moveToNextChar"),
)
"""The palette in reading order: structure, symbols, interval brackets, editing."""

SCRIPTS = ("mathlive/mathlive.min.js", "rd_math_input.js")
"""Under ``web/``, in load order."""


def script_urls(folder: str) -> list[str]:
    """The scripts' paths for ``stdHtml(js=...)`` (served by Anki's add-on web exports)."""
    return [f"/_addons/{folder}/web/{name}" for name in SCRIPTS]


def web_pattern() -> str:
    """The ``setWebExports`` regex for the files above (the fonts MathLive draws with included)."""
    return r"mathlive/(mathlive\.min\.js|fonts/KaTeX_[A-Za-z0-9_-]+\.woff2)|rd_math_input\.js"


def _vars(t: Mapping[str, str]) -> str:
    return (
        f"--rd-window:{t['window']};--rd-card:{t['card']};--rd-input:{t['input']};"
        f"--rd-border:{t['border']};--rd-control:{t['control_border']};--rd-text:{t['text']};"
        f"--rd-strong:{t['strong']};--rd-muted:{t['muted']};--rd-accent:{t['accent']};"
        f"--rd-accent-bg:{t['accent_bg']};--rd-secondary:{t['secondary_bg']};"
        f"--rd-secondary-hover:{t['secondary_hover']};"
    )


def page_css(light: Mapping[str, str], dark: Mapping[str, str]) -> str:
    """The page's stylesheet: ``light`` tokens, and ``dark`` under ``.night-mode``."""
    return (
        f":root {{ {_vars(light)} }}\n.night-mode {{ {_vars(dark)} }}\n"
        + f"""
html, body {{ margin: 0; padding: 0; background: var(--rd-window); color: var(--rd-text);
  font-family: -apple-system, "Segoe UI", Roboto, sans-serif; overflow-x: hidden; }}
body {{ padding: 2px 0 4px; }}
#rd-math {{ display: flex; flex-direction: column; gap: 12px; }}
#rd-math-field {{ background: var(--rd-input); border: 2px solid var(--rd-control);
  border-radius: 12px; padding: 6px 14px; min-height: 64px; display: flex; align-items: center; }}
#rd-math-field:focus-within {{ border-color: var(--rd-accent); }}
math-field {{ width: 100%; font-size: 34px; background: transparent; color: var(--rd-strong);
  border: none; outline: none; min-height: 52px; --hue: 210;
  --caret-color: var(--rd-accent); --selection-background-color: var(--rd-accent-bg);
  --contains-highlight-background-color: var(--rd-accent-bg);
  --placeholder-color: var(--rd-muted); --text-font-family: inherit; }}
math-field::part(virtual-keyboard-toggle), math-field::part(menu-toggle) {{ display: none; }}
#rd-pad {{ display: flex; flex-wrap: wrap; gap: 8px 22px; align-items: center; }}
.rd-group {{ display: flex; flex-wrap: wrap; gap: 8px; }}
#rd-pad button {{ min-width: {MIN_TARGET_PX + 12}px; min-height: {MIN_TARGET_PX + 4}px;
  padding: 0 10px; border-radius: 10px; border: 1px solid var(--rd-control);
  background: var(--rd-secondary); color: var(--rd-strong); font-size: 22px; line-height: 1;
  font-family: "Cambria Math", "STIX Two Math", "Segoe UI Symbol", serif; cursor: pointer;
  display: inline-flex; align-items: center; justify-content: center; }}
#rd-pad button:hover {{ background: var(--rd-secondary-hover); }}
#rd-pad button:active {{ background: var(--rd-accent-bg); border-color: var(--rd-accent); }}
#rd-pad button:disabled {{ opacity: .45; cursor: default; }}
#rd-pad button sup {{ font-size: 13px; margin-left: 1px; }}
.rd-g-frac {{ display: inline-flex; flex-direction: column; align-items: center;
  font-size: 15px; line-height: 1.05; font-style: italic; }}
.rd-g-frac span:first-child {{ border-bottom: 1.5px solid currentColor; padding: 0 5px; }}
#rd-math-note {{ font-size: 12px; color: var(--rd-muted); }}
"""
    )


def pad_html() -> str:
    """The palette: one ``<button>`` per :data:`PALETTE` entry, grouped."""
    parts: list[str] = []
    for group in GROUPS:
        buttons = "".join(
            f'<button type="button" id="rd-pad-{b.key}" data-key="{b.key}" data-op="{b.op}" '
            f'data-arg="{escape(b.arg, quote=True)}" title="{escape(b.tip, quote=True)}" '
            f'aria-label="{escape(b.tip, quote=True)}" tabindex="-1">{b.glyph}</button>'
            for b in PALETTE
            if b.group == group
        )
        parts.append(f'<div class="rd-group" data-group="{group}">{buttons}</div>')
    return "".join(parts)


def shell_body(light: Mapping[str, str], dark: Mapping[str, str]) -> str:
    """The whole page body: styles, the field, the palette and the note."""
    return (
        f"<style>{page_css(light, dark)}</style>"
        '<div id="rd-math">'
        '<div id="rd-math-field">'
        '<math-field id="rd-mf" aria-label="Your answer"></math-field></div>'
        f'<div id="rd-pad" role="group" aria-label="Math palette">{pad_html()}</div>'
        f'<div id="rd-math-note">{escape(GRADED_NOTE)}</div>'
        "</div>"
    )


def configure_call(read_only: bool, placeholder: str, night: bool) -> str:
    """JS for the page: lock or unlock the field, set its placeholder and the theme."""
    opts = {"readOnly": read_only, "placeholder": placeholder, "night": night}
    return f"rdMath.configure({json.dumps(opts)});"


CLEAR_CALL = "rdMath.clear();"
FOCUS_CALL = "rdMath.focus();"


def value_from(cmd: str) -> str | None:
    """The LaTeX in a ``rd:math:`` bridge command, or None for any other command."""
    return cmd[len(VALUE_PREFIX) :] if cmd.startswith(VALUE_PREFIX) else None
