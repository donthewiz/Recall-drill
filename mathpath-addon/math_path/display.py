"""Math shown to the learner: keyboard text and recipe prompts as HTML with MathJax (pure).

Everything math that appears on screen goes through here, so it is typeset with MathJax and never
shown as raw keyboard or LaTeX text:

- :func:`kb_html` takes the *keyboard form*, possibly mixed with prose ("Let u = x^2: u^2 + 3u = 0",
  "x = 3: f(3) = 4, click (3, 4)") and wraps each run of math in ``\\( ... \\)``.
- :func:`prompt_html` takes a recipe's prompt template, which mixes prose, raw LaTeX
  (``\\dfrac{...}{...}``) and ``{tex:name}`` fills, and does the same for LaTeX.

The split into prose and math is a plain rule over whitespace-separated chunks (see
:func:`_classify`); anything the math reader can't parse is shown as ordinary text, never lost.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from html import escape
from typing import Any

from . import loader

_PUNCT = ".,;:!?"
_KNOWN_WORDS = frozenset(
    "sqrt abs inf pi sin cos tan ln log exp arcsin arccos arctan "
    "alpha beta gamma delta theta lambda sigma omega phi rho tau".split()
)
_FUNCTION_CALL = re.compile(
    r"[(\[]*(?:" + "|".join(sorted(_KNOWN_WORDS, key=len, reverse=True)) + r")\("
)
_STOP_WORDS = frozenset("is of to at in on or an as by if it no so we do be".split())
_PLACEHOLDER = re.compile(r"\{(tex:|fix\d:)?([A-Za-z_][A-Za-z0-9_]*)\}")
_SENTINEL = "\u0001"
_SENTINEL_RE = re.compile(_SENTINEL + r"(\d+)" + _SENTINEL)
_MATH_MARKS = re.compile(r"[0-9\\{}()\[\]^_|=<>+\-*/\u00b7\u2264\u2265\u00b1]")
_OPERATOR_ONLY = re.compile(r"[=<>+\-*/^|\u00b7\u2264\u2265\u00b1]+")


def _classify(chunk: str, *, tex: bool) -> str:
    """ "math", "letter" (a lone letter), "pair" (two letters: ``bx``) or "prose".

    Letters and pairs are math only next to math (see :func:`_runs`)."""
    core = chunk.strip(_PUNCT)
    if tex and "\\" in core:
        return "math"  # \ge, \dfrac{..}{..}, \sqrt{..}
    if not core:
        return "prose"
    if re.fullmatch(r"[A-Za-z]{2,}\^\d+", core):
        return "prose"  # a unit squared: ft^2
    if _FUNCTION_CALL.match(core) or re.match(r"[A-Za-z]\(", core):
        return "math"  # sqrt(x, abs(x), sin(x
    bare = re.sub(r"[()\[\]{}]", "", core)
    if re.fullmatch(r"[A-Za-z]+", bare):
        word = bare.lower()
        if len(bare) == 1:
            return "prose" if chunk.endswith(":") else "letter"
        if word in _KNOWN_WORDS:
            return "math"
        if word in _STOP_WORDS or len(bare) >= 3:
            return "prose"
        return "pair"
    words = re.findall(r"[A-Za-z]+", core)
    if any(len(w) >= 3 and w.lower() not in _KNOWN_WORDS for w in words):
        return "prose"
    if _OPERATOR_ONLY.fullmatch(core) or _MATH_MARKS.search(core):
        return "math"
    return "prose"


def _runs(text: str, *, tex: bool) -> list[tuple[bool, str]]:
    """``(is_math, text)`` runs: consecutive math chunks (and letters touching math) joined;
    sentence punctuation after a run is moved out to the prose after it."""
    chunks = text.split()
    kinds = [_classify(c, tex=tex) for c in chunks]
    changed = True
    while (
        changed
    ):  # a lone letter next to math is math ("x = 3"), a pair between maths too ("+ bx +")
        changed = False
        for i, k in enumerate(kinds):
            if k not in ("letter", "pair"):
                continue
            left = i > 0 and kinds[i - 1] == "math"
            right = i + 1 < len(kinds) and kinds[i + 1] == "math"
            if (k == "letter" and (left or right)) or (k == "pair" and left and right):
                kinds[i] = "math"
                changed = True
    out: list[tuple[bool, str]] = []
    run: list[str] = []

    def flush() -> None:
        if not run:
            return
        joined = " ".join(run)
        stripped = joined.rstrip(_PUNCT)
        out.append((True, stripped))
        if stripped != joined:
            out.append((False, joined[len(stripped) :]))
        run.clear()

    for chunk, kind in zip(chunks, kinds, strict=True):
        if kind == "math":
            run.append(chunk)
            if chunk.endswith(":"):  # "u = x^2: u^2 + 1 = 0" is two runs
                flush()
        else:
            flush()
            out.append((False, chunk))
    flush()
    return out


def _join(parts: list[str]) -> str:
    """Join pieces with a space, except before closing punctuation."""
    html = ""
    for part in parts:
        if not html:
            html = part
        elif part and part[0] in _PUNCT:
            html += part
        else:
            html += " " + part
    return html


def _prose(text: str) -> str:
    """Prose as HTML: ``ft^2`` gets a real superscript."""
    return re.sub(r"\^(\d+)", r"<sup>\1</sup>", escape(text))


def tex_of_keyboard(text: str) -> str | None:
    """The LaTeX of keyboard text (one or several ``;``-separated answers), or None when the
    math reader can't parse it."""
    parse = loader.load().parse
    pieces: list[str] = []
    for part in _split_semicolons(text):
        try:
            pieces.append(parse.to_latex(parse.parse(part)))
        except parse.MathReadError:
            return None
    return r";\ ".join(pieces) if pieces else None


def _split_semicolons(text: str) -> list[str]:
    out: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == ";" and depth == 0:
            out.append(text[start:i])
            start = i + 1
    out.append(text[start:])
    return [p.strip() for p in out if p.strip()]


def math_span(tex: str) -> str:
    """Inline MathJax for LaTeX ``tex``."""
    return f"\\({escape(tex, quote=False)}\\)"


_LONE_NUMBER = re.compile(r"\(\s*(-?\d+(?:\.\d+)?(?:/\d+)?)\s*\)")
_STAR = re.compile(r"(?<=[0-9A-Za-z)])\*(?=[A-Za-z(])")


def _tidy(text: str) -> str:
    """Drop the ``*`` the checker's printer puts between a number or letter and a letter or
    bracket (``8*x`` -> ``8x``), so it is shown the way a textbook writes it."""
    return _STAR.sub("", text)


def kb_math_html(text: str) -> str:
    """Pure keyboard math (an answer) as a MathJax span, or escaped text if it can't be read."""
    tex = tex_of_keyboard(_tidy(text))
    return math_span(tex) if tex is not None else f'<span class="mp-raw">{escape(text)}</span>'


def _island_html(run: str) -> str:
    """One run of keyboard math as HTML. A run the reader can't parse gives up its dangling
    operators and unmatched brackets (they become prose around it) before falling back to text."""
    lone = _LONE_NUMBER.fullmatch(run.strip())
    if lone:  # (-6): the parentheses came from filling a template after a word, not from the math
        run = lone.group(1)
    tokens = run.split()
    lead: list[str] = []
    trail: list[str] = []
    while tokens and _OPERATOR_ONLY.fullmatch(tokens[0]) and len(tokens) > 1:
        lead.append(tokens.pop(0))
    while tokens and _OPERATOR_ONLY.fullmatch(tokens[-1]) and len(tokens) > 1:
        trail.insert(0, tokens.pop())
    core = " ".join(tokens)
    tex = tex_of_keyboard(_tidy(core))
    if tex is None:
        open_pre = ""
        close_post = ""
        c = core
        for _ in range(4):
            depth = 0
            bad_open: list[int] = []
            bad_close: list[int] = []
            for i, ch in enumerate(c):
                if ch in "([":
                    depth += 1
                    bad_open.append(i)
                elif ch in ")]":
                    if bad_open:
                        bad_open.pop()
                    else:
                        bad_close.append(i)
            if not bad_open and not bad_close:
                break
            if bad_open and bad_open[0] == 0:
                open_pre += c[0]
                c = c[1:]
            elif bad_close and bad_close[-1] == len(c) - 1:
                close_post = c[-1] + close_post
                c = c[:-1]
            else:
                break
        tex = tex_of_keyboard(_tidy(c)) if c else None
        if tex is None:
            return f'<span class="mp-raw">{escape(run)}</span>'
        pieces = [escape(" ".join(lead)), escape(open_pre) + math_span(tex) + escape(close_post)]
        return _join([p for p in pieces if p] + ([escape(" ".join(trail))] if trail else []))
    pieces = [escape(" ".join(lead)), math_span(tex), escape(" ".join(trail))]
    return _join([p for p in pieces if p])


def kb_html(text: str) -> str:
    """Mixed prose and keyboard math as HTML (see the module docstring)."""
    parts: list[str] = []
    for is_math, run in _runs(text, tex=False):
        parts.append(_island_html(run) if is_math else _prose(run))
    return _join(parts)


def fill_prompt(template: str, env: Mapping[str, Any]) -> str:
    """The prompt as HTML for MathJax. ``{tex:name}`` is the checker's LaTeX; a plain ``{name}`` is
    its keyboard text read as math; ``{fixN:name}`` a rounded decimal. Raw LaTeX in the template
    (``\\dfrac``, ``\\sqrt``, ``\\ge``) is kept, and each run of it becomes one MathJax span."""
    core = loader.load()
    pieces: list[str] = []

    def hold(m: re.Match[str]) -> str:
        value = core.validator.fill(m.group(0), env)
        if m.group(1) is None:  # a plain name: keyboard text -> LaTeX when it reads as math
            value = tex_of_keyboard(value) or value
        pieces.append(value)
        return f"{_SENTINEL}{len(pieces) - 1}{_SENTINEL}"

    held = _PLACEHOLDER.sub(hold, template)
    parts: list[str] = []
    for is_math, run in _runs(held, tex=True):
        if is_math:
            tex = _SENTINEL_RE.sub(lambda m: pieces[int(m.group(1))], run)
            parts.append(math_span(tex))
        else:
            parts.append(_prose(_SENTINEL_RE.sub(lambda m: pieces[int(m.group(1))], run)))
    return _join(parts)
