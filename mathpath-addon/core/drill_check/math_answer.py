"""Checking a typed math answer against a card's ``MathAnswer`` (pure, no Qt).

The default is **same form, any order**: the typed answer is right when it parses
to the same expression tree as the card's, up to the order of sums and products,
flattening, and trivial differences (spacing, ``2a`` for ``2*a``, ``y2`` for
``y_2``, the minus sign, redundant outer parentheses). Equations and inequalities
may have their sides swapped. ``+-`` stands for both branches, so one branch is
wrong. Intervals compare endpoints and bracket types.

An answer that is *equivalent* (``a^2-b^2`` for ``(a+b)(a-b)``) but written in
another form is **wrong** with "Equivalent, but this card wants: ...", unless the
card has the tag ``rd::math::equiv``: then equivalent counts as right. Equivalence
is ``simplify(a - b) == 0`` (the vendored SymPy, imported on first use) plus a
numeric spot check at random points; equations and inequalities compare by
``lhs - rhs`` up to a constant factor.

The engine is not touched. ``engine_target`` is what the item's ``back`` holds (no
spaces, no ``,`` or ``;``, so the engine never chunks it or splits it as a list),
and :func:`engine_typed` is what ``submit`` hands the engine: the target itself
when the check says right, else a string that can never grade right or near.
"""

from __future__ import annotations

import cmath
import math
import random
import re
from collections.abc import Callable
from dataclasses import dataclass
from fractions import Fraction
from typing import Any, Literal

from . import math_vendor
from .math_parse import (
    PM,
    Add,
    Div,
    Fn,
    MathReadError,
    Mul,
    Neg,
    Node,
    Num,
    Paren,
    Pow,
    Rel,
    Seq,
    Sym,
    Union,
    latex_to_keyboard,
    parse,
    to_latex,
)

__all__ = [
    "READ_MESSAGE",
    "WRONG_MESSAGE",
    "MathCheck",
    "MathReadError",
    "check_answer",
    "engine_target",
    "engine_typed",
    "keyboard_from_palette",
    "latex_of",
    "usable_target",
]

READ_MESSAGE = "Couldn't read that as math"
WRONG_MESSAGE = "Not the same expression"
EQUIVALENT_PREFIX = "Equivalent, but this card wants: "

Outcome = Literal["right", "equivalent", "wrong", "unreadable"]


@dataclass(frozen=True)
class MathCheck:
    outcome: Outcome
    right: bool
    """Counts as right (``outcome == "right"``)."""
    message: str
    """"" when right; else what to tell the learner. May hold ``\\(...\\)`` for MathJax."""
    typed_latex: str | None
    """The typed answer as LaTeX, or None when it couldn't be read."""
    target_latex: str
    """The card's answer as LaTeX ("" if the target itself can't be read)."""


# ---------------------------------------------------------------------------
# Engine strings
# ---------------------------------------------------------------------------

_COMMA = ""
_SEMICOLON = ""
_WS = re.compile(r"\s+")
WRONG_MARK = "wrong"
"""Prefix of what the engine gets for a wrong answer: letters, so the engine's own
normalisation keeps it, and no stopword, so it is never "near"."""


def engine_target(answer: str) -> str:
    """The item's ``back`` for a math card: the answer with no whitespace and no
    ``,`` or ``;`` (replaced by private-use characters), so the engine sees one
    word, never chunks it and never splits it as a list."""
    return _WS.sub("", answer).replace(",", _COMMA).replace(";", _SEMICOLON)


def engine_typed(typed: str, check: MathCheck, target: str) -> str:
    """What ``submit`` passes the engine: ``target`` (the trial's engine target) when
    the check says right, else the typed answer in the engine's one-word form behind
    :data:`WRONG_MARK`, which never grades right or near."""
    if check.right:
        return target
    return WRONG_MARK + engine_target(typed)


# ---------------------------------------------------------------------------
# Canonical form: the same-form comparison
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _K:
    """A canonical node: ``key`` identifies it, ``value`` is set for a number."""

    key: str
    value: Fraction | None = None
    parts: tuple[_K, ...] = ()
    kind: str = ""


def _num(v: Fraction) -> _K:
    return _K(f"n:{v}", v, (), "num")


def _flat(kind: str, items: list[_K]) -> list[_K]:
    out: list[_K] = []
    for k in items:
        out.extend(k.parts if k.kind == kind else [k])
    return out


def _add(items: list[_K]) -> _K:
    rest = _flat("add", items)
    rest.sort(key=lambda k: k.key)
    if len(rest) == 1:
        return rest[0]
    return _K("a:(" + "+".join(k.key for k in rest) + ")", None, tuple(rest), "add")


def _mul(items: list[_K]) -> _K:
    coeff = Fraction(1)
    rest: list[_K] = []
    for k in _flat("mul", items):
        if k.value is not None:
            coeff *= k.value
        else:
            rest.append(k)
    if coeff == 0:
        return _num(Fraction(0))
    if not rest:
        return _num(coeff)
    rest.sort(key=lambda k: k.key)
    if coeff == 1 and len(rest) == 1:
        return rest[0]
    return _K(f"m:({coeff}*" + "*".join(k.key for k in rest) + ")", None, tuple(rest), "mul")


def _exact_root(v: Fraction, n: int) -> Fraction | None:
    if v < 0:
        return None

    def root(x: int) -> int | None:
        r = round(x ** (1 / n))
        return next((c for c in (r - 1, r, r + 1) if c >= 0 and c**n == x), None)

    a, b = root(v.numerator), root(v.denominator)
    return Fraction(a, b) if a is not None and b else None


def _inv(k: _K) -> _K:
    if k.value is not None and k.value != 0:
        return _num(1 / k.value)
    return _pow(k, _num(Fraction(-1)))


def _pow(base: _K, exp: _K) -> _K:
    if exp.value == 1:
        return base
    if exp.value == 0:
        return _num(Fraction(1))
    if base.value is not None and exp.value is not None:
        e = exp.value
        if e.denominator == 1 and abs(e) <= 64 and (base.value != 0 or e > 0):
            return _num(base.value ** int(e))
        if e.numerator == 1 and e.denominator in (2, 3):
            root = _exact_root(base.value, e.denominator)
            if root is not None:
                return _num(root)
    return _K(f"p:({base.key}^{exp.key})", None, (base, exp), "pow")


def _canon(node: Node) -> _K:
    if isinstance(node, Num):
        return _num(node.value)
    if isinstance(node, Sym):
        return _K(f"s:{node.name}", None, (), "sym")
    if isinstance(node, Paren):
        return _canon(node.arg)
    if isinstance(node, Neg):
        return _mul([_num(Fraction(-1)), _canon(node.arg)])
    if isinstance(node, Add):
        return _add([_canon(t) for t in node.terms])
    if isinstance(node, Mul):
        return _mul([_canon(f) for f in node.factors])
    if isinstance(node, Div):
        return _mul([_canon(node.num), _inv(_canon(node.den))])
    if isinstance(node, Pow):
        return _pow(_canon(node.base), _canon(node.exp))
    if isinstance(node, Fn):
        return _canon_fn(node)
    if isinstance(node, Seq):
        items = [_canon(i) for i in node.items]
        if node.open in ("{", ""):  # a set or a plain list: no order
            items = sorted({i.key: i for i in items}.values(), key=lambda k: k.key)
        key = f"q:{node.open}{'|'.join(i.key for i in items)}{node.close}"
        return _K(key, None, tuple(items), "seq")
    if isinstance(node, Rel):
        return _canon_rel(node)
    if isinstance(node, Union):
        parts = _flat("union", [_canon(p) for p in node.parts])
        parts = sorted({p.key: p for p in parts}.values(), key=lambda k: k.key)
        if len(parts) == 1:
            return parts[0]
        return _K("u:(" + "|".join(p.key for p in parts) + ")", None, tuple(parts), "union")
    raise MathReadError("a +- sign in the wrong place")


def _canon_fn(node: Fn) -> _K:
    arg = _canon(node.args[0])
    if node.name == "sqrt":
        return _pow(arg, _num(Fraction(1, 2)))
    if node.name == "root":
        return _pow(arg, _inv(_canon(node.args[1])))
    return _K(f"f:{node.name}({arg.key})", None, (arg,), "fn")


_FLIP = {">": "<", ">=": "<="}


def _normal_rel(rel: Rel) -> tuple[tuple[str, ...], list[Node]]:
    """The relation with ``>``/``>=`` turned around so ``x<=5`` and ``5>=x`` agree."""
    ops, operands = rel.ops, list(rel.operands)
    if all(op in _FLIP for op in ops):
        return tuple(_FLIP[op] for op in reversed(ops)), operands[::-1]
    return ops, operands


def _canon_rel(rel: Rel) -> _K:
    ops, operands = _normal_rel(rel)
    items = [_canon(o) for o in operands]
    if all(op in ("=", "!=") for op in ops) and len(set(ops)) == 1:
        items.sort(key=lambda k: k.key)
    key = "r:" + "".join(f"[{k.key}]{op}" for k, op in zip(items, (*ops, ""), strict=True))
    return _K(key, None, tuple(items), "rel")


_MAX_BRANCHES = 64


def _expand(node: Node) -> list[Node]:
    """Every branch of a tree with ``+-`` in it (independent signs); [node] without."""
    out = _expand_inner(node)
    if len(out) > _MAX_BRANCHES:
        raise MathReadError("too many +- signs")
    return out


def _product(lists: list[list[Node]]) -> list[tuple[Node, ...]]:
    combos: list[tuple[Node, ...]] = [()]
    for options in lists:
        combos = [c + (o,) for c in combos for o in options]
        if len(combos) > _MAX_BRANCHES:
            raise MathReadError("too many +- signs")
    return combos


def _expand_inner(node: Node) -> list[Node]:
    if isinstance(node, Num | Sym):
        return [node]
    if isinstance(node, PM):
        inner = _expand_inner(node.arg)
        return [*inner, *[Neg(a) for a in inner]]
    if isinstance(node, Neg):
        return [Neg(a) for a in _expand_inner(node.arg)]
    if isinstance(node, Paren):
        return [Paren(a, node.open, node.close) for a in _expand_inner(node.arg)]
    if isinstance(node, Add):
        return [Add(c) for c in _product([_expand_inner(t) for t in node.terms])]
    if isinstance(node, Mul):
        return [Mul(c, node.explicit) for c in _product([_expand_inner(f) for f in node.factors])]
    if isinstance(node, Div):
        return [Div(a, b) for a, b in _product([_expand_inner(node.num), _expand_inner(node.den)])]
    if isinstance(node, Pow):
        return [Pow(a, b) for a, b in _product([_expand_inner(node.base), _expand_inner(node.exp)])]
    if isinstance(node, Fn):
        return [Fn(node.name, c) for c in _product([_expand_inner(a) for a in node.args])]
    if isinstance(node, Seq):
        return [
            Seq(node.open, node.close, c) for c in _product([_expand_inner(i) for i in node.items])
        ]
    if isinstance(node, Rel):
        return [Rel(c, node.ops) for c in _product([_expand_inner(o) for o in node.operands])]
    return [Union(c) for c in _product([_expand_inner(p) for p in node.parts])]


def _form(node: Node) -> frozenset[str]:
    """The answer's form: one canonical key per ``+-`` branch."""
    return frozenset(_canon(b).key for b in _expand(node))


# ---------------------------------------------------------------------------
# Equivalence: numeric spot check plus SymPy
# ---------------------------------------------------------------------------


class _BadPoint(Exception):
    """The expression has no value at this sample point (division by zero, a pole)."""


class _NoValue(Exception):
    """The expression can't be evaluated numerically (infinity, a set)."""


_CONSTANTS = {"pi": math.pi, "i": 1j}


def _sec(z: complex) -> complex:
    return 1 / cmath.cos(z)


def _csc(z: complex) -> complex:
    return 1 / cmath.sin(z)


def _cot(z: complex) -> complex:
    return 1 / cmath.tan(z)


_FUNCS: dict[str, Callable[[complex], complex | float]] = {
    "sin": cmath.sin,
    "cos": cmath.cos,
    "tan": cmath.tan,
    "sec": _sec,
    "csc": _csc,
    "cot": _cot,
    "arcsin": cmath.asin,
    "arccos": cmath.acos,
    "arctan": cmath.atan,
    "ln": cmath.log,
    "log": cmath.log10,
    "exp": cmath.exp,
    "abs": abs,
    "sqrt": cmath.sqrt,
}


def _eval(node: Node, env: dict[str, complex]) -> complex:
    if isinstance(node, Num):
        return complex(node.value)
    if isinstance(node, Sym):
        if node.name == "inf":
            raise _NoValue
        if node.name in _CONSTANTS:
            return complex(_CONSTANTS[node.name])
        return env[node.name]
    if isinstance(node, Paren):
        return _eval(node.arg, env)
    if isinstance(node, Neg):
        return -_eval(node.arg, env)
    if isinstance(node, Add):
        return sum((_eval(t, env) for t in node.terms), 0j)
    if isinstance(node, Mul):
        out = 1 + 0j
        for f in node.factors:
            out *= _eval(f, env)
        return out
    try:
        return _eval_compound(node, env)
    except (ZeroDivisionError, OverflowError, ValueError) as exc:
        raise _BadPoint from exc


def _eval_compound(node: Node, env: dict[str, complex]) -> complex:
    if isinstance(node, Div):
        return _eval(node.num, env) / _eval(node.den, env)
    if isinstance(node, Pow):
        base, exp = _eval(node.base, env), _eval(node.exp, env)
        if base == 0 and exp.real <= 0:
            raise ZeroDivisionError
        if exp.imag == 0 and exp.real == int(exp.real) and abs(exp.real) <= 64:
            return base ** int(exp.real)
        return base**exp
    if isinstance(node, Fn):
        if node.name == "root":
            return _eval(node.args[0], env) ** (1 / _eval(node.args[1], env))
        return complex(_FUNCS[node.name](_eval(node.args[0], env)))
    raise _NoValue


def _names(node: Node) -> set[str]:
    """Every symbol name in the tree (constants included)."""
    out: set[str] = set()
    if isinstance(node, Sym):
        out.add(node.name)
    elif isinstance(node, Neg | PM | Paren):
        out |= _names(node.arg)
    elif isinstance(node, Add):
        out.update(*(_names(t) for t in node.terms))
    elif isinstance(node, Mul):
        out.update(*(_names(f) for f in node.factors))
    elif isinstance(node, Div):
        out |= _names(node.num) | _names(node.den)
    elif isinstance(node, Pow):
        out |= _names(node.base) | _names(node.exp)
    elif isinstance(node, Fn):
        out.update(*(_names(a) for a in node.args))
    return out


def _has_inf(node: Node) -> bool:
    return "inf" in _names(node)


_POINTS = 12
_NEEDED = 4


def _samples(names: list[str]) -> list[dict[str, complex]]:
    rng = random.Random(0x5EED)
    pts: list[dict[str, complex]] = []
    for _ in range(_POINTS):
        pts.append(
            {
                n: complex(rng.choice((-1, 1)) * rng.choice((0.5, 1, 1.5, 2, 2.5, 3, 3.5, 4.25)))
                + rng.random() * 0.37
                for n in names
            }
        )
    return pts


def _values(a: Node, b: Node) -> list[tuple[complex, complex]] | None:
    """(a, b) at the sample points where both have a value; None if one can't be evaluated."""
    syms = (_names(a) | _names(b)) - set(_CONSTANTS) - {"inf"}
    pairs: list[tuple[complex, complex]] = []
    try:
        for env in _samples(sorted(syms)):
            try:
                pairs.append((_eval(a, env), _eval(b, env)))
            except _BadPoint:
                continue
    except _NoValue:
        return None
    return pairs


def _close(u: complex, v: complex) -> bool:
    return abs(u - v) <= 1e-7 * max(1.0, abs(u), abs(v))


def _to_sympy(node: Node, sp: Any) -> Any:
    if isinstance(node, Num):
        return sp.Rational(node.value.numerator, node.value.denominator)
    if isinstance(node, Sym):
        if node.name == "pi":
            return sp.pi
        if node.name == "i":
            return sp.I
        if node.name == "inf":
            return sp.oo
        return sp.Symbol(node.name)
    if isinstance(node, Paren):
        return _to_sympy(node.arg, sp)
    if isinstance(node, Neg):
        return -_to_sympy(node.arg, sp)
    if isinstance(node, Add):
        return sp.Add(*[_to_sympy(t, sp) for t in node.terms])
    if isinstance(node, Mul):
        return sp.Mul(*[_to_sympy(f, sp) for f in node.factors])
    if isinstance(node, Div):
        return _to_sympy(node.num, sp) / _to_sympy(node.den, sp)
    if isinstance(node, Pow):
        return _to_sympy(node.base, sp) ** _to_sympy(node.exp, sp)
    if isinstance(node, Fn):
        arg = _to_sympy(node.args[0], sp)
        if node.name == "root":
            return arg ** (1 / _to_sympy(node.args[1], sp))
        if node.name == "log":
            return sp.log(arg, 10)
        name = {"abs": "Abs", "ln": "log", "arcsin": "asin", "arccos": "acos", "arctan": "atan"}
        return getattr(sp, name.get(node.name, node.name))(arg)
    raise MathReadError("not an expression")


_SIMPLIFY_LIMIT = 300


def _simplifies_to_zero(a: Node, b: Node) -> bool | None:
    """``simplify(a - b) == 0`` with the vendored SymPy; None if it can't say."""
    sp = math_vendor.sympy()
    if sp is None:
        return None
    try:
        diff = _to_sympy(a, sp) - _to_sympy(b, sp)
        if sp.count_ops(diff) > _SIMPLIFY_LIMIT:
            return None
        return bool(sp.simplify(diff) == 0)
    except Exception:  # SymPy raising on an odd tree must not break a drill
        return None


def _expr_equal(a: Node, b: Node) -> bool:
    """Equal as functions: the numeric spot check agrees, and ``simplify(a - b)`` is 0
    (or SymPy can't say and enough sample points agreed)."""
    if _has_inf(a) or _has_inf(b):
        return _canon(a).key == _canon(b).key
    pairs = _values(a, b)
    if pairs is None:
        return False
    if pairs and not all(_close(u, v) for u, v in pairs):
        return False
    zero = _simplifies_to_zero(a, b)
    if zero is not None:
        return zero or len(pairs) >= _NEEDED
    return len(pairs) >= _NEEDED


def _ratio(a: Node, b: Node) -> float | None:
    """The constant ``k`` with ``a == k * b`` at every sample point, or None."""
    pairs = _values(a, b)
    if pairs is None or len(pairs) < _NEEDED:
        return None
    ks: list[complex] = []
    for u, v in pairs:
        if abs(v) < 1e-9:
            if abs(u) < 1e-9:
                continue
            return None
        ks.append(u / v)
    if not ks or not all(_close(ks[0], k) for k in ks) or abs(ks[0].imag) > 1e-9:
        return None
    return ks[0].real if abs(ks[0]) > 1e-9 else None


def _side_diff(operands: list[Node]) -> Node:
    """``right - left`` of a two-sided relation (after turning it around)."""
    return Add((operands[1], Neg(Paren(operands[0], "(", ")"))))


def _equivalent(a: Node, b: Node) -> bool:
    """Equivalent (not just the same form), for ``+-``-free trees."""
    if isinstance(a, Rel) or isinstance(b, Rel):
        return isinstance(a, Rel) and isinstance(b, Rel) and _rel_equivalent(a, b)
    if isinstance(a, Seq) or isinstance(b, Seq):
        return isinstance(a, Seq) and isinstance(b, Seq) and _seq_equivalent(a, b)
    if isinstance(a, Union) or isinstance(b, Union):
        return isinstance(a, Union) and isinstance(b, Union) and _match(a.parts, b.parts)
    return _expr_equal(a, b)


def _rel_equivalent(a: Rel, b: Rel) -> bool:
    ops_a, xs = _normal_rel(a)
    ops_b, ys = _normal_rel(b)
    if ops_a != ops_b or len(xs) != len(ys):
        return False
    if len(xs) == 2:
        fa, fb = _side_diff(xs), _side_diff(ys)
        if _has_inf(fa) or _has_inf(fb):
            return False
        k = _ratio(fa, fb)
        if k is None:
            return False
        if ops_a[0] in ("=", "!="):
            return True
        return k > 0
    return all(_equivalent(x, y) for x, y in zip(xs, ys, strict=True))


def _seq_equivalent(a: Seq, b: Seq) -> bool:
    if (a.open, a.close) != (b.open, b.close) or len(a.items) != len(b.items):
        return False
    if a.open in ("{", ""):
        return _match(a.items, b.items)
    return all(_equivalent(x, y) for x, y in zip(a.items, b.items, strict=True))


def _match(xs: tuple[Node, ...], ys: tuple[Node, ...]) -> bool:
    """Every part of one side is equivalent to some part of the other, and back."""
    return all(any(_equivalent(x, y) for y in ys) for x in xs) and all(
        any(_equivalent(y, x) for x in xs) for y in ys
    )


def _equivalent_forms(a: Node, b: Node) -> bool:
    xs, ys = _expand(a), _expand(b)
    return all(any(_equivalent(x, y) for y in ys) for x in xs) and all(
        any(_equivalent(y, x) for x in xs) for y in ys
    )


# ---------------------------------------------------------------------------
# The public check
# ---------------------------------------------------------------------------


def latex_of(text: str) -> str | None:
    """``text`` (keyboard form) as LaTeX, or None when it can't be read."""
    try:
        return to_latex(parse(text))
    except MathReadError:
        return None


def usable_target(answer: str) -> bool:
    """The card's ``MathAnswer`` can be read (and has no stray ``+-``)."""
    try:
        _form(parse(answer))
    except MathReadError:
        return False
    return True


def keyboard_from_palette(latex: str) -> str:
    """The palette's LaTeX as keyboard form; the text itself when it can't be
    converted (the check then says it couldn't read it)."""
    try:
        return latex_to_keyboard(latex)
    except MathReadError:
        return latex


def check_answer(typed: str, target: str, *, equiv: bool = False) -> MathCheck:
    """Grade ``typed`` (keyboard form) against ``target`` (the card's ``MathAnswer``)."""
    target_tex = latex_of(target) or ""
    try:
        typed_node = parse(typed)
        typed_form = _form(typed_node)
    except MathReadError:
        return MathCheck("unreadable", False, READ_MESSAGE, None, target_tex)
    typed_tex = to_latex(typed_node)
    try:
        target_node = parse(target)
        target_form = _form(target_node)
    except MathReadError:
        # An unreadable card answer: plain text match, so the card still drills.
        same = _WS.sub("", typed) == _WS.sub("", target)
        return MathCheck(
            "right" if same else "wrong", same, "" if same else WRONG_MESSAGE, typed_tex, ""
        )
    if typed_form == target_form:
        return MathCheck("right", True, "", typed_tex, target_tex)
    try:
        same_value = _equivalent_forms(typed_node, target_node)
    except (MathReadError, RecursionError):
        same_value = False
    if same_value and equiv:
        return MathCheck("right", True, "", typed_tex, target_tex)
    if same_value:
        message = f"{EQUIVALENT_PREFIX}\\({target_tex}\\)"
        return MathCheck("equivalent", False, message, typed_tex, target_tex)
    return MathCheck("wrong", False, WRONG_MESSAGE, typed_tex, target_tex)
