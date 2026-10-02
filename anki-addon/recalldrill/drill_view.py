"""The drill window's web area as HTML (pure): card, feedback, batch and done screens.

The Qt window (``ui/drill_window.py``) loads :data:`SHELL_BODY` once with
``AnkiWebView.stdHtml`` and then calls ``rdRender(payload)`` with what
:func:`render` returns. Everything here reads a :class:`ViewModel` (or a
:class:`DoneSummary`) and nothing else.

``prepare`` is ``mw.prepare_card_text_for_display``: it escapes media file
names and turns ``[anki:play:q:N]`` / ``[anki:play:a:N]`` into ▶ buttons that
send ``play:q:N`` through ``pycmd``. Tests pass the identity.

Colors are the web app's (``src/index.css``): the same green and red, with the
same meaning (``success`` = right, ``danger`` = wrong, ``accent`` = info), in
light and night mode.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from html import escape
from typing import Any

from .card_html import display_extra, display_front
from .controller import BatchDoneView, DoneSummary, FeedbackView, ViewModel
from .engine.types import WordDiffResult

Prepare = Callable[[str], str]

EDITING_NOTICE = (
    "Editing this card in Anki's Browser. Close the Browser (or press Done editing) "
    "to come back to the drill."
)

SHELL_CSS = """
:root {
  --rd-surface-1: #EFF2F5; --rd-card: #FFFFFF; --rd-text: #1E232A;
  --rd-text-2: #5F6773; --rd-muted: #8E97A4; --rd-border: #E2E7ED;
  --rd-accent: #2563EB; --rd-accent-bg: #EFF6FF; --rd-warning: #D97706;
  --rd-success: #16A34A; --rd-success-bg: #F0FDF4;
  --rd-danger: #DC2626; --rd-danger-bg: #FEF2F2;
}
.night-mode, body.nightMode {
  --rd-surface-1: #171B21; --rd-card: #181D24; --rd-text: #F1F4F8;
  --rd-text-2: #9AA4B2; --rd-muted: #647082; --rd-border: #28303C;
  --rd-accent: #3B82F6; --rd-accent-bg: #1E293B; --rd-warning: #F59E0B;
  --rd-success: #22C55E; --rd-success-bg: #132D1E;
  --rd-danger: #EF4444; --rd-danger-bg: #321616;
}
body { margin: 12px 16px; }
#rd-root { max-width: 900px; margin: 0 auto; }
.rd-card { border: 1px solid var(--rd-border); border-radius: 14px; padding: 18px 22px;
  transition: background-color .2s, border-color .2s; }
.rd-card.rd-flash-success { background: var(--rd-success-bg); border-color: var(--rd-success); }
.rd-card.rd-flash-danger { background: var(--rd-danger-bg); border-color: var(--rd-danger); }
.rd-head { display: flex; justify-content: space-between; align-items: center;
  margin-bottom: 10px; text-align: left; font-family: sans-serif; }
.rd-pill { font-size: 11px; font-weight: 600; text-transform: uppercase; letter-spacing: .05em;
  color: var(--rd-accent); background: var(--rd-accent-bg); padding: 2px 10px;
  border-radius: 999px; }
.rd-badge { font-size: 11px; color: var(--rd-muted); }
.rd-hint { color: var(--rd-text-2); }
.rd-sub { margin: 14px 0 4px; min-height: 28px; }
.rd-cue { display: inline-block; font-family: Consolas, "Courier New", monospace;
  font-size: 16px; font-weight: 600; color: var(--rd-accent); background: var(--rd-surface-1);
  border: 1px solid var(--rd-border); border-radius: 8px; padding: 4px 12px;
  white-space: pre-wrap; }
.rd-blind { font-size: 12px; font-style: italic; color: var(--rd-muted); font-family: sans-serif; }
.rd-feedback { margin-top: 10px; font-family: sans-serif; }
.rd-notice { font-size: 13px; color: var(--rd-text-2); margin: 6px 0; }
.rd-fb { font-size: 15px; font-weight: 600; margin: 6px 0; }
.rd-fb-success { color: var(--rd-success); }
.rd-fb-danger { color: var(--rd-danger); }
.rd-fb-info { color: var(--rd-accent); }
.rd-diff { font-family: Consolas, "Courier New", monospace; font-size: 15px; line-height: 2;
  color: var(--rd-text); background: var(--rd-surface-1); border: 1px solid var(--rd-border);
  border-radius: 10px; padding: 8px 12px; margin: 6px 0; }
.rd-w { display: inline-block; margin: 0 3px; }
.rd-miss { color: var(--rd-danger); font-weight: 700; text-decoration: underline;
  text-decoration-thickness: 2px; text-underline-offset: 4px; background: var(--rd-danger-bg);
  border: 1px solid var(--rd-danger); border-radius: 4px; padding: 0 5px; }
.rd-answer { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--rd-border); }
.rd-extra { margin-top: 12px; padding-top: 10px; border-top: 1px solid var(--rd-border);
  color: var(--rd-text-2); font-size: 16px; }
.rd-extra-label { font-weight: 700; text-transform: uppercase; letter-spacing: .05em;
  font-size: 11px; margin-right: 6px; font-family: sans-serif; }
.rd-screen { text-align: center; font-family: sans-serif; color: var(--rd-text); }
.rd-screen h2 { font-size: 22px; margin: 6px 0; }
.rd-screen .rd-deck { color: var(--rd-text-2); margin: 0 0 14px; }
.rd-grid { display: flex; gap: 12px; justify-content: center; margin: 14px 0; }
.rd-stat { flex: 1; max-width: 180px; text-align: left; background: var(--rd-surface-1);
  border: 1px solid var(--rd-border); border-radius: 12px; padding: 10px 14px; }
.rd-stat-label { font-size: 11px; font-weight: 600; text-transform: uppercase;
  letter-spacing: .05em; color: var(--rd-text-2); }
.rd-stat-value { font-size: 20px; font-weight: 700; }
.rd-stat-value small { font-size: 12px; font-weight: 400; color: var(--rd-muted); }
.rd-line { font-size: 12px; color: var(--rd-muted); margin: 6px 0; }
.rd-section { text-align: left; border: 1px solid var(--rd-border); border-radius: 12px;
  padding: 10px 14px; margin: 14px 0; }
.rd-section-title { font-size: 11px; font-weight: 700; text-transform: uppercase;
  letter-spacing: .05em; color: var(--rd-text-2); margin-bottom: 6px; }
.rd-row { padding: 6px 0; border-top: 1px solid var(--rd-border); font-size: 14px; }
.rd-row:first-of-type { border-top: none; }
.rd-row-meta { font-size: 12px; color: var(--rd-muted); }
.rd-span { display: inline-block; font-family: Consolas, monospace; font-size: 12px;
  color: var(--rd-danger); background: var(--rd-danger-bg); border-radius: 4px;
  padding: 0 5px; margin: 3px 4px 0 0; }
"""

SHELL_JS = """
var rdFlashTimer = null;
function rdRender(p) {
  document.getElementById("rd-card-css").textContent = p.css;
  document.body.className = p.bodyClass;
  var root = document.getElementById("rd-root");
  root.innerHTML = p.html;
  if (window.MathJax && MathJax.typesetPromise) {
    MathJax.typesetPromise([root]).catch(function() {});
  }
}
function rdFlash(ok) {
  var card = document.getElementById("rd-card");
  if (!card) { return; }
  card.classList.remove("rd-flash-success", "rd-flash-danger");
  card.classList.add(ok ? "rd-flash-success" : "rd-flash-danger");
  if (rdFlashTimer) { clearTimeout(rdFlashTimer); }
  rdFlashTimer = setTimeout(function() {
    var c = document.getElementById("rd-card");
    if (c) { c.classList.remove("rd-flash-success", "rd-flash-danger"); }
  }, FLASH_MS);
}
document.addEventListener("keydown", function(e) {
  var cmd = null;
  if (e.key === "Enter") { cmd = (e.ctrlKey || e.metaKey) ? "rd:ctrl-enter" : "rd:enter"; }
  else if ((e.ctrlKey || e.metaKey) && (e.key === "e" || e.key === "E")) { cmd = "rd:edit"; }
  else if ((e.ctrlKey || e.metaKey) && (e.key === "r" || e.key === "R")) { cmd = "rd:replay"; }
  if (cmd) { e.preventDefault(); pycmd(cmd); }
});
"""


def shell_body(flash_ms: int) -> str:
    """The page loaded once; Escape is AnkiWebView's own ``pycmd("close")``."""
    js = SHELL_JS.replace("FLASH_MS", str(flash_ms))
    return (
        f"<style>{SHELL_CSS}</style><style id='rd-card-css'></style>"
        f"<div id='rd-root'></div><script>{js}</script>"
    )


def render_call(payload: dict[str, str]) -> str:
    return f"rdRender({json.dumps(payload)});"


# ---------------------------------------------------------------------------
# Pieces
# ---------------------------------------------------------------------------


def diff_html(diff: Sequence[WordDiffResult]) -> str:
    """SessionView's word diff: matched words plain, missed words red and underlined."""
    words = [
        f'<span class="rd-w{"" if w["matched"] else " rd-miss"}">{escape(w["word"])}</span>'
        for w in diff
    ]
    return f'<div class="rd-diff">{"".join(words)}</div>'


_FB_MARK = {"success": "✓ ", "danger": "✕ ", "info": "• "}


def feedback_html(fb: FeedbackView) -> str:
    out = f'<div class="rd-fb rd-fb-{fb.type}">{_FB_MARK[fb.type]}{escape(fb.text)}</div>'
    if fb.diff is not None:
        out += diff_html(fb.diff)
    return out


def sub_html(view: ViewModel) -> str:
    if view.sub_text:
        return f'<span class="rd-cue">{escape(view.sub_text)}</span>'
    if view.blind_hint:
        return f'<span class="rd-blind">{escape(view.blind_hint)}</span>'
    return ""


def card_html(view: ViewModel, prepare: Prepare) -> str:
    """The trial and feedback screen."""
    head = (
        f'<div class="rd-head"><span class="rd-pill">{escape(view.label)}</span>'
        f'<span class="rd-badge">{escape(view.cue_badge)}</span></div>'
    )
    front = f'<div class="rd-front">{prepare(display_front(view.front_html, view.hint))}</div>'
    parts: list[str] = []
    if view.editing:
        parts.append(f'<div class="rd-notice">{escape(EDITING_NOTICE)}</div>')
    if view.notice:
        parts.append(f'<div class="rd-notice">{escape(view.notice)}</div>')
    if view.feedback is not None:
        parts.append(feedback_html(view.feedback))
    if view.answer_html is not None:
        parts.append(f'<div class="rd-answer">{prepare(view.answer_html)}</div>')
    if view.extra_html is not None:
        parts.append(
            '<div class="rd-extra"><span class="rd-extra-label">Extra</span>'
            f"{prepare(display_extra(view.extra_html))}</div>"
        )
    return (
        f'<div id="rd-card" class="rd-card">{head}{front}'
        f'<div class="rd-sub">{sub_html(view)}</div>'
        f'<div class="rd-feedback">{"".join(parts)}</div></div>'
    )


def _stat(label: str, value: str) -> str:
    return (
        f'<div class="rd-stat"><div class="rd-stat-label">{escape(label)}</div>'
        f'<div class="rd-stat-value">{value}</div></div>'
    )


def batch_done_html(b: BatchDoneView) -> str:
    """SessionView's batch interstitial (the buttons are native)."""
    out = (
        f'<div class="rd-card rd-screen"><h2>Batch {b.batch_number} of {b.total_batches} '
        "complete!</h2>"
        '<div class="rd-grid">'
        + _stat("Mastered", f"{b.items_mastered} <small>/ {b.batch_size}</small>")
        + _stat("Trials", str(b.trials_spent))
        + _stat("Accuracy", f"{b.accuracy_percent}%")
        + "</div>"
    )
    if b.remaining:
        out += f'<p class="rd-line">{escape(b.remaining)}</p>'
    return out + "</div>"


def done_html(d: DoneSummary) -> str:
    """DoneView (the buttons are native)."""
    out = (
        f'<div class="rd-card rd-screen"><h2>{escape(d.title)}</h2>'
        f'<p class="rd-deck">{escape(d.deck_name)}</p>'
        '<div class="rd-grid">'
        + _stat("Mastered", f"{d.mastered} <small>/ {d.total}</small>")
        + _stat("Attempts", str(d.attempts))
        + _stat("Accuracy", f"{d.accuracy_percent}%")
        + f'</div><p class="rd-line">{escape(d.accuracy_line)}</p>'
    )
    if d.hardest:
        rows = "".join(
            f'<div class="rd-row"><b>{escape(h.front)}</b> → {escape(h.back)}'
            f'<div class="rd-row-meta">{escape(h.parts)}</div>'
            + "".join(f'<span class="rd-span">{escape(s)}</span>' for s in h.hard_spans)
            + "</div>"
            for h in d.hardest
        )
        out += (
            '<div class="rd-section" id="hardest-cards">'
            f'<div class="rd-section-title">Where you struggled</div>{rows}</div>'
        )
    out += f'<p class="rd-line">{escape(d.summary)}</p>'
    if d.missed_in_final:
        rows = "".join(
            f'<div class="rd-row"><b>{escape(m.front)}</b> → {escape(m.back)}'
            f'<div class="rd-row-meta">{m.final_misses} miss'
            f"{'' if m.final_misses == 1 else 'es'}</div></div>"
            for m in d.missed_in_final
        )
        out += (
            '<div class="rd-section" id="final-check-misses">'
            f'<div class="rd-section-title">Missed in final check</div>{rows}</div>'
        )
    return out + "</div>"


def render(
    view: ViewModel, prepare: Prepare, body_class: str, done: DoneSummary | None = None
) -> dict[str, Any]:
    """The ``rdRender`` payload. ``body_class``: Anki's body classes (with
    ``card cardN`` on the card screen, so the note type CSS applies as in the
    reviewer); ``done``: the summary, on the done screen."""
    if view.mode == "done":
        assert done is not None, "the done screen needs its summary"
        return {"css": "", "bodyClass": body_class, "html": done_html(done)}
    if view.mode == "batch_done":
        assert view.batch_done is not None
        return {"css": "", "bodyClass": body_class, "html": batch_done_html(view.batch_done)}
    return {"css": view.css, "bodyClass": body_class, "html": card_html(view, prepare)}
