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

_GROUP_OPEN = "\ue200"
_GROUP_CLOSE = "\ue201"
_UNION = "∪"

_ATOM = re.compile(r"(?<![A-Za-z0-9_])\(([A-Za-z]|\d+(?:\.\d+)?)\)")
_DOUBLE = re.compile(r"\(\(([^()]*)\)\)")
_OR = re.compile(r"\\(?:lor|vee)(?![A-Za-z])")
"""MathLive turns the letters "or" typed in a math field into ``\\lor``."""
_CALL = re.compile(r"[A-Za-z]+(?=\()")
_FUNCTIONS = tuple(
    sorted(
        ("sqrt", "abs", "sin", "cos", "tan", "arcsin", "arccos", "arctan", "ln", "log", "exp"),
        key=len,
        reverse=True,
    )
)


def _split_call(m: re.Match[str]) -> str:
    """``isqrt(448)`` (the imaginary unit, then a root) is SymPy's integer square root: write the
    product out (``i*sqrt(448)``). Same for ``pisqrt``, ``xabs`` ... Real function names stay."""
    name = m.group()
    if name in _FUNCTIONS:
        return name
    for f in _FUNCTIONS:
        if name.endswith(f):
            return f"{name[: -len(f)]}*{f}"
    return name


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
        pieces = [parse.latex_to_keyboard(p) for p in _OR.split(latex)]
    except parse.MathReadError as exc:
        if "placeholder" in latex:
            raise UnreadableAnswer("Finish the fraction or root first.") from exc
        raise UnreadableAnswer("That can't be read as math. Check the brackets.") from exc
    raw = " or ".join(p.strip() for p in pieces)
    s = raw.replace(_GROUP_OPEN, "(").replace(_GROUP_CLOSE, ")").replace(_UNION, " U ")
    s = _CALL.sub(_split_call, s)
    while True:  # drop redundant parentheses: ((8)) -> 8, ((6)/(8)) -> (6/8)
        t = _ATOM.sub(r"\1", s)
        t = _DOUBLE.sub(r"(\1)", t)
        if t == s:
            return s.strip()
        s = t
