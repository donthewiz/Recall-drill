"""The text the drill grades, from a field's or a rendered side's HTML.

Every graded string goes through :func:`grading_text`. Display keeps the
original HTML; nothing here touches display.

The rules are plain regex steps (:func:`pre_strip`, :func:`tidy`) around
Anki's ``strip_html``. They need no collection, only ``anki.lang`` set up
(``strip_html`` goes through the i18n backend).
"""

from __future__ import annotations

import re

from anki.utils import strip_html

from ..engine.jscompat import WS_RE, js_trim

# Media and placeholders. A field holds [sound:x.mp3] and [anki:tts ...]...[/anki:tts];
# a rendered side (card.render_output().question_text) has them already swapped
# for [anki:play:q:N] / [anki:play:a:N], and {{type:F}} renders as [[type:F]].
_SOUND_RE = re.compile(r"\[sound:[^\]]*\]")
_TTS_RE = re.compile(r"\[anki:tts(?:[ \t][^\]]*)?\].*?\[/anki:tts\]", re.DOTALL)
_TTS_TAG_RE = re.compile(r"\[/?anki:tts[^\]]*\]")
_PLAY_RE = re.compile(r"\[anki:play:[qa]:[0-9]+\]")
_TYPE_RE = re.compile(r"\[\[type:[^\]]*\]\]")

# strip_html deletes tags without a space, so "a<br>b<div>c</div>" becomes "abc".
# Line breaks, rules and block elements (opening and closing tags) become spaces
# first. Inline tags (<b>, <i>, <span>, <sup>, ...) stay glued: "<b>os</b>seous"
# is one word.
_BLOCK_TAG_RE = re.compile(
    r"<br\b[^>]*>|<hr\b[^>]*>"
    r"|</?(?:div|p|li|ul|ol|dl|dt|dd|table|tr|td|th|h[1-6]|blockquote|pre"
    r"|details|summary|section|article|header|footer)\b[^>]*>",
    re.IGNORECASE,
)

_NBSP = " "


def pre_strip(html: str) -> str:
    """Steps 1 and 2: drop media and placeholders, then block tags -> spaces."""
    text = _SOUND_RE.sub("", html)
    text = _TTS_RE.sub("", text)
    text = _TTS_TAG_RE.sub("", text)
    text = _PLAY_RE.sub("", text)
    text = _TYPE_RE.sub("", text)
    return _BLOCK_TAG_RE.sub(" ", text)


def tidy(text: str) -> str:
    """Step 4: NBSP -> space, collapse whitespace (JS ``\\s+``), trim."""
    return js_trim(WS_RE.sub(" ", text.replace(_NBSP, " ")))


def grading_text(html: str) -> str:
    """Plain, single-spaced text of ``html`` for grading, hints and history.

    Order: drop ``[sound:]``/TTS/play/type placeholders, block tags -> spaces,
    ``strip_html`` (removes tags and unescapes entities), then :func:`tidy`.
    """
    if not html:
        return ""
    return tidy(strip_html(pre_strip(html)))
