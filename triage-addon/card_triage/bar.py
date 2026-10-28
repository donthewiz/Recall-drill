"""The prompt bar: its text, its messages and the JavaScript that shows and hides it (pure).

The bar is one element, ``#card-triage-bar``, put first in the reviewer page's ``<body>`` together
with one ``<style>`` element whose rules all start with that id (nothing of Anki's page is
restyled). It takes its own space at the top, so the card moves down below it instead of being
covered (Don, 2026-10-28, after seeing it cover a cloze question in real Anki). Light or dark
follows Anki's own night-mode classes on ``<html>`` and ``<body>``. It
never takes keyboard focus: its buttons are out of the tab order and ignore the mouse-down that
would focus them.
"""

from __future__ import annotations

import json

PREFIX = "card_triage:"
"""Every message from the bar starts with this; every other message is someone else's."""
CMD_SET_ASIDE = PREFIX + "set_aside"
CMD_KEEP_GOING = PREFIX + "keep_going"

BAR_ID = "card-triage-bar"
STYLE_ID = "card-triage-bar-style"

TIMER_TEXT = "Stuck on this one?"
SET_ASIDE_LABEL = "Set aside"
KEEP_GOING_LABEL = "Keep going"


def again_text(count: int) -> str:
    noun = "Again" if count == 1 else "Agains"
    return f"{count} {noun} on this card."


def is_ours(message: str) -> bool:
    return message.startswith(PREFIX)


def key_label(key: str) -> str:
    """A key as the bar shows it: a single letter in capitals (``x`` → ``X``)."""
    return key.upper() if len(key) == 1 else key


_CSS = f"""
#{BAR_ID} {{
  position: sticky; top: 0; z-index: 2147483000; margin-bottom: 12px;
  box-sizing: border-box; padding: 4px 12px; text-align: center;
  font: 14px/1.4 system-ui, -apple-system, "Segoe UI", sans-serif;
  background: #fff4cc; color: #3d3200; border-bottom: 1px solid #e3cf7a;
  user-select: none; -webkit-user-select: none;
}}
#{BAR_ID} .ct-btn {{
  font: inherit; color: inherit; background: transparent; border: 0; padding: 0 2px;
  text-decoration: underline; cursor: pointer; outline: none;
}}
#{BAR_ID} .ct-btn.ct-primary {{ font-weight: 600; }}
#{BAR_ID} .ct-dot {{ opacity: 0.6; white-space: pre; }}
.night-mode #{BAR_ID}, .nightMode #{BAR_ID} {{
  background: #3a3418; color: #f3e8b4; border-bottom-color: #6b5f2a;
}}
"""


def _js_str(text: str) -> str:
    return json.dumps(text)


def show_js(message: str, key: str) -> str:
    """JavaScript that puts the bar at the top of the page (replacing any bar already there)."""
    return f"""(function () {{
  var old = document.getElementById({_js_str(BAR_ID)});
  if (old) old.remove();
  var oldStyle = document.getElementById({_js_str(STYLE_ID)});
  if (oldStyle) oldStyle.remove();
  var style = document.createElement("style");
  style.id = {_js_str(STYLE_ID)};
  style.textContent = {_js_str(_CSS)};
  var bar = document.createElement("div");
  bar.id = {_js_str(BAR_ID)};
  bar.setAttribute("role", "status");
  function btn(label, cmd, cls) {{
    var b = document.createElement("button");
    b.type = "button"; b.className = "ct-btn " + cls; b.tabIndex = -1; b.textContent = label;
    b.addEventListener("mousedown", function (e) {{ e.preventDefault(); }});
    b.addEventListener("click", function (e) {{ e.preventDefault(); pycmd(cmd); }});
    return b;
  }}
  var msg = document.createElement("span");
  msg.textContent = {_js_str(message)} + " ";
  var dot = document.createElement("span");
  dot.className = "ct-dot"; dot.textContent = " \\u00b7 ";
  bar.appendChild(msg);
  bar.appendChild(btn({_js_str(f"{SET_ASIDE_LABEL} ({key_label(key)})")},
                      {_js_str(CMD_SET_ASIDE)}, "ct-primary"));
  bar.appendChild(dot);
  bar.appendChild(btn({_js_str(KEEP_GOING_LABEL)}, {_js_str(CMD_KEEP_GOING)}, "ct-secondary"));
  // Span the page edge to edge across the body's own margin (read, not changed).
  var cs = getComputedStyle(document.body);
  bar.style.marginTop = "-" + cs.marginTop;
  bar.style.marginLeft = "-" + cs.marginLeft;
  bar.style.marginRight = "-" + cs.marginRight;
  document.body.appendChild(style);
  document.body.insertBefore(bar, document.body.firstChild);
}})();"""


def hide_js() -> str:
    """JavaScript that removes the bar (and its style) if it is there."""
    return f"""(function () {{
  [{_js_str(BAR_ID)}, {_js_str(STYLE_ID)}].forEach(function (id) {{
    var el = document.getElementById(id);
    if (el) el.remove();
  }});
}})();"""
