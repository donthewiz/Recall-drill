"""Math answers as trees (pure): the keyboard form, the palette's LaTeX, and LaTeX out.

``parse`` reads the keyboard form the math skill writes into ``MathAnswer``
(``^`` powers, ``sqrt()``, ``+-``, ``/`` with parentheses, ``abs()``, ``pi``, ``i``,
``<=``/``>=``, intervals, unions with ``U``) into a :data:`Node` tree *as written*:
the order of terms, the parentheses and the ``+-`` signs are kept, so
``to_latex`` can show the answer the way the card has it. Comparing is
``math_answer``'s job.

``latex_to_keyboard`` turns the palette's MathLive LaTeX into that same keyboard
form, so one parser serves both. Nothing here imports SymPy.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from fractions import Fraction
from typing import Literal


class MathReadError(ValueError):
    """The text can't be read as math."""


# ---------------------------------------------------------------------------
# The tree
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Num:
    value: Fraction
    text: str


@dataclass(frozen=True)
class Sym:
    name: str
    """``x``, ``x_1``, ``pi``, ``inf``, ``i``, ``theta``."""


@dataclass(frozen=True)
class Neg:
    arg: Node


@dataclass(frozen=True)
class PM:
    """``+-arg``: both branches."""

    arg: Node


@dataclass(frozen=True)
class Add:
    terms: tuple[Node, ...]
    """Each term may be a :class:`Neg` (``a - b``) or a :class:`PM` (``a +- b``)."""


@dataclass(frozen=True)
class Mul:
    factors: tuple[Node, ...]
    explicit: tuple[bool, ...]
    """``explicit[k]``: factor ``k + 1`` followed a ``*`` (else it is juxtaposed)."""


@dataclass(frozen=True)
class Div:
    num: Node
    den: Node


@dataclass(frozen=True)
class Pow:
    base: Node
    exp: Node


@dataclass(frozen=True)
class Fn:
    name: str
    args: tuple[Node, ...]


@dataclass(frozen=True)
class Paren:
    """A group as written. ``open`` is ``""`` for the invisible group the LaTeX reader makes."""

    arg: Node
    open: str
    close: str


@dataclass(frozen=True)
class Seq:
    """Intervals, points and sets: ``[-2,5)``, ``(1,2)``, ``{1,2,3}``; and, with no
    brackets (``open == ""``), a comma list of answers: ``x=2, x=-3``."""

    open: str
    close: str
    items: tuple[Node, ...]


@dataclass(frozen=True)
class Rel:
    operands: tuple[Node, ...]
    ops: tuple[str, ...]
    """``=``, ``<``, ``<=``, ``>``, ``>=``, ``!=``; one fewer than the operands."""


@dataclass(frozen=True)
class Union:
    parts: tuple[Node, ...]


Node = Num | Sym | Neg | PM | Add | Mul | Div | Pow | Fn | Paren | Seq | Rel | Union


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------

INVISIBLE_OPEN = ""
INVISIBLE_CLOSE = ""
"""The grouping the LaTeX reader emits where LaTeX had braces: not drawn."""

_REPLACE = {
    "−": "-",
    "–": "-",
    "—": "-",
    "×": "*",
    "·": "*",
    "⋅": "*",
    "∙": "*",
    "÷": "/",
    "∕": "/",
    "⁄": "/",
    "≤": "<=",
    "≥": ">=",
    "≠": "!=",
    "±": "+-",
    "π": " pi ",
    "∞": " inf ",
    "√": " sqrt ",
    "²": "^2",
    "³": "^3",
    " ": " ",
    "　": " ",
    "⁢": "",
    "​": "",
    "﻿": "",
}

_GREEK = {
    "alpha": "alpha",
    "beta": "beta",
    "gamma": "gamma",
    "delta": "delta",
    "theta": "theta",
    "lambda": "lambda",
    "sigma": "sigma",
    "omega": "omega",
    "phi": "phi",
    "rho": "rho",
    "tau": "tau",
    "α": "alpha",
    "β": "beta",
    "γ": "gamma",
    "δ": "delta",
    "θ": "theta",
    "λ": "lambda",
    "σ": "sigma",
    "ω": "omega",
    "φ": "phi",
    "ρ": "rho",
    "τ": "tau",
}
_CONSTANTS = {"pi": "pi", "infinity": "inf", "inf": "inf"}
FUNCTIONS = (
    "arcsin",
    "arccos",
    "arctan",
    "sqrt",
    "root",
    "abs",
    "sin",
    "cos",
    "tan",
    "sec",
    "csc",
    "cot",
    "asin",
    "acos",
    "atan",
    "ln",
    "log",
    "exp",
)
_ALIASES = {"asin": "arcsin", "acos": "arccos", "atan": "arctan"}
_NAMES = sorted([*_GREEK, *_CONSTANTS], key=len, reverse=True)
_FUNCTIONS = sorted(FUNCTIONS, key=len, reverse=True)
_REL_OPS = ("<=", ">=", "!=", "==", "=", "<", ">")

_NUM_RE = re.compile(r"[0-9]+(?:\.[0-9]*)?|\.[0-9]+")

TokKind = Literal["num", "sym", "fn", "op", "union"]


@dataclass(frozen=True)
class _Tok:
    kind: TokKind
    value: str
    pos: int


def _normalize(text: str) -> str:
    out = text
    for old, new in _REPLACE.items():
        out = out.replace(old, new)
    return out


def _tokenize(source: str) -> list[_Tok]:
    text = _normalize(source)
    toks: list[_Tok] = []
    i = 0
    n = len(text)
    while i < n:
        ch = text[i]
        if ch.isspace():
            i += 1
            continue
        m = _NUM_RE.match(text, i)
        if m is not None:
            toks.append(_Tok("num", m.group(), i))
            i = m.end()
            continue
        if ch.isalpha():
            j = i
            while j < n and text[j].isalpha():
                j += 1
            i = _letters(text, i, j, toks)
            continue
        if ch == "∪":
            toks.append(_Tok("union", "U", i))
            i += 1
            continue
        if text.startswith("+-", i):
            toks.append(_Tok("op", "+-", i))
            i += 2
            continue
        two = text[i : i + 2]
        if two in ("<=", ">=", "!=", "=="):
            toks.append(_Tok("op", "=" if two == "==" else two, i))
            i += 2
            continue
        if ch in "+-*/^()[]{},=<>|" or ch in (INVISIBLE_OPEN, INVISIBLE_CLOSE):
            toks.append(_Tok("op", ch, i))
            i += 1
            continue
        raise MathReadError(f"unexpected {ch!r}")
    return _mark_unions(toks)


def _letters(text: str, start: int, end: int, toks: list[_Tok]) -> int:
    """Tokens for the letter run ``text[start:end]``; returns where scanning goes on
    (past a subscript that follows the run's last letter)."""
    run = text[start:end]
    pos = 0
    while pos < len(run):
        at = start + pos
        fn = next((f for f in _FUNCTIONS if run.startswith(f, pos)), None)
        if fn is not None and pos + len(fn) == len(run) and text[end : end + 1] == "(":
            toks.append(_Tok("fn", _ALIASES.get(fn, fn), at))
            return end
        name = next((c for c in _NAMES if run.startswith(c, pos)), None)
        if name is not None:
            canon = _CONSTANTS.get(name) or _GREEK[name]
            toks.append(_Tok("sym", canon, at))
            pos += len(name)
            continue
        letter = run[pos]
        pos += 1
        if pos < len(run):
            toks.append(_Tok("sym", letter, at))
            continue
        # The run's last letter: a subscript may follow (x_1, x_{12}, y2).
        sub, nxt = _subscript(text, end)
        toks.append(_Tok("sym", f"{letter}_{sub}" if sub else letter, at))
        return nxt
    return end


def _subscript(text: str, at: int) -> tuple[str, int]:
    """The subscript after a letter at ``text[at:]``: ``_1``, ``_{12}``, ``_a`` or digits
    right after the letter (``y2``). ("", at) when there is none."""
    if text[at : at + 1] == "_":
        if text[at + 1 : at + 2] == "{":
            close = text.find("}", at + 2)
            body = text[at + 2 : close] if close != -1 else ""
            if close == -1 or not body.isalnum() or not body.isascii():
                raise MathReadError("bad subscript")
            return body, close + 1
        m = re.compile(r"[0-9]+|[A-Za-z]").match(text, at + 1)
        if m is None:
            raise MathReadError("bad subscript")
        return m.group(), m.end()
    m = re.compile(r"[0-9]+(?![.0-9])").match(text, at)
    if m is not None:
        return m.group(), m.end()
    return "", at


def _mark_unions(toks: list[_Tok]) -> list[_Tok]:
    """``U`` between a closing and an opening bracket is the union sign."""
    out = list(toks)
    for k, t in enumerate(out):
        if t.kind != "sym" or t.value != "U" or k == 0 or k + 1 >= len(out):
            continue
        before, after = out[k - 1], out[k + 1]
        if before.kind == "op" and before.value in ")]" and after.kind == "op":
            if after.value in "([":
                out[k] = _Tok("union", "U", t.pos)
    return out


# ---------------------------------------------------------------------------
# The parser
# ---------------------------------------------------------------------------

_CLOSERS = {"(": ")", "[": "]", "{": "}"}
_MAX_DEPTH = 40


class _Parser:
    def __init__(self, toks: list[_Tok]) -> None:
        self.toks = toks
        self.i = 0
        self.depth = 0

    # -- helpers --------------------------------------------------------------

    def peek(self) -> _Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def is_op(self, *values: str) -> bool:
        t = self.peek()
        return t is not None and t.kind == "op" and t.value in values

    def take(self) -> _Tok:
        t = self.peek()
        if t is None:
            raise MathReadError("unexpected end")
        self.i += 1
        return t

    def expect(self, value: str) -> None:
        t = self.take()
        if t.kind != "op" or t.value != value:
            raise MathReadError(f"expected {value!r}")

    # -- grammar --------------------------------------------------------------

    def parse(self) -> Node:
        node = self.relation()
        if self.is_op(","):
            # A list of answers (``x=2, x=-3``, ``(1,2),(3,4)``): no brackets, any order.
            items = [node]
            while self.is_op(","):
                self.i += 1
                items.append(self.relation())
            node = Seq("", "", tuple(items))
        if self.peek() is not None:
            raise MathReadError("unexpected input")
        return node

    def relation(self) -> Node:
        first = self.union()
        operands = [first]
        ops: list[str] = []
        while self.is_op(*_REL_OPS):
            ops.append(self.take().value)
            operands.append(self.union())
        return Rel(tuple(operands), tuple(ops)) if ops else first

    def union(self) -> Node:
        parts = [self.additive()]
        while (t := self.peek()) is not None and t.kind == "union":
            self.i += 1
            parts.append(self.additive())
        return Union(tuple(parts)) if len(parts) > 1 else parts[0]

    def additive(self) -> Node:
        terms: list[Node] = []
        while True:
            sign = self.take().value if self.is_op("+", "-", "+-") else ""
            term = self.product()
            if sign == "-":
                term = Neg(term)
            elif sign == "+-":
                term = PM(term)
            terms.append(term)
            if not self.is_op("+", "-", "+-"):
                break
        return terms[0] if len(terms) == 1 else Add(tuple(terms))

    def product(self) -> Node:
        left = self.power()
        factors: list[Node] | None = None
        explicit: list[bool] = []
        while True:
            if self.is_op("*"):
                self.i += 1
                right = self.signed_power()
                is_explicit = True
            elif self.is_op("/"):
                self.i += 1
                left = Div(self._collapse(left, factors, explicit), self.signed_power())
                factors, explicit = None, []
                continue
            elif self._starts_factor(left, factors):
                right = self.power()
                is_explicit = False
            else:
                break
            if factors is None:
                factors = [left]
            factors.append(right)
            explicit.append(is_explicit)
        return self._collapse(left, factors, explicit)

    @staticmethod
    def _collapse(left: Node, factors: list[Node] | None, explicit: list[bool]) -> Node:
        return Mul(tuple(factors), tuple(explicit)) if factors is not None else left

    def _starts_factor(self, left: Node, factors: list[Node] | None) -> bool:
        """Implicit multiplication: the next token starts an atom."""
        t = self.peek()
        if t is None:
            return False
        last = factors[-1] if factors is not None else left
        if t.kind in ("sym", "fn"):
            return True
        if t.kind == "num":
            return isinstance(last, Paren)
        return t.kind == "op" and t.value in ("(", INVISIBLE_OPEN)

    def signed_power(self) -> Node:
        if self.is_op("+", "-", "+-"):
            sign = self.take().value
            inner = self.power()
            return Neg(inner) if sign == "-" else PM(inner) if sign == "+-" else inner
        return self.power()

    def power(self) -> Node:
        base = self.atom()
        if self.is_op("^"):
            self.i += 1
            self.depth += 1
            if self.depth > _MAX_DEPTH:
                raise MathReadError("too deep")
            try:
                return Pow(base, self.signed_power())
            finally:
                self.depth -= 1
        return base

    def atom(self) -> Node:
        t = self.take()
        if t.kind == "num":
            return Num(Fraction(t.value if not t.value.endswith(".") else t.value + "0"), t.value)
        if t.kind == "sym":
            return Sym(t.value)
        if t.kind == "fn":
            return self._function(t.value)
        if t.kind == "op" and t.value in ("(", "[", "{", INVISIBLE_OPEN):
            return self._group(t.value)
        if t.kind == "op" and t.value == "|":
            inner = self.additive()
            self.expect("|")
            return Fn("abs", (inner,))
        raise MathReadError(f"unexpected {t.value!r}")

    def _function(self, name: str) -> Node:
        if self.is_op("("):
            self.i += 1
            args = [self.relation()]
            while self.is_op(","):
                self.i += 1
                args.append(self.relation())
            self.expect(")")
        else:
            args = [self.power()]
        want = 2 if name == "root" else 1
        if len(args) != want:
            raise MathReadError(f"{name} takes {want} argument(s)")
        return Fn(name, tuple(args))

    def _group(self, opener: str) -> Node:
        self.depth += 1
        if self.depth > _MAX_DEPTH:
            raise MathReadError("too deep")
        closer = INVISIBLE_CLOSE if opener == INVISIBLE_OPEN else _CLOSERS[opener]
        items = [self.relation()]
        while self.is_op(","):
            self.i += 1
            items.append(self.relation())
        t = self.take()
        self.depth -= 1
        if t.kind != "op" or t.value not in (")", "]", "}", INVISIBLE_CLOSE):
            raise MathReadError("missing closing bracket")
        if opener == INVISIBLE_OPEN:
            if t.value != INVISIBLE_CLOSE or len(items) != 1:
                raise MathReadError("bad group")
            return Paren(items[0], "", "")
        if t.value == INVISIBLE_CLOSE:
            raise MathReadError("bad group")
        if len(items) == 1 and opener in "([" and t.value == closer:
            return Paren(items[0], opener, closer)
        if len(items) == 1 and opener != "{":
            raise MathReadError("mismatched brackets")
        return Seq(opener, t.value, tuple(items))


def parse(text: str) -> Node:
    """The keyboard form as a tree. Raises :class:`MathReadError` on anything unreadable."""
    if not text.strip():
        raise MathReadError("empty")
    try:
        node = _Parser(_tokenize(text)).parse()
    except RecursionError as exc:
        raise MathReadError("too deep") from exc
    except ValueError as exc:
        if isinstance(exc, MathReadError):
            raise
        raise MathReadError(str(exc)) from exc
    return node


# ---------------------------------------------------------------------------
# LaTeX out
# ---------------------------------------------------------------------------

_LATEX_SYM = {
    "pi": "\\pi ",
    "inf": "\\infty ",
    "alpha": "\\alpha ",
    "beta": "\\beta ",
    "gamma": "\\gamma ",
    "delta": "\\delta ",
    "theta": "\\theta ",
    "lambda": "\\lambda ",
    "sigma": "\\sigma ",
    "omega": "\\omega ",
    "phi": "\\phi ",
    "rho": "\\rho ",
    "tau": "\\tau ",
}
_LATEX_REL = {"=": "=", "<": "<", "<=": "\\le ", ">": ">", ">=": "\\ge ", "!=": "\\ne "}
_LATEX_FN = {
    "sin": "\\sin",
    "cos": "\\cos",
    "tan": "\\tan",
    "sec": "\\sec",
    "csc": "\\csc",
    "cot": "\\cot",
    "arcsin": "\\arcsin",
    "arccos": "\\arccos",
    "arctan": "\\arctan",
    "ln": "\\ln",
    "log": "\\log",
    "exp": "\\exp",
}


def _bare(node: Node) -> Node:
    while isinstance(node, Paren):
        node = node.arg
    return node


def to_latex(node: Node) -> str:
    """The tree as LaTeX for MathJax, in the order the answer was written."""
    return _tex(node).strip()


def _tex(node: Node) -> str:
    if isinstance(node, Num):
        return node.text
    if isinstance(node, Sym):
        if node.name in _LATEX_SYM:
            return _LATEX_SYM[node.name]
        letter, _, sub = node.name.partition("_")
        return f"{letter}_{{{sub}}}" if sub else letter
    if isinstance(node, Neg):
        return "-" + _tex_operand(node.arg)
    if isinstance(node, PM):
        return "\\pm " + _tex_operand(node.arg)
    if isinstance(node, Add):
        out = _tex(node.terms[0])
        for term in node.terms[1:]:
            if isinstance(term, Neg):
                out += " - " + _tex_operand(term.arg)
            elif isinstance(term, PM):
                out += " \\pm " + _tex_operand(term.arg)
            else:
                out += " + " + _tex(term)
        return out
    if isinstance(node, Mul):
        out = _tex_factor(node.factors[0])
        for k, f in enumerate(node.factors[1:]):
            out += ("\\cdot " if node.explicit[k] else " ") + _tex_factor(f)
        return out
    if isinstance(node, Div):
        return f"\\frac{{{_tex(_bare(node.num))}}}{{{_tex(_bare(node.den))}}}"
    if isinstance(node, Pow):
        return f"{_tex_base(node.base)}^{{{_tex(_bare(node.exp))}}}"
    if isinstance(node, Fn):
        return _tex_fn(node)
    if isinstance(node, Paren):
        if not node.open:
            return _tex(node.arg)
        return f"\\left{node.open} {_tex(node.arg)} \\right{node.close}"
    if isinstance(node, Seq):
        body = ",\\, ".join(_tex(i) for i in node.items)
        if not node.open:
            return body
        o = "\\{" if node.open == "{" else node.open
        c = "\\}" if node.close == "}" else node.close
        return f"\\left{o} {body} \\right{c}"
    if isinstance(node, Rel):
        out = _tex(node.operands[0])
        for op, operand in zip(node.ops, node.operands[1:], strict=True):
            out += f" {_LATEX_REL[op]} " + _tex(operand)
        return out
    return " \\cup ".join(_tex(p) for p in node.parts)


def _tex_operand(node: Node) -> str:
    """After a sign: a sum needs its parentheses (they are in the tree already)."""
    return _tex(node)


def _tex_factor(node: Node) -> str:
    if isinstance(node, Neg | PM | Add):
        return f"\\left( {_tex(node)} \\right)"
    return _tex(node)


def _tex_base(node: Node) -> str:
    inner = node.arg if isinstance(node, Paren) and not node.open else node
    if isinstance(inner, Num | Sym | Fn | Seq) or (isinstance(inner, Paren) and inner.open):
        return _tex(inner)
    return f"\\left( {_tex(inner)} \\right)"


def _tex_fn(node: Fn) -> str:
    arg = _tex(_bare(node.args[0]))
    if node.name == "sqrt":
        return f"\\sqrt{{{arg}}}"
    if node.name == "abs":
        return f"\\left| {arg} \\right|"
    if node.name == "root":
        return f"\\sqrt[{_tex(_bare(node.args[1]))}]{{{arg}}}"
    return f"{_LATEX_FN[node.name]}\\left( {arg} \\right)"


# ---------------------------------------------------------------------------
# LaTeX in: the palette's MathLive value -> the keyboard form
# ---------------------------------------------------------------------------

_LTX_TOKEN_RE = re.compile(r"\\([A-Za-z]+|.)|(.)", re.DOTALL)

_LTX_SPACES = frozenset(
    {",", ";", ":", "!", " ", "quad", "qquad", "hspace", "relax", "displaystyle"}
)
_LTX_PLAIN: dict[str, str] = {
    "pm": "+-",
    "cdot": "*",
    "times": "*",
    "div": "/",
    "le": "<=",
    "leq": "<=",
    "leqslant": "<=",
    "ge": ">=",
    "geq": ">=",
    "geqslant": ">=",
    "ne": "!=",
    "neq": "!=",
    "lt": "<",
    "gt": ">",
    "cup": "∪",
    "lbrack": "[",
    "rbrack": "]",
    "lbrace": "{",
    "rbrace": "}",
    "{": "{",
    "}": "}",
    "pi": " pi ",
    "infty": " inf ",
    "infinity": " inf ",
    "lparen": "(",
    "rparen": ")",
}
_LTX_NAMES = {n: f" {n} " for n in _GREEK if n.isascii()}
_LTX_FUNCTIONS = {
    "sin",
    "cos",
    "tan",
    "sec",
    "csc",
    "cot",
    "arcsin",
    "arccos",
    "arctan",
    "ln",
    "log",
    "exp",
}
_LTX_ABS = {"|", "vert", "lvert", "rvert"}
_LTX_CHARS = frozenset("0123456789.+-*/=<>()[],;")


class _Latex:
    def __init__(self, source: str) -> None:
        self.toks: list[tuple[str, str]] = []  # ("cmd" | "char", value)
        for m in _LTX_TOKEN_RE.finditer(source):
            if m.group(1) is not None:
                self.toks.append(("cmd", m.group(1)))
            else:
                self.toks.append(("char", m.group(2)))
        self.i = 0
        self.abs_open = False

    def peek(self) -> tuple[str, str] | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> tuple[str, str]:
        t = self.peek()
        if t is None:
            raise MathReadError("unexpected end")
        self.i += 1
        return t

    def sequence(self, until_brace: bool) -> str:
        out: list[str] = []
        while True:
            t = self.peek()
            if t is None:
                if until_brace:
                    raise MathReadError("missing }")
                break
            if t == ("char", "}"):
                if not until_brace:
                    raise MathReadError("stray }")
                self.i += 1
                break
            out.append(self.item())
        return "".join(out)

    def group(self) -> str:
        """One LaTeX argument: ``{...}`` or a single token, as an invisible group."""
        t = self.peek()
        if t == ("char", "{"):
            self.i += 1
            return INVISIBLE_OPEN + self.sequence(True) + INVISIBLE_CLOSE
        if t is None or t == ("char", "}"):
            raise MathReadError("missing argument")
        return INVISIBLE_OPEN + self.item() + INVISIBLE_CLOSE

    def raw_group(self) -> str:
        """The text of a ``{...}`` of letters and digits (names, subscripts)."""
        if self.peek() != ("char", "{"):
            kind, value = self.take()
            if kind != "char" or not value.isalnum():
                raise MathReadError("bad name")
            return value
        self.i += 1
        out: list[str] = []
        while True:
            kind, value = self.take()
            if (kind, value) == ("char", "}"):
                break
            if kind == "cmd" and value in _LTX_SPACES:
                continue
            if kind != "char" or not (value.isalnum() or value in "+-"):
                raise MathReadError("bad name")
            out.append(value)
        return "".join(out)

    def item(self) -> str:
        kind, value = self.take()
        if kind == "char":
            return self._char(value)
        return self._command(value)

    def _char(self, ch: str) -> str:
        if ch == "{":
            return INVISIBLE_OPEN + self.sequence(True) + INVISIBLE_CLOSE
        if ch == "^":
            return "^" + self.group()
        if ch == "_":
            return "_{" + self.raw_group() + "}"
        if ch == "|":
            return self._abs()
        if ch in (" ", "\t", "\n", "~"):
            return ""
        if ch in _LTX_CHARS or ch.isalnum() or ch in "−±":
            return ch
        raise MathReadError(f"unexpected {ch!r}")

    def _abs(self) -> str:
        self.abs_open = not self.abs_open
        return "abs(" if self.abs_open else ")"

    def _command(self, name: str) -> str:
        if name in _LTX_SPACES:
            return ""
        if name in ("frac", "dfrac", "tfrac"):
            num = self.group()
            den = self.group()
            return f"{INVISIBLE_OPEN}{num}/{den}{INVISIBLE_CLOSE}"
        if name == "sqrt":
            if self.peek() == ("char", "["):
                self.i += 1
                index: list[str] = []
                while self.peek() != ("char", "]"):
                    index.append(self.item())
                self.i += 1
                return f"root({self.group()},{''.join(index)})"
            return f"sqrt({self.group()})"
        if name in ("left", "right"):
            return self._delimiter()
        if name in _LTX_ABS:
            return self._abs()
        if name in _LTX_PLAIN:
            return _LTX_PLAIN[name]
        if name in _LTX_NAMES:
            return _LTX_NAMES[name]
        if name in ("mathrm", "operatorname", "text", "mathit", "mathbf"):
            return " " + "".join(c for c in self.raw_group() if c.isalnum()) + " "
        if name in _LTX_FUNCTIONS:
            if self.peek() in (("char", "("), ("cmd", "left")):
                return name
            raise MathReadError(f"{name} needs parentheses")
        raise MathReadError(f"unsupported \\{name}")

    def _delimiter(self) -> str:
        kind, value = self.take()
        if kind == "cmd" and value in _LTX_ABS:
            return self._abs()
        if kind == "cmd" and value in ("lbrace", "{"):
            return "{"
        if kind == "cmd" and value in ("rbrace", "}"):
            return "}"
        if kind == "cmd" and value in ("lbrack", "rbrack", "lparen", "rparen"):
            return _LTX_PLAIN[value]
        if kind == "char" and value in "()[]":
            return value
        if kind == "char" and value == "|":
            return self._abs()
        raise MathReadError("unsupported delimiter")


def latex_to_keyboard(latex: str) -> str:
    """The palette's MathLive LaTeX as the keyboard form :func:`parse` reads.

    Raises :class:`MathReadError` on a placeholder, an unfinished fraction or any
    LaTeX outside what the palette makes."""
    if "placeholder" in latex:
        raise MathReadError("unfinished")
    reader = _Latex(latex)
    out = reader.sequence(False)
    if reader.peek() is not None:
        raise MathReadError("stray \\right")
    if reader.abs_open:
        raise MathReadError("unclosed |")
    return out
