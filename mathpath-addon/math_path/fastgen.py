"""A quick exact pre-filter for the checker's parameter draw (pure, no SymPy).

``recipe_validator.instance`` draws parameters, derives the recipe's ``let`` values with SymPy
and checks every constraint with SymPy, retrying until all hold. For a recipe with tight
constraints (``ca.rateq.solve_quadratic`` rejects most draws) the retries cost seconds, nearly all
of it in SymPy's parser.

:func:`rejects` evaluates the constraints with Python fractions first and says ``True`` only when
a constraint is *certainly* false. Anything it can't evaluate exactly (``expand``, irrational
square roots, the variable) counts as "unknown" and is never rejected here, so the checker still
makes every final decision: this module only skips draws the checker would have rejected
anyway, and the draw sequence (and so the instance for a given seed) is unchanged.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import dataclass
from fractions import Fraction

_TOKEN = re.compile(
    r"\s*(?:(?P<num>\d+(?:\.\d+)?)|(?P<name>[A-Za-z_][A-Za-z_0-9]*)|(?P<op>\*\*|[-+*/^(),]))"
)
_COMPARE = re.compile(r"(.+?)\s*(==|!=|<=|>=|<|>)\s*(.+)")
_FUNCTIONS = frozenset({"floor", "abs", "gcd", "sqrt"})


class _Unknown(Exception):
    """The expression can't be evaluated exactly here."""


@dataclass(frozen=True)
class _Tok:
    kind: str
    text: str


def _tokens(s: str) -> list[_Tok]:
    out: list[_Tok] = []
    pos = 0
    s = s.strip()
    while pos < len(s):
        m = _TOKEN.match(s, pos)
        if m is None or m.end() == pos:
            raise _Unknown(s[pos:])
        pos = m.end()
        for kind in ("num", "name", "op"):
            if m.group(kind) is not None:
                out.append(_Tok(kind, m.group(kind)))
    return out


@dataclass(frozen=True)
class Num:
    value: Fraction


@dataclass(frozen=True)
class Name:
    name: str


@dataclass(frozen=True)
class Neg:
    arg: Node


@dataclass(frozen=True)
class Bin:
    op: str
    left: Node
    right: Node


@dataclass(frozen=True)
class Call:
    name: str
    args: tuple[Node, ...]


Node = Num | Name | Neg | Bin | Call


class _Parser:
    def __init__(self, toks: list[_Tok]) -> None:
        self.toks = toks
        self.i = 0

    def peek(self) -> _Tok | None:
        return self.toks[self.i] if self.i < len(self.toks) else None

    def take(self) -> _Tok:
        t = self.peek()
        if t is None:
            raise _Unknown("end")
        self.i += 1
        return t

    def expr(self) -> Node:
        node = self.term()
        while (t := self.peek()) is not None and t.text in ("+", "-"):
            self.take()
            node = Bin(t.text, node, self.term())
        return node

    def term(self) -> Node:
        node = self.unary()
        while (t := self.peek()) is not None:
            if t.text in ("*", "/"):
                self.take()
                node = Bin(t.text, node, self.unary())
            elif t.kind in ("num", "name") or t.text == "(":
                node = Bin("*", node, self.unary())  # juxtaposition: 2a, C (r1 + r2)
            else:
                break
        return node

    def unary(self) -> Node:
        t = self.peek()
        if t is not None and t.text == "-":
            self.take()
            return Neg(self.unary())
        if t is not None and t.text == "+":
            self.take()
            return self.unary()
        return self.power()

    def power(self) -> Node:
        base = self.atom()
        t = self.peek()
        if t is not None and t.text in ("^", "**"):
            self.take()
            return Bin("^", base, self.unary())
        return base

    def atom(self) -> Node:
        t = self.take()
        if t.kind == "num":
            return Num(Fraction(t.text))
        if t.kind == "name":
            nxt = self.peek()
            if t.text in _FUNCTIONS and nxt is not None and nxt.text == "(":
                self.take()
                args = [self.expr()]
                while (c := self.peek()) is not None and c.text == ",":
                    self.take()
                    args.append(self.expr())
                if self.take().text != ")":
                    raise _Unknown("call")
                return Call(t.text, tuple(args))
            return Name(t.text)
        if t.text == "(":
            node = self.expr()
            if self.take().text != ")":
                raise _Unknown("paren")
            return node
        raise _Unknown(t.text)


def _parse(s: str) -> Node:
    p = _Parser(_tokens(s))
    node = p.expr()
    if p.peek() is not None:
        raise _Unknown("trailing")
    return node


def _isqrt_floor(v: Fraction) -> int:
    if v < 0:
        raise _Unknown("sqrt of a negative")
    return math.isqrt(v.numerator // v.denominator)


def _exact_sqrt(v: Fraction) -> Fraction:
    if v < 0:
        raise _Unknown("sqrt of a negative")
    n, d = math.isqrt(v.numerator), math.isqrt(v.denominator)
    if n * n == v.numerator and d * d == v.denominator:
        return Fraction(n, d)
    raise _Unknown("irrational")


def _eval(node: Node, env: Mapping[str, Fraction]) -> Fraction:
    if isinstance(node, Num):
        return node.value
    if isinstance(node, Name):
        if node.name not in env:
            raise _Unknown(node.name)
        return env[node.name]
    if isinstance(node, Neg):
        return -_eval(node.arg, env)
    if isinstance(node, Bin):
        a = _eval(node.left, env)
        b = _eval(node.right, env)
        if node.op == "+":
            return a + b
        if node.op == "-":
            return a - b
        if node.op == "*":
            return a * b
        if node.op == "/":
            if b == 0:
                raise _Unknown("division by zero")
            return a / b
        if b.denominator != 1 or abs(b) > 64:
            raise _Unknown("exponent")
        if a == 0 and b < 0:
            raise _Unknown("zero to a negative power")
        return a ** int(b)
    args = node.args
    if node.name == "floor" and len(args) == 1:
        inner = args[0]
        if isinstance(inner, Call) and inner.name == "sqrt" and len(inner.args) == 1:
            # floor(sqrt(v)) without leaving the integers
            return Fraction(_isqrt_floor(_eval(inner.args[0], env)))
        v = _eval(inner, env)
        return Fraction(v.numerator // v.denominator)
    if node.name == "abs" and len(args) == 1:
        return abs(_eval(args[0], env))
    if node.name == "sqrt" and len(args) == 1:
        return _exact_sqrt(_eval(args[0], env))
    if node.name == "gcd" and len(args) == 2:
        a, b = _eval(args[0], env), _eval(args[1], env)
        if a.denominator != 1 or b.denominator != 1:
            raise _Unknown("gcd of a fraction")
        return Fraction(math.gcd(int(a), int(b)))
    raise _Unknown(node.name)


@dataclass(frozen=True)
class Prefilter:
    """The recipe's ``let`` values and constraints, parsed once."""

    lets: tuple[tuple[str, Node | None], ...]
    constraints: tuple[tuple[Node, str, Node] | None, ...]

    @classmethod
    def for_recipe(cls, params_let: Mapping[str, str], constraints: list[str]) -> Prefilter:
        lets: list[tuple[str, Node | None]] = []
        for name, text in params_let.items():
            try:
                lets.append((name, _parse(text)))
            except _Unknown:
                lets.append((name, None))
        parsed: list[tuple[Node, str, Node] | None] = []
        for c in constraints:
            m = _COMPARE.fullmatch(c.strip())
            if m is None:
                parsed.append(None)
                continue
            try:
                parsed.append((_parse(m.group(1)), m.group(2), _parse(m.group(3))))
            except _Unknown:
                parsed.append(None)
        return cls(tuple(lets), tuple(parsed))

    def rejects(self, params: Mapping[str, Fraction]) -> bool:
        """True when some constraint is certainly false for these parameter values."""
        env = dict(params)
        for name, node in self.lets:
            if node is None:
                env.pop(name, None)
                continue
            try:
                env[name] = _eval(node, env)
            except _Unknown:
                env.pop(name, None)
        for c in self.constraints:
            if c is None:
                continue
            lhs, op, rhs = c
            try:
                a, b = _eval(lhs, env), _eval(rhs, env)
            except _Unknown:
                continue
            holds = {
                "==": a == b,
                "!=": a != b,
                "<": a < b,
                "<=": a <= b,
                ">": a > b,
                ">=": a >= b,
            }[op]
            if not holds:
                return True
        return False
