"""Card HTML for display (pure): what the drill shows of Anki's rendered sides.

Anki's rendered question still holds ``[[type:F]]`` (the reviewer's type-in
box; the drill has its own input) and ``[anki:play:q:N]`` markers. The type
placeholder goes here; the play markers are turned into ▶ buttons by the UI
(``mw.prepare_card_text_for_display``, which also escapes media file names).
"""

from __future__ import annotations

import re
from html import escape

_TYPE_RE = re.compile(r"\[\[type:[^\]]*\]\]")
_SOUND_RE = re.compile(r"\[sound:[^\]]*\]")
_PLAY_RE = re.compile(r"\[anki:play:[qa]:[0-9]+\]")
_TAG_RE = re.compile(r"<[^>]*>")
_WS_RE = re.compile(r"\s+")
_IMG_SRC_RE = re.compile(r"<img\b[^>]*?\bsrc\s*=\s*([\"'])(.*?)\1", re.IGNORECASE | re.DOTALL)
_ANSWER_HR_RE = re.compile(r"<hr\b[^>]*\bid\s*=\s*[\"']?answer\b[^>]*>", re.IGNORECASE)


def strip_type_placeholders(html: str) -> str:
    return _TYPE_RE.sub("", html)


def display_front(front_html: str, hint: str) -> str:
    """The rendered question without Anki's type-in placeholder, plus the
    disambiguation hint (kept apart from ``front_html`` by ``build``)."""
    out = strip_type_placeholders(front_html)
    if hint:
        out += f'<span class="rd-hint">{escape(hint)}</span>'
    return out


def display_extra(extra_html: str) -> str:
    """The raw Extra field: ``[sound:]`` references in a field aren't rendered
    by Anki's template pass, so they would show as text."""
    return _SOUND_RE.sub("", extra_html)


def _text(html: str) -> str:
    t = _PLAY_RE.sub("", strip_type_placeholders(html))
    return _WS_RE.sub(" ", _TAG_RE.sub(" ", t).replace("&nbsp;", " ")).strip()


def _srcs(html: str) -> set[str]:
    return {m.group(2) for m in _IMG_SRC_RE.finditer(html)}


def _has_content(html: str) -> bool:
    return bool(_text(html)) or bool(_srcs(html))


def same_content(a: str, b: str) -> bool:
    """Same visible text and the same images (markup aside)."""
    return _text(a) == _text(b) and _srcs(a) == _srcs(b)


def answer_side(front_html: str, answer_html: str) -> str:
    """What to show of the rendered answer below the diff on an image card.

    Split at ``<hr id=answer>``:

    - the part before it is the front again (``{{FrontSide}}``) or empty: show
      the part after it (the back);
    - otherwise the part before it *is* the answer (the anki-cards image
      occlusion lookalike: ``{{Answer}}<hr id=answer>`` then Extra, FullContext,
      Source), so show that, and the Extra stays in its own section.

    No ``<hr id=answer>``: the whole rendered answer.
    """
    m = _ANSWER_HR_RE.search(answer_html)
    if m is None:
        return answer_html
    before, after = answer_html[: m.start()], answer_html[m.end() :]
    if not _has_content(before) or same_content(before, front_html):
        return after
    return before
