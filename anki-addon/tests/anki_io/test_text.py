"""anki_io/text.py: grading_text. No collection needed (conftest sets the language
that strip_html needs)."""

from __future__ import annotations

import pytest

from recalldrill.anki_io.text import grading_text, pre_strip, tidy


@pytest.mark.parametrize(
    ("html", "text"),
    [
        ("a<br>b", "a b"),
        ("a<br/>b<BR />c", "a b c"),
        ("<div>x</div><div>y</div>", "x y"),
        ("a<br>b<div>c</div>", "a b c"),  # Phase 0: strip_html alone gives "abc"
        ("<p>one</p><p>two</p>", "one two"),
        ("<ul><li>a</li><li>b</li></ul>", "a b"),
        ("front<hr id=answer>back", "front back"),
        ("a&nbsp;b", "a b"),
        ("&nbsp; a &nbsp;&nbsp; b&nbsp;", "a b"),
        ("&lt;b&gt; &amp; &quot;", '<b> & "'),
        ("<b>os</b>seous <i>tissue</i>", "osseous tissue"),
        ("word [sound:x.mp3]", "word"),
        ("[sound:x.mp3]", ""),
        ("[anki:tts lang=en_US]hi[/anki:tts]", ""),
        ("say [anki:tts lang=en_US voices=Apple_Samantha]hi\nthere[/anki:tts] now", "say now"),
        ("<img src=x.jpg>", ""),
        ('<img src="x.jpg"> caption', "caption"),
        ("tab\tand\nnewline em-space", "tab and newline em-space"),
        ("", ""),
        # Placeholders in a rendered side (card.render_output().question_text).
        ("q [anki:play:q:0] {{x}}\n\n[[type:Back]]", "q {{x}}"),
        ("[anki:play:a:12]answer", "answer"),
        ("[[type:cloze:Text]]", ""),
        # A rendered cloze: the data-cloze attribute is part of the tag.
        (
            '<span class="cloze" data-cloze="osseous&#x20;tissue" data-ordinal="1">[...]</span>.',
            "[...].",
        ),
        ("<style>.x{}</style><!-- c -->kept", "kept"),
    ],
)
def test_grading_text(html: str, text: str) -> None:
    assert grading_text(html) == text


def test_pre_strip_turns_blocks_into_spaces_only() -> None:
    assert pre_strip("a<br>b<div>c</div><b>d</b>") == "a b c <b>d</b>"
    assert pre_strip("x[sound:a.mp3][anki:play:q:0][[type:F]]") == "x"


def test_tidy_uses_js_whitespace() -> None:
    assert tidy("  a \t\n b ﻿") == "a b"
    # U+0085 and U+001F are not JS whitespace, so they stay (engine rule).
    assert tidy("a\u0085b") == "a\u0085b"
