#!/usr/bin/env python3
"""verify_math.py — SymPy checks for every math claim on a card.

Nothing unverified ships: `verify_cards(cards)` must report 0 failures before
any card is added to Anki or shown to Don.

Two jobs:

1. **MathAnswer contract** (cards tagged ``rd::math``): the keyboard form in
   ``math_answer`` must parse, and must mean the same thing as the MathJax in
   the card's one cloze. Keyboard form rules (references/card-kinds-and-tags.md):
   ``^`` powers, ``sqrt()``, ``+-`` for ±, ``/`` with parentheses, ``i`` the
   imaginary unit, ``pi``, ``inf`` infinity, ``U`` union of intervals.
   Default grading in the drill is "same form, any order", so the keyboard
   form must have the same form as the cloze (checked structurally); only a
   card tagged ``rd::math::equiv`` accepts any equivalent form (checked with
   simplify).
2. **Claims** (`card["checks"]`, every card): each number, step, formula or
   answer the card states is recomputed independently.

Check kinds (all strings in keyboard form):

    {"kind": "equal", "a": "(1+2i)(1+3i)", "b": "-5+5i"}
    {"kind": "solve", "eq": "2x^2-x=3", "var": "x", "expect": "-1, 3/2",
        "domain": "complex"}            # domain: complex (default) | real
    {"kind": "ineq", "ineq": "abs(3x+2)<5", "var": "x", "expect": "(-7/3, 1)"}
        # also compound "-5 < 3x+2 < 5", "x < -1 or x > 3"; expect "none" / "all reals"
    {"kind": "vertex", "f": "x^2+10x+23", "var": "x", "expect": "(-5, -2)"}
    {"kind": "opens", "f": "-2x^2+10x-23/2", "var": "x", "expect": "down"}
    {"kind": "range", "f": "x^2-6x+5", "expect": "[-4, inf)"}
    {"kind": "numeric", "expr": "(-1-sqrt(22))/3", "expect": -1.897, "places": 3}
    {"kind": "factor", "expr": "x^2-5x+6", "expect": "(x-2)(x-3)"}
    {"kind": "true", "rel": "2^2-4*1*5 < 0"}
    {"kind": "step", "from": "3x^2+2x=7", "to": "3x^2+2x-7=0", "var": "x"}
        # an equation step: same solution set (complex) as the line before it;
        # "may_add": true for squaring both sides (extraneous roots allowed)
    {"kind": "definition"}   # states a definition / general form; nothing to compute
"""
from __future__ import annotations

import contextlib
import re
from typing import Any

import sympy as sp
from sympy.core.parameters import distribute as _distribute
from sympy.parsing.sympy_parser import (
    convert_xor,
    implicit_multiplication_application,
    parse_expr,
    standard_transformations,
)

_TRANS = standard_transformations + (implicit_multiplication_application, convert_xor)
_LOCAL = {"i": sp.I, "inf": sp.oo, "oo": sp.oo, "pi": sp.pi, "sqrt": sp.sqrt, "abs": sp.Abs, "Abs": sp.Abs,
          "E": sp.E}
X = sp.Symbol("x")

MATH_KINDS = ("expr", "equation", "list", "interval", "point")


class MathParseError(ValueError):
    pass


def _form_ctx(keep_form: bool):
    """keep_form: stop SymPy from multiplying a number into parentheses while
    parsing (3(x+2) -> 3x+6, -(x+1) -> -x-1, (x+1)/2 -> x/2+1/2). Values are the
    same either way, but whether it happens depends on how the text is grouped,
    so form comparisons parse with it off, like Recall Drill's checker (which
    grades 3x+6 against 3(x+2) as "equivalent", not "right"). v1.1.2."""
    return _distribute(False) if keep_form else contextlib.nullcontext()


# ---------------------------------------------------------------------------
# Keyboard form
# ---------------------------------------------------------------------------

def _pm_variants(s: str) -> list[str]:
    """'a+-b' -> ['a+b', 'a-b'] (every +- expanded; at most 2 allowed)."""
    n = s.count("+-")
    if n == 0:
        return [s]
    if n > 2:
        raise MathParseError(f"too many +- in {s!r}")
    out = [""]
    parts = s.split("+-")
    for k, p in enumerate(parts):
        if k == 0:
            out = [p]
            continue
        out = [o + "+" + p for o in out] + [o + "-" + p for o in out]
    return out


def _syms_in(s: str) -> dict:
    """Names SymPy should know (implicit multiplication splits 'ac' into a*c)."""
    return dict(_LOCAL)


def kb_expr(s: str) -> sp.Expr:
    """One keyboard expression (no +-, no '=') -> SymPy."""
    s = s.strip()
    if not s:
        raise MathParseError("empty expression")
    s = s.replace("−", "-").replace("·", "*").replace("×", "*")
    s = re.sub(r"\|([^|]+)\|", r"abs(\1)", s)
    try:
        return parse_expr(s, local_dict=_syms_in(s), transformations=_TRANS, evaluate=True)
    except Exception as exc:  # noqa: BLE001
        raise MathParseError(f"can't parse {s!r}: {exc}") from exc


def _split_top(s: str, sep: str = ",") -> list[str]:
    out, depth, start = [], 0, 0
    for k, ch in enumerate(s):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            out.append(s[start:k])
            start = k + 1
    out.append(s[start:])
    return [p.strip() for p in out]


def _interval(piece: str) -> sp.Set:
    piece = piece.strip()
    m = re.fullmatch(r"([\[(])(.*)([\])])", piece)
    if not m:
        raise MathParseError(f"not an interval: {piece!r}")
    a, b = _split_top(m.group(2))
    return sp.Interval(kb_expr(a), kb_expr(b), left_open=m.group(1) == "(",
                       right_open=m.group(3) == ")")


def parse_keyboard(s: str, kind: str, keep_form: bool = False) -> Any:
    """Keyboard answer -> comparable SymPy object (keep_form: see _form_ctx).

    expr     -> frozenset of expressions (two when +- is used)
    equation -> (lhs, frozenset of rhs variants)
    list     -> frozenset of expressions (solutions; +- expands)
    interval -> sympy Set (U = union)
    point    -> tuple of expressions
    """
    with _form_ctx(keep_form):
        return _parse_keyboard(s, kind)


def _parse_keyboard(s: str, kind: str) -> Any:
    s = s.strip()
    if kind == "expr":
        return frozenset(kb_expr(v) for v in _pm_variants(s))
    if kind == "equation":
        if s.count("=") != 1:
            raise MathParseError(f"equation needs one '=': {s!r}")
        lhs, rhs = s.split("=")
        return (kb_expr(lhs), frozenset(kb_expr(v) for v in _pm_variants(rhs)))
    if kind == "list":
        s2 = s.strip("{}")
        vals = []
        for p in _split_top(s2):
            vals.extend(kb_expr(v) for v in _pm_variants(p))
        return frozenset(vals)
    if kind == "interval":
        pieces = [p for p in re.split(r"\s+U\s+|∪", s)]
        out = sp.EmptySet
        for p in pieces:
            out = sp.Union(out, _interval(p))
        return out
    if kind == "point":
        m = re.fullmatch(r"\((.*)\)", s)
        if not m:
            raise MathParseError(f"not a point: {s!r}")
        return tuple(kb_expr(p) for p in _split_top(m.group(1)))
    raise MathParseError(f"unknown math kind {kind!r}")


# ---------------------------------------------------------------------------
# LaTeX (the MathJax shown in the cloze)
# ---------------------------------------------------------------------------

def _latex_clean(t: str) -> str:
    t = t.strip()
    t = re.sub(r"^\\\(|\\\)$", "", t).strip()
    t = t.replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    t = t.replace("\\left", "").replace("\\right", "")
    t = t.replace("\\lt", "<").replace("\\gt", ">")
    t = t.replace("\\,", " ").replace("\\ ", " ").replace("\\!", "")
    t = re.sub(r"\\text\{\s*or\s*\}", ",", t)
    return t


_LETTER_PAREN = re.compile(r"(\\[A-Za-z]+)|([A-Za-z])(?=\s*\()")


def _letter_times_paren(t: str) -> str:
    """a(x-h)^2 -> a \\cdot (x-h)^2. SymPy's LaTeX reader takes a letter before
    '(' as a function call (a(x-h), squared as a whole); the keyboard reader and
    the drill read it as multiplication. Commands (\\pi, \\sqrt) are left alone.
    v1.1.2."""
    return _LETTER_PAREN.sub(lambda m: m.group(1) or m.group(2) + " \\cdot ", t)


def _latex_one(t: str) -> sp.Expr:
    from sympy.parsing.latex import parse_latex
    t = t.strip()
    if not t:
        raise MathParseError("empty LaTeX")
    t = re.sub(r"\\infty", "oo", t) if t.strip() in ("\\infty", "-\\infty") else t
    if t in ("oo", "-oo"):
        return sp.oo if t == "oo" else -sp.oo
    try:
        e = parse_latex(_letter_times_paren(t))
    except Exception as exc:  # noqa: BLE001
        raise MathParseError(f"can't parse LaTeX {t!r}: {exc}") from exc
    return e.subs(sp.Symbol("i"), sp.I)


def _latex_pm(t: str) -> list[str]:
    if "\\pm" not in t:
        return [t]
    a = t.replace("\\pm", "+", 1)
    b = t.replace("\\pm", "-", 1)
    return _latex_pm(a) + _latex_pm(b)


def parse_latex_answer(tex: str, kind: str, keep_form: bool = False) -> Any:
    with _form_ctx(keep_form):
        return _parse_latex_answer(tex, kind)


def _parse_latex_answer(tex: str, kind: str) -> Any:
    t = _latex_clean(tex)
    if kind == "expr":
        return frozenset(_latex_one(v) for v in _latex_pm(t))
    if kind == "equation":
        lhs, rhs = t.split("=", 1)
        return (_latex_one(lhs), frozenset(_latex_one(v) for v in _latex_pm(rhs)))
    if kind == "list":
        t2 = re.sub(r"^\\\{|\\\}$", "", t.strip())
        vals = []
        for p in _latex_split(t2):
            vals.extend(_latex_one(v) for v in _latex_pm(p))
        return frozenset(vals)
    if kind == "interval":
        out = sp.EmptySet
        for piece in re.split(r"\\cup", t):
            piece = piece.strip()
            m = re.fullmatch(r"([\[(])(.*)([\])])", piece)
            if not m:
                raise MathParseError(f"not an interval: {piece!r}")
            a, b = _latex_split(m.group(2))
            out = sp.Union(out, sp.Interval(_latex_one(a), _latex_one(b),
                                            left_open=m.group(1) == "(",
                                            right_open=m.group(3) == ")"))
        return out
    if kind == "point":
        m = re.fullmatch(r"\((.*)\)", t.strip())
        if not m:
            raise MathParseError(f"not a point: {t!r}")
        return tuple(_latex_one(p) for p in _latex_split(m.group(1)))
    raise MathParseError(f"unknown math kind {kind!r}")


def _latex_split(t: str) -> list[str]:
    """Split LaTeX at top-level commas (braces and brackets respected)."""
    out, depth, start = [], 0, 0
    for k, ch in enumerate(t):
        if ch in "({[":
            depth += 1
        elif ch in ")}]":
            depth -= 1
        elif ch == "," and depth == 0:
            out.append(t[start:k])
            start = k + 1
    out.append(t[start:])
    return [p.strip() for p in out if p.strip()]


# ---------------------------------------------------------------------------
# Equivalence
# ---------------------------------------------------------------------------

def same_value(a: sp.Expr, b: sp.Expr) -> bool:
    if a == b:
        return True
    try:
        d = sp.simplify(sp.expand_complex(a - b)) if (a.has(sp.I) or b.has(sp.I)) else sp.simplify(a - b)
        if d == 0:
            return True
    except Exception:  # noqa: BLE001
        pass
    # numeric fallback at random points (formulas with letters)
    free = sorted((a.free_symbols | b.free_symbols), key=str)
    if not free:
        try:
            return abs(complex(sp.N(a - b, 30))) < 1e-12
        except Exception:  # noqa: BLE001
            return False
    import random
    rnd = random.Random(7)
    for _ in range(6):
        sub = {s: sp.Rational(rnd.randint(2, 19), rnd.randint(1, 7)) for s in free}
        try:
            if abs(complex(sp.N((a - b).subs(sub), 30))) > 1e-9:
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


def same_set(a, b) -> bool:
    a, b = list(a), list(b)
    if len(a) != len(b):
        # duplicates (e.g. +-0) collapse
        pass
    return all(any(same_value(x, y) for y in b) for x in a) and \
        all(any(same_value(x, y) for x in a) for y in b)


def same_form(a: sp.Expr, b: sp.Expr) -> bool:
    """Same written form: equal after SymPy's automatic ordering only (no
    simplify, no number multiplied into parentheses). (x-2)(x+3) and (x+3)(x-2)
    match; x^2+x-6 does not; 3x+6 and 3(x+2) do not. Pass expressions parsed
    with keep_form=True."""
    try:
        with _form_ctx(True):
            ca = sp.sympify(str(a), locals={"I": sp.I})
            cb = sp.sympify(str(b), locals={"I": sp.I})
        return ca == cb
    except Exception:  # noqa: BLE001
        return False


def same_form_set(a, b) -> bool:
    a, b = list(a), list(b)
    return all(any(same_form(x, y) for y in b) for x in a) and \
        all(any(same_form(x, y) for x in a) for y in b)


def same_answer(a: Any, b: Any, kind: str, equiv: bool = True) -> bool:
    if not equiv:
        if kind in ("expr", "list"):
            return same_form_set(a, b)
        if kind == "equation":
            return same_form(a[0], b[0]) and same_form_set(a[1], b[1])
        if kind == "point":
            return len(a) == len(b) and all(same_form(x, y) for x, y in zip(a, b))
    if kind in ("expr", "list"):
        return same_set(a, b)
    if kind == "equation":
        return same_value(a[0], b[0]) and same_set(a[1], b[1])
    if kind == "interval":
        return sp.simplify(a.symmetric_difference(b)) == sp.EmptySet if a != b else True
    if kind == "point":
        return len(a) == len(b) and all(same_value(x, y) for x, y in zip(a, b))
    return False


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _eq(s: str) -> sp.Expr:
    """Keyboard equation 'lhs = rhs' -> lhs - rhs (expression = 0)."""
    if s.count("=") != 1:
        raise MathParseError(f"equation needs one '=': {s!r}")
    lhs, rhs = s.split("=")
    return kb_expr(lhs) - kb_expr(rhs)


def _sym(name: str | None) -> sp.Symbol:
    return sp.Symbol(name or "x")


def _real_odd_roots(e: sp.Expr) -> sp.Expr:
    """x^(p/q) with q odd -> real_root(x, q)^p, so (-1)^(1/3) = -1 as in the
    course (real cube roots), not SymPy's principal complex root."""
    return e.replace(
        lambda z: isinstance(z, sp.Pow) and isinstance(z.exp, sp.Rational)
        and z.exp.q > 1 and z.exp.q % 2 == 1,
        lambda z: sp.real_root(z.base, z.exp.q) ** z.exp.p)


def _solutions(expr: sp.Expr, var: sp.Symbol, domain: str = "complex") -> set:
    dom = sp.S.Complexes if domain == "complex" else sp.S.Reals
    if domain == "real":
        expr = _real_odd_roots(expr)
    sol = sp.solveset(sp.together(expr), var, domain=dom)
    if sol == sp.EmptySet:
        return set()
    if isinstance(sol, sp.Complement) and isinstance(sol.args[0], sp.FiniteSet):
        sol = sol.args[0]   # letters in the answer: SymPy only excludes generic values
    if not isinstance(sol, sp.FiniteSet):
        raise MathParseError(f"solution set not finite: {sol}")
    # solveset on a rational expression already drops points where a
    # denominator is 0; double-check by substituting into the original
    good = set()
    for r in sol:
        val = expr.subs(var, r)
        if val.has(sp.zoo, sp.nan) or sp.simplify(val) != 0:
            continue
        good.add(r)
    return good


def _solutions_by_sub(expr: sp.Expr, var: sp.Symbol, u_of: sp.Expr,
                      domain: str) -> set:
    """Equations in quadratic form: let u = u_of, solve for u, then solve
    u_of = u0 for each u0 (Bittinger 3.2 Examples 9-11)."""
    u = sp.Symbol("u")
    fix = _real_odd_roots if domain == "real" else (lambda e: e)
    e, uo = fix(expr), fix(u_of)
    eu = sp.expand(e.subs(uo ** 2, u ** 2).subs(uo, u))
    if eu.has(var) and isinstance(uo, sp.Pow) and uo.exp == sp.Rational(1, 2):
        # u = sqrt(s): s = u^2 with u >= 0
        up = sp.Symbol("u", nonnegative=True)
        eu = sp.expand(e.subs(var, up ** 2)).subs(up, u)
        sols = {u0 for u0 in _solutions(eu, u, "real") if u0 >= 0}
        return {u0 ** 2 for u0 in sols if sp.simplify(e.subs(var, u0 ** 2)) == 0}
    if eu.has(var):
        # inverse substitution: write var in terms of u (e.g. u = 3x-1 -> x = (u+1)/3)
        for g in sp.solve(sp.Eq(u, uo), var):
            cand = sp.simplify(sp.expand(e.subs(var, g)))
            if not cand.has(var):
                eu = cand
                break
    if eu.has(var):
        raise MathParseError(f"u = {u_of} doesn't remove {var}: {eu}")
    out = set()
    for u0 in _solutions(eu, u, domain):
        out |= _solutions(uo - u0, var, domain)
    return {r for r in out if sp.simplify(e.subs(var, r)) == 0}


# ---------------------------------------------------------------------------
# Relations (equations and inequalities) -> solution sets   [v1.1]
# ---------------------------------------------------------------------------

_REL_OPS = ("<=", ">=", "≤", "≥", "<", ">", "=")
_REL_SPLIT = re.compile(r"(<=|>=|≤|≥|<|>|=)")
_OP_FN = {"<": sp.Lt, "<=": sp.Le, "≤": sp.Le, ">": sp.Gt, ">=": sp.Ge, "≥": sp.Ge, "=": sp.Eq}


def is_inequality(s: str) -> bool:
    """True when a keyboard relation uses <, <=, >, >= (or 'or' between parts)."""
    return bool(re.search(r"<|>|≤|≥", s)) or bool(re.search(r"\bor\b", s))


def _one_relation(s: str, fix=lambda e: e) -> sp.Basic:
    """'a < X', 'a < X <= b' (compound) -> SymPy relational (And for compound)."""
    parts = _REL_SPLIT.split(s)
    exprs = [fix(kb_expr(p)) for p in parts[0::2]]
    ops = parts[1::2]
    if not ops:
        raise MathParseError(f"no relation in {s!r}")
    rels = [_OP_FN[op](exprs[k], exprs[k + 1]) for k, op in enumerate(ops)]
    return rels[0] if len(rels) == 1 else sp.And(*rels)


def solution_set(s: str, var: sp.Symbol, domain: str = "real") -> sp.Set:
    """Solution set of a keyboard equation or inequality as a SymPy Set.
    Accepts compound inequalities ('-5 < 3x+2 < 5') and 'or' between parts
    ('x < -1 or x > 3'). Inequalities are solved over the reals; an equation
    with finitely many roots returns a FiniteSet (extraneous roots and real
    odd roots handled as in _solutions)."""
    pieces = [p.strip() for p in re.split(r"\bor\b", s)]
    out = sp.EmptySet
    for p in pieces:
        if not is_inequality(p):
            e = _eq(p)
            dom = sp.S.Complexes if domain == "complex" else sp.S.Reals
            try:
                out = sp.Union(out, sp.FiniteSet(*_solutions(e, var, domain)))
            except MathParseError:
                ee = _real_odd_roots(e) if domain == "real" else e
                out = sp.Union(out, sp.solveset(sp.together(ee), var, domain=dom))
            continue
        rel = _one_relation(p, _real_odd_roots)
        if isinstance(rel, sp.And):
            part = sp.S.Reals
            for r in rel.args:
                part = sp.Intersection(part, sp.solveset(r, var, domain=sp.S.Reals))
        else:
            part = sp.solveset(rel, var, domain=sp.S.Reals)
        out = sp.Union(out, part)
    return sp.simplify(out) if not isinstance(out, sp.FiniteSet) else out


def same_solution_set(a, b) -> bool:
    """Compare two solution sets: finite sets element by element (same_value),
    anything else (intervals, unions, all reals) as sets."""
    def as_set(v):
        if isinstance(v, sp.Set):
            return v
        return sp.FiniteSet(*v)
    A, B = as_set(a), as_set(b)
    if isinstance(A, sp.FiniteSet) and isinstance(B, sp.FiniteSet):
        return same_set(list(A), list(B))
    if A == B:
        return True
    try:
        return sp.simplify(A.symmetric_difference(B)) == sp.EmptySet
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Written form of a typed answer (what SymPy's parser hides)   [v1.1]
# ---------------------------------------------------------------------------
# SymPy simplifies while it parses: sqrt(88) becomes 2*sqrt(22) and
# (-2+2sqrt(22))/6 becomes -1/3+sqrt(22)/3. So form rules are checked on the
# text as typed (and on an unevaluated parse), never on the parsed value.

FORMS = ("exact", "reduced_fraction", "simplified_radical", "a+bi", "interval")


def _raw(s: str) -> sp.Expr:
    s = s.strip().replace("−", "-")
    s = re.sub(r"\|([^|]+)\|", r"abs(\1)", s)
    try:
        return parse_expr(s, local_dict=dict(_LOCAL), transformations=_TRANS, evaluate=False)
    except Exception as exc:  # noqa: BLE001
        raise MathParseError(f"can't parse {s!r}: {exc}") from exc


def _int_content(e: sp.Expr) -> int:
    """gcd of the integer coefficients of the terms of an unevaluated sum."""
    terms = e.args if isinstance(e, sp.Add) else (e,)
    g = 0
    for t in terms:
        c, _rest = t.as_coeff_Mul()
        if not (c.is_Integer or (c.is_Rational and c.q == 1)):
            return 1
        g = sp.igcd(g, int(abs(c)))
    return g or 1


def _unreduced(e: sp.Expr) -> bool:
    """A fraction whose numerator terms and denominator share a factor:
    (-2 + 2 sqrt(22))/6, 6/8, 4x/6."""
    for node in sp.preorder_traversal(e):
        if isinstance(node, sp.Mul):
            dens = [f for f in node.args if isinstance(f, sp.Pow) and f.exp == -1 and f.base.is_Integer]
            nums = [f for f in node.args if f not in dens]
            if dens and nums:
                d = int(abs(dens[0].base))
                num = nums[0] if len(nums) == 1 else sp.Mul(*nums, evaluate=False)
                if d > 1 and sp.igcd(_int_content(num), d) > 1:
                    return True
    return False


def _approx_places(form: str) -> int | None:
    m = re.fullmatch(r"approx:(\d+)", form)
    return int(m.group(1)) if m else None


def form_problems(typed: str, forms: list[str]) -> list[str]:
    """Problems with how an answer is WRITTEN (not its value). `forms` are the
    recipe/card forms: exact, reduced_fraction, simplified_radical, a+bi,
    interval, approx:N (rounded to N decimal places). [] = form is right."""
    probs: list[str] = []
    s = typed.strip()
    variants = []
    for piece in _split_top(s.strip("{}")):
        variants += _pm_variants(piece)
    for form in forms:
        n = _approx_places(form)
        if n is not None:
            for v in variants:
                for num in re.findall(r"-?\d+\.\d+|-?\d+", v):
                    if "." not in num or len(num.split(".")[1]) != n:
                        probs.append(f"not rounded to {n} decimal places: {num}")
            continue
        if form == "exact" and re.search(r"\d\.\d", s):
            probs.append(f"not exact (decimal): {s}")
        if form == "simplified_radical":
            for n_ in re.findall(r"sqrt\((\d+)\)", s):
                k = int(n_)
                if any(k % (j * j) == 0 for j in range(2, int(k ** 0.5) + 1)):
                    probs.append(f"radical not simplified: sqrt({k})")
        if form == "reduced_fraction":
            for a, b in re.findall(r"(?<![\w.)])(\d+)\s*/\s*(\d+)(?![\w.(])", s):
                if sp.igcd(int(a), int(b)) != 1:
                    probs.append(f"fraction not reduced: {a}/{b}")
            for v in variants:
                try:
                    if _unreduced(_raw(v)):
                        probs.append(f"fraction not reduced: {v}")
                        break
                except MathParseError:
                    pass
        if form == "a+bi" and re.search(r"sqrt\(\s*-", s):
            probs.append(f"square root of a negative left in: {s}")
        if form == "interval" and not re.search(r"[\[(].*,.*[\])]", s):
            probs.append(f"not interval notation: {s}")
    return list(dict.fromkeys(probs))


def check_answer(typed: str, key: str, kind: str, forms: list[str] | None = None,
                 equiv: bool = True) -> dict:
    """For Math Path / Recall Drill builds: grade a typed answer against the
    key. Value first (equivalent, or same form when equiv=False), then the
    written-form rules on the TEXT as typed. Returns
    {"value_ok": bool, "form_problems": [...], "ok": bool}.
    approx:N forms compare numbers within half a unit in the last place."""
    forms = forms or []
    places = next((p for p in map(_approx_places, forms) if p is not None), None)
    try:
        if places is not None:
            a = sorted(complex(sp.N(v)).real for v in parse_keyboard(typed, "list"))
            b = sorted(complex(sp.N(v)).real for v in parse_keyboard(key, "list"))
            tol = 0.5 * 10 ** (-places) + 1e-9
            value_ok = len(a) == len(b) and all(abs(x - y) <= tol for x, y in zip(a, b))
        else:
            value_ok = same_answer(parse_keyboard(typed, kind, keep_form=not equiv),
                                   parse_keyboard(key, kind, keep_form=not equiv), kind, equiv)
    except MathParseError:
        value_ok = False
    fp = form_problems(typed, forms) if value_ok else []
    return {"value_ok": value_ok, "form_problems": fp, "ok": value_ok and not fp}


def run_check(chk: dict) -> tuple[bool, str]:
    kind = chk.get("kind")
    try:
        if kind == "definition":
            return True, "definition (nothing to compute)"
        if kind == "equal":
            a = parse_keyboard(chk["a"], "expr")
            b = parse_keyboard(chk["b"], "expr")
            ok = same_set(a, b)
            return ok, f"{chk['a']} {'=' if ok else '!='} {chk['b']}"
        if kind == "solve":
            v = _sym(chk.get("var"))
            if chk.get("u"):
                got = _solutions_by_sub(_eq(chk["eq"]), v, kb_expr(chk["u"]),
                                        chk.get("domain", "complex"))
            else:
                got = _solutions(_eq(chk["eq"]), v, chk.get("domain", "complex"))
            want = parse_keyboard(chk["expect"], "list") if chk["expect"].strip() not in ("none", "{}") else frozenset()
            ok = same_set(got, want)
            return ok, f"solve {chk['eq']}: SymPy {sorted(map(str, got))} vs card {chk['expect']}"
        if kind == "ineq":
            v = _sym(chk.get("var"))
            got = solution_set(chk["ineq"], v, "real")
            exp = chk["expect"].strip()
            if exp in ("none", "{}"):
                want = sp.EmptySet
            elif exp in ("all reals", "(-inf, inf)"):
                want = sp.S.Reals
            else:
                want = parse_keyboard(exp, "interval")
            ok = same_solution_set(got, want)
            return ok, f"solve {chk['ineq']}: SymPy {got} vs card {chk['expect']}"
        if kind == "vertex":
            v = _sym(chk.get("var"))
            f = kb_expr(chk["f"])
            p = sp.Poly(sp.expand(f), v)
            if p.degree() != 2:
                return False, "not quadratic"
            a, b, _c = p.all_coeffs()
            h = -b / (2 * a)
            k = sp.simplify(f.subs(v, h))
            want = parse_keyboard(chk["expect"], "point")
            ok = same_value(h, want[0]) and same_value(k, want[1])
            return ok, f"vertex of {chk['f']}: SymPy ({h}, {k}) vs card {chk['expect']}"
        if kind == "range":
            v = _sym(chk.get("var"))
            f = kb_expr(chk["f"])
            got = sp.calculus.util.function_range(f, v, sp.S.Reals)
            want = parse_keyboard(chk["expect"], "interval")
            ok = same_answer(got, want, "interval")
            return ok, f"range of {chk['f']}: SymPy {got} vs card {chk['expect']}"
        if kind == "opens":
            v = _sym(chk.get("var"))
            a = sp.Poly(sp.expand(kb_expr(chk["f"])), v).all_coeffs()[0]
            got = "up" if a > 0 else "down"
            return got == chk["expect"], f"{chk['f']} opens {got} (card: {chk['expect']})"
        if kind == "numeric":
            val = complex(sp.N(kb_expr(chk["expr"]), 30))
            places = int(chk.get("places", 3))
            got = round(val.real, places)
            ok = abs(val.imag) < 1e-12 and abs(got - float(chk["expect"])) < 10 ** (-places) / 2
            return ok, f"{chk['expr']} ≈ {got} (card: {chk['expect']})"
        if kind == "factor":
            e = kb_expr(chk["expr"])
            f = kb_expr(chk["expect"])
            same = same_value(e, f)
            is_prod = isinstance(f, sp.Mul) or isinstance(f, sp.Pow)
            return same and is_prod, f"{chk['expr']} = {chk['expect']} ({'factored' if is_prod else 'NOT a product'})"
        if kind == "true":
            r = kb_expr(chk["rel"])
            ok = bool(r) is True
            return ok, f"{chk['rel']} is {bool(r)}"
        if kind == "step":
            v = _sym(chk.get("var"))
            a = _solutions(_eq(chk["from"]), v)
            b = _solutions(_eq(chk["to"]), v)
            if chk.get("may_add"):
                ok = all(any(same_value(x, y) for y in b) for x in a)
            else:
                ok = same_set(a, b)
            return ok, f"step {chk['from']} -> {chk['to']}: {sorted(map(str, a))} -> {sorted(map(str, b))}"
    except (MathParseError, KeyError, TypeError, ValueError, NotImplementedError) as exc:
        return False, f"{kind}: error {exc}"
    return False, f"unknown check kind {kind!r}"


# ---------------------------------------------------------------------------
# Cards
# ---------------------------------------------------------------------------

_CLOZE_RE = re.compile(r"\{\{c(\d+)::(.*?)(?:::(.*?))?\}\}", re.S)


def cloze_answers(text: str) -> list[str]:
    return [m.group(2) for m in _CLOZE_RE.finditer(text)]


def _palette_latex(tex: str) -> str:
    """The cloze's MathJax as the drill's palette (MathLive) would send it."""
    t = tex.strip()
    t = re.sub(r"^\\\(|\\\)$", "", t).strip()
    t = t.replace("} }", "}}").replace("\\dfrac", "\\frac").replace("\\tfrac", "\\frac")
    t = t.replace("\\lt", "<").replace("\\gt", ">").replace("\\,", "").replace("\\!", "")
    return t


def drill_grade(card_math: list[str], math_answer: str, equiv: bool) -> tuple[str, str]:
    """Grade, with Recall Drill's own checker (scripts/drill_check, copied from the
    add-on), the answer a student gets by typing exactly what the card shows.
    Returns (outcome, message); outcome "right" is the only pass. v1.1.1."""
    import os
    import sys
    here = os.path.dirname(os.path.abspath(__file__))
    if here not in sys.path:
        sys.path.insert(0, here)
    try:
        from drill_check.math_answer import check_answer as _drill_check
        from drill_check.math_answer import keyboard_from_palette, usable_target
    except Exception as exc:  # noqa: BLE001
        return "error", f"Recall Drill checker missing: {exc}"
    if not usable_target(math_answer):
        return "unusable", "Recall Drill can't read this MathAnswer (it would drill as a word card)"
    try:
        typed = ", ".join(keyboard_from_palette(_palette_latex(m)) for m in card_math)
    except Exception as exc:  # noqa: BLE001
        return "unreadable", f"the drill's palette can't read the card's math: {exc}"
    r = _drill_check(typed, math_answer, equiv=equiv)
    return r.outcome, r.message


def verify_card(card: dict) -> list[str]:
    """Problems with one card ([] = verified). Sets card['verified']."""
    problems: list[str] = []
    checks = card.get("checks")
    if not checks:
        problems.append("no checks: every card needs at least one (or {'kind': 'definition'})")
    else:
        for chk in checks:
            ok, msg = run_check(chk)
            if not ok:
                problems.append("check failed: " + msg)
    if "rd::math" in card.get("tags", []) or card.get("math_answer"):
        kind = card.get("math_kind")
        ans = card.get("math_answer", "")
        blanks = cloze_answers(card.get("text", ""))
        if kind not in MATH_KINDS:
            problems.append(f"math_kind must be one of {MATH_KINDS}")
        elif not ans:
            problems.append("rd::math card without math_answer")
        elif len(blanks) != 1:
            problems.append(f"math card needs exactly one cloze, has {len(blanks)}")
        else:
            try:
                kb = parse_keyboard(ans, kind)
            except MathParseError as exc:
                problems.append(f"MathAnswer doesn't parse: {exc}")
                kb = None
            tex = blanks[0]
            mj = re.findall(r"\\\((.*?)\\\)", tex, re.S)
            if not mj:
                problems.append("math cloze has no \\( ... \\) MathJax")
            elif kb is not None:
                try:
                    lt = parse_latex_answer(" ".join(mj) if len(mj) == 1 else mj[0], kind)
                    equiv = "rd::math::equiv" in card.get("tags", [])
                    if not same_answer(kb, lt, kind):
                        problems.append(f"MathAnswer {ans!r} != cloze {tex!r}")
                    elif not equiv and not same_answer(
                            parse_keyboard(ans, kind, keep_form=True),
                            parse_latex_answer(" ".join(mj) if len(mj) == 1 else mj[0], kind, keep_form=True),
                            kind, equiv=False):
                        problems.append(f"MathAnswer {ans!r} is equal to the cloze but not in the same "
                                        f"form (drill grades same form; tag rd::math::equiv if any form counts)")
                    if re.search(r"\boo\b", ans):
                        problems.append("MathAnswer: write infinity as inf, not oo")
                    outcome, msg = drill_grade(mj, ans, equiv)
                    if outcome != "right":
                        problems.append(f"Recall Drill grades the card's own math as {outcome!r} against "
                                        f"MathAnswer {ans!r} ({msg}): write MathAnswer in the same form the card shows")
                except MathParseError as exc:
                    problems.append(f"cloze LaTeX doesn't parse: {exc}")
    card["verified"] = not problems
    return problems


def verify_cards(cards: list[dict]) -> dict:
    """Verify every card. Returns {'ok': n, 'failed': [(index, problems)],
    'checks': total checks run, 'definitions': n}."""
    failed, nchecks, ndef = [], 0, 0
    for i, c in enumerate(cards):
        p = verify_card(c)
        nchecks += len(c.get("checks") or [])
        ndef += sum(1 for k in c.get("checks") or [] if k.get("kind") == "definition")
        if p:
            failed.append((i, p))
    return {"ok": len(cards) - len(failed), "failed": failed, "checks": nchecks,
            "definitions": ndef}


if __name__ == "__main__":
    import json
    import sys
    data = json.load(open(sys.argv[1], encoding="utf-8"))
    rep = verify_cards(data)
    for i, p in rep["failed"]:
        print(f"card {i}: " + "; ".join(p))
    print(f"{rep['ok']} of {len(data)} cards verified, {rep['checks']} checks "
          f"({rep['definitions']} definitions)")
    sys.exit(1 if rep["failed"] else 0)
