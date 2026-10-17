"""The palette's LaTeX as the keyboard form the checker reads (the adapter; pure, lazy SymPy-free).

MathLive gives LaTeX. ``latex_to_keyboard`` (Recall Drill's palette reader, copied in
``core/drill_check/math_parse.py``) turns it into *Recall Drill's* internal keyboard form, which
is not what ``verify_math`` reads: it wraps groups in the private-use characters U+E200 / U+E201
and writes the union as the symbol ∪. Without this adapter every fraction would be graded wrong,
and with plain parentheses the form check would miss unsimplified radicals (``sqrt((8))`` passes
as "simplified"). ``docs/DECISIONS.md`` has the long version.
"""

from __future__ import annotations

import re

from . import loader

_GROUP_OPEN = ""
_GROUP_CLOSE = ""
_UNION = "∪"

_ATOM = re.compile(r"(?<![A-Za-z0-9_])\(([A-Za-z]|\d+(?:\.\d+)?)\)")
_DOUBLE = re.compile(r"\(\(([^()]*)\)\)")


class UnreadableAnswer(ValueError):
    """The field can't be turned into an answer; ``str(exc)`` says why, for the learner."""


def palette_to_keyboard(latex: str) -> str:
    """The keyboard form of the palette's ``latex`` (what ``verify_math`` reads).

    Raises :class:`UnreadableAnswer` for an empty field, an unfinished fraction or root, or LaTeX
    the palette can't make."""
    if not latex.strip():
        raise UnreadableAnswer("Type an answer first.")
    parse = loader.load().parse
    try:
        raw: str = parse.latex_to_keyboard(latex)
    except parse.MathReadError as exc:
        if "placeholder" in latex:
            raise UnreadableAnswer("Finish the fraction or root first.") from exc
        raise UnreadableAnswer("That can't be read as math. Check the brackets.") from exc
    s = raw.replace(_GROUP_OPEN, "(").replace(_GROUP_CLOSE, ")").replace(_UNION, " U ")
    while True:  # drop redundant parentheses: ((8)) -> 8, ((6)/(8)) -> (6/8)
        t = _ATOM.sub(r"\1", s)
        t = _DOUBLE.sub(r"(\1)", t)
        if t == s:
            return s.strip()
        s = t
