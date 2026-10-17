#!/usr/bin/env python3
"""recipe_validator.py — checks Math Path problem recipes (mathpath-recipe/1 and /2).

For every recipe it generates N instances (default 20, fixed seeds) and checks
with SymPy, independently of what the recipe claims:

1. the parameters meet every constraint (the generator retries; a recipe that
   can't produce N clean instances in 2000 tries fails);
2. the problem's own solution set (SymPy solveset) equals the recipe answer;
3. every step's result: equations keep the solution set ("equivalent";
   "may_add" allows extraneous roots after squaring), factored forms are
   products, "each" lists split into equations whose solutions are the answer,
   "solutions" equal the answer, "values" match the coefficients, "true" holds;
4. the answer's required form (exact, reduced fraction, simplified radical,
   a+bi, interval brackets) — the answer as written must already be in that form;
5. every named mistake gives a wrong answer different from the right one on
   every instance (otherwise its detection rule would fire on correct work);
6. every step has a hint and a why, in that order; step names match the
   process card's steps word for word (when a cards file is given).

Format 2 (v1.1) adds, without changing how format-1 recipes are checked:
- problem.task: solve (default) | vertex | axis | extreme | range | domain |
  evaluate | graph  (non-solve tasks read problem.function, plus "at" for evaluate);
- inequalities in problem.equation (<, <=, >, >=, compound a < X < b, "or");
- answer kinds none ("no solution"), all_reals, graph ("parabola; (h, k); (x, y)");
- answer forms approx:N (value written with N decimals, e.g. {fix3:t}) and
  answer.reject_if (["t < 0"]) for applied problems;
- answer.display (course notation, must equal the value) and answer.type
  (minimum/maximum for task extreme);
- step check pm_equation ("x - 2 = +-sqrt(11)") and inequality steps under
  "equivalent"; mistake rule form_violation (value right, written form wrong).

Usage:
    python3 recipe_validator.py recipes_dir_or_files... [--cards cards.json] [--n 20] [--report out.md]
Exit code 1 if any recipe fails. The format is documented in
references/recipe-format.md.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import re
import sys

import sympy as sp

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from verify_math import (  # noqa: E402
    MathParseError,
    _pm_variants,
    _real_odd_roots,
    _solutions,
    _solutions_by_sub,
    form_problems,
    is_inequality,
    kb_expr,
    parse_keyboard,
    same_answer,
    same_set,
    same_solution_set,
    same_value,
    solution_set,
)

FORMAT = "mathpath-recipe/1"          # oldest format still read
FORMATS = ("mathpath-recipe/1", "mathpath-recipe/2")
TASKS = ("solve", "vertex", "axis", "extreme", "range", "domain", "evaluate", "graph")
KINDS = ("list", "expr", "equation", "interval", "point", "none", "all_reals", "graph")
SHAPES = ("parabola", "line", "absolute value", "curve")
_PLACE = re.compile(r"\{(tex:|fix\d:)?([A-Za-z_][A-Za-z0-9_]*)\}")
_CLOZE = re.compile(r"\{\{c\d+::(.*?)(?:::(.*?))?\}\}", re.S)


# ---------------------------------------------------------------------------
# Printing
# ---------------------------------------------------------------------------

def kb(e) -> str:
    """SymPy -> keyboard form (^, i, inf)."""
    s = sp.sstr(e)
    s = s.replace("**", "^").replace("oo", "inf")
    s = re.sub(r"\bI\b", "i", s)
    return s


def _deg(term) -> float:
    """Total power of the variables in a term (sqrt(x) counts 1/2), for
    textbook order: highest power first, constant last."""
    d = 0.0
    for base, exp in term.as_powers_dict().items():
        if isinstance(base, sp.Symbol) and exp.is_number:
            d += float(exp)
        elif base.free_symbols and isinstance(base, sp.Pow):
            d += float(base.exp) if base.exp.is_number else 0
    return d


def tex(e) -> str:
    """LaTeX in textbook order (x^2 + bx + c, x - 4 sqrt(x) - 32)."""
    if isinstance(e, sp.Add):
        terms = sorted(e.args, key=lambda t: -_deg(t))
        return sp.latex(sp.Add(*terms, evaluate=False), order="none", imaginary_unit="i")
    return sp.latex(e, imaginary_unit="i")


def fill(template: str, env: dict) -> str:
    """Fill {name} (keyboard form) and {tex:name} (LaTeX). A value is put in
    parentheses only where an operator, letter or digit comes right before it
    ('x - {p}' -> 'x - (-3)'), not at the start of a list item, point or
    interval ('({h}, {k})' -> '(-2, -5)')."""
    def rep(m):
        name = m.group(2)
        if name not in env:
            raise KeyError(f"unknown name {{{name}}} in {template!r}")
        v = env[name]
        if m.group(1) and m.group(1).startswith("fix"):
            places = int(m.group(1)[3])
            return f"{float(sp.N(v, 30)):.{places}f}"
        if m.group(1):
            return tex(v)
        before = template[:m.start()].rstrip()
        if before and before[-1].isdigit():
            return f"({kb(v)})"          # '2{h}' with h = 2 must read 2(2), not 22
        wrap = bool(before) and (before[-1] in "+-*/^" or before[-1].isalnum())
        return f"({kb(v)})" if wrap and _needs_paren(v) else kb(v)
    return _PLACE.sub(rep, template)


def _needs_paren(v) -> bool:
    """Wrap negatives and sums when substituted into a template, so
    'x - {p}' with p = -3 reads 'x - (-3)'."""
    if isinstance(v, sp.Basic):
        return v.is_Add or (v.is_number and v.is_real and v.is_negative) or \
            (v.is_Mul and v.could_extract_minus_sign())
    return False


# ---------------------------------------------------------------------------
# Generation
# ---------------------------------------------------------------------------

def draw_params(spec: dict, rnd: random.Random) -> dict:
    env = {}
    for name, d in spec.items():
        if "choice" in d:
            v = rnd.choice(d["choice"])
        elif "int" in d:
            lo, hi = d["int"]
            pool = [k for k in range(lo, hi + 1) if k not in d.get("not", [])]
            v = rnd.choice(pool)
        else:
            raise ValueError(f"param {name}: need 'choice' or 'int'")
        env[name] = sp.sympify(v)
    return env


def _subst(expr: str, env: dict) -> str:
    """Put the values of named parameters into a keyboard expression
    (names are whole words; longer names first)."""
    s = expr
    for k, v in sorted(env.items(), key=lambda kv: -len(kv[0])):
        s = re.sub(rf"(?<![A-Za-z_]){re.escape(k)}(?![A-Za-z_0-9])", f"({kb(v)})", s)
    return s


def derive(let: dict, env: dict, var: str) -> dict:
    env = dict(env)
    for name, expr in let.items():
        local = {k: v for k, v in env.items() if k != var}
        env[name] = kb_expr(_subst(expr, local))
    return env


def cond(expr: str, env: dict) -> bool:
    """A constraint like 'p/a != q' or 's < 0', evaluated on the instance."""
    s = _subst(expr, env)
    m = re.fullmatch(r"(.+?)\s*(==|!=)\s*(.+)", s)
    if m:
        eq = sp.simplify(kb_expr(m.group(1)) - kb_expr(m.group(3))) == 0
        return eq if m.group(2) == "==" else not eq
    return bool(kb_expr(s))


def instance(recipe: dict, seed: int, tries: int = 2000) -> dict:
    rnd = random.Random(seed)
    var = recipe.get("var", "x")
    for _ in range(tries):
        env = draw_params(recipe["params"], rnd)
        try:
            env = derive(recipe.get("let", {}), env, var)
        except (MathParseError, ZeroDivisionError):
            continue
        ok = True
        for c in recipe.get("constraints", []):
            try:
                if not cond(c, env):
                    ok = False
                    break
            except Exception:  # noqa: BLE001
                ok = False
                break
        if ok:
            return env
    raise RuntimeError(f"{recipe['id']}: no clean instance in {tries} tries (seed {seed})")


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------

def _eq_expr(s: str) -> sp.Expr:
    if s.count("=") != 1:
        raise MathParseError(f"need one '=': {s!r}")
    a, b = s.split("=")
    return kb_expr(a) - kb_expr(b)


def _var(recipe: dict) -> sp.Symbol:
    return sp.Symbol(recipe.get("var", "x"))


def _rel_text(recipe: dict) -> str:
    p = recipe["problem"]
    return p.get("equation") or p.get("relation") or ""


def _task(recipe: dict) -> str:
    return recipe["problem"].get("task", "solve")


def _kind(recipe: dict) -> str:
    return recipe["answer"].get("kind", "list")


def _places(recipe: dict) -> int | None:
    for f in recipe["answer"].get("form", []):
        m = re.fullmatch(r"approx:(\d+)", f)
        if m:
            return int(m.group(1))
    return None


def parse_graph(s: str) -> dict:
    """'parabola; (3, -4); (5, 0)' -> {'shape': 'parabola', 'points': [(3, -4), (5, 0)]}.
    The MyMathLab graph tool asks for the shape, then the vertex, then one more point."""
    parts = [p.strip() for p in s.split(";")]
    return {"shape": parts[0].lower(), "points": [parse_keyboard(p, "point") for p in parts[1:] if p]}


def _answer_obj(recipe: dict, env: dict, template: str | None = None):
    kind = _kind(recipe)
    text = fill(recipe["answer"]["value"] if template is None else template, env)
    if template is not None and kind in ("none", "all_reals"):
        # a mistake's wrong answer: "no solution", an interval, or a list of numbers
        t = text.strip()
        if t.lower() in ("none", "no solution", "{}"):
            return set()
        if t in ("all reals", "(-inf, inf)"):
            return sp.S.Reals
        if re.fullmatch(r"[\[(].*,.*[\])](\s*U\s*[\[(].*[\])])*", t) and not re.fullmatch(r"\([^,]*\)", t):
            try:
                return parse_keyboard(t, "interval")
            except MathParseError:
                pass
        return parse_keyboard(t, "list")
    if kind == "none":
        if text.strip().lower() not in ("", "none", "no solution", "{}"):
            raise MathParseError(f"answer kind none needs value 'no solution', got {text!r}")
        return set()
    if kind == "all_reals":
        return sp.S.Reals
    if kind == "graph":
        return parse_graph(text)
    return parse_keyboard(text, kind)


def _answer_set(recipe: dict, env: dict):
    return _answer_obj(recipe, env)


def _reject(recipe: dict, env: dict, sols: set) -> set:
    """Drop solutions that make no sense in an applied problem (answer.reject_if)."""
    conds = recipe["answer"].get("reject_if", [])
    if not conds:
        return sols
    var = recipe.get("var", "x")
    keep = set()
    for r in sols:
        bad = False
        for c in conds:
            try:
                bad = bad or cond(c, dict(env, **{var: r}))
            except Exception:  # noqa: BLE001  (a complex value can't be compared: reject it)
                bad = True
        if not bad:
            keep.add(r)
    return keep


def _true_solutions(recipe: dict, env: dict):
    var = _var(recipe)
    eq = _eq_expr(fill(_rel_text(recipe), env))
    dom = recipe.get("domain", "complex")
    if recipe.get("solve_by_u"):
        return _solutions_by_sub(eq, var, kb_expr(fill(recipe["solve_by_u"], env)), dom)
    return _solutions(eq, var, dom)


def _vertex(f: sp.Expr, var: sp.Symbol):
    """(h, k, 'minimum'|'maximum') for a quadratic or a |linear| function."""
    if f.has(sp.Abs):
        inner = sorted(f.atoms(sp.Abs), key=str)[0].args[0]
        h = sp.solve(sp.Eq(inner, 0), var)[0]
        k = sp.simplify(f.subs(var, h))
        up = sp.limit(f - k, var, sp.oo) == sp.oo
        return h, k, "minimum" if up else "maximum"
    p = sp.Poly(sp.expand(f), var)
    if p.degree() != 2:
        raise MathParseError(f"no vertex: not quadratic: {f}")
    a, b, _c = p.all_coeffs()
    h = -b / (2 * a)
    return h, sp.simplify(f.subs(var, h)), "minimum" if a > 0 else "maximum"


def _shape(f: sp.Expr, var: sp.Symbol) -> str:
    if f.has(sp.Abs):
        return "absolute value"
    try:
        return {1: "line", 2: "parabola"}.get(sp.Poly(sp.expand(f), var).degree(), "curve")
    except sp.PolynomialError:
        return "curve"


def _truth(recipe: dict, env: dict):
    """What SymPy says the answer is, for any task (independent of the recipe's answer)."""
    task, kind, var = _task(recipe), _kind(recipe), _var(recipe)
    if task == "solve":
        rel = fill(_rel_text(recipe), env)
        if is_inequality(rel) or kind in ("interval", "all_reals"):
            S = solution_set(rel, var, "real")
            return _reject(recipe, env, set(S)) if isinstance(S, sp.FiniteSet) else S
        return _reject(recipe, env, _true_solutions(recipe, env))
    f = kb_expr(fill(recipe["problem"]["function"], env))
    if recipe.get("domain") == "real":
        f = _real_odd_roots(f)
    if task == "vertex":
        h, k, _t = _vertex(f, var)
        return (h, k)
    if task == "axis":
        return (var, frozenset([_vertex(f, var)[0]]))
    if task == "extreme":
        _h, k, t = _vertex(f, var)
        return {"value": k, "type": t}
    if task == "range":
        return sp.calculus.util.function_range(f, var, sp.S.Reals)
    if task == "domain":
        return sp.calculus.util.continuous_domain(f, var, sp.S.Reals)
    if task == "evaluate":
        at = kb_expr(fill(str(recipe["problem"]["at"]), env))
        return frozenset([sp.simplify(f.subs(var, at))])
    if task == "graph":
        out = {"shape": _shape(f, var), "f": f}
        if out["shape"] in ("parabola", "absolute value"):
            out["vertex"] = _vertex(f, var)[:2]
        return out
    raise MathParseError(f"unknown task {task!r}")


def _graph_problems(ans: dict, truth: dict, var: sp.Symbol) -> list[str]:
    probs = []
    if ans["shape"] not in SHAPES:
        probs.append(f"unknown shape {ans['shape']!r} (use {', '.join(SHAPES)})")
    if ans["shape"] != truth["shape"]:
        probs.append(f"shape {ans['shape']!r}, but the function's graph is a {truth['shape']}")
    pts = ans["points"]
    if len(pts) < 2:
        probs.append("a graph answer needs at least 2 points")
    for p in pts:
        if len(p) != 2 or not same_value(truth["f"].subs(var, p[0]), p[1]):
            probs.append(f"point {tuple(map(kb, p))} is not on the graph")
    if "vertex" in truth and pts and len(pts[0]) == 2 and not (
            same_value(pts[0][0], truth["vertex"][0]) and same_value(pts[0][1], truth["vertex"][1])):
        probs.append("the first point must be the vertex")
    if len({tuple(map(str, p)) for p in pts}) < len(pts):
        probs.append("points repeat")
    return probs


def _same(recipe: dict, a, truth) -> bool:
    """Is answer object `a` the right answer `truth`? (value; written form is checked separately)"""
    kind, task = _kind(recipe), _task(recipe)
    if kind == "graph":
        return not _graph_problems(a, truth, _var(recipe))
    if task == "extreme":
        vals = list(a) if isinstance(a, (set, frozenset)) else [a]
        return len(vals) == 1 and same_value(vals[0], truth["value"])
    places = _places(recipe)
    if places is not None and kind in ("list", "expr"):
        try:
            A = sorted(float(sp.N(v)) for v in a)
            B = sorted(float(sp.N(v)) for v in truth)
        except TypeError:
            return False
        tol = 0.5 * 10 ** (-places) + 1e-9
        return len(A) == len(B) and all(abs(x - y) <= tol for x, y in zip(A, B))
    if kind in ("list", "none", "interval", "all_reals"):
        return same_solution_set(a, truth)
    if kind == "expr":
        return same_set(a, truth)
    if kind == "point":
        return same_answer(a, truth, "point")
    if kind == "equation":
        return same_value(a[0], truth[0]) and same_set(a[1], truth[1])
    return False


def _is_product(e: sp.Expr, var: sp.Symbol) -> bool:
    e = sp.sympify(e)
    if not isinstance(e, sp.Mul):
        return isinstance(e, sp.Pow) and e.base.has(var)
    return sum(1 for f in e.args if f.has(var)) >= 2 or any(isinstance(f, sp.Pow) and f.has(var) for f in e.args)


def _holds(rel_text: str, var: sp.Symbol, val) -> bool:
    """Does the original relation hold at var = val? (checked directly, not by the solver)"""
    from verify_math import _one_relation
    for piece in re.split(r"\bor\b", rel_text):
        r = _one_relation(piece.strip(), _real_odd_roots).subs(var, val)
        if bool(sp.simplify(r)) is True:
            return True
    return False


def _sample_points(S: sp.Set) -> list:
    pieces = S.args if isinstance(S, sp.Union) else (S,)
    pts = []
    for P in pieces:
        if P == sp.S.Reals:
            pts.append(sp.Integer(0))
        elif isinstance(P, sp.Interval):
            a, b = P.start, P.end
            if a.is_infinite and b.is_infinite:
                pts.append(sp.Integer(0))
            elif a.is_infinite:
                pts.append(b - 1)
            elif b.is_infinite:
                pts.append(a + 1)
            else:
                pts.append((a + b) / 2)
        elif isinstance(P, sp.FiniteSet):
            pts.extend(P.args)
    return pts


def check_step(step: dict, recipe: dict, env: dict, answer) -> list[str]:
    var = sp.Symbol(step.get("var", recipe.get("var", "x")))
    res = fill(step["result"], env)
    kind = step["check"]
    dom = step.get("domain", recipe.get("domain", "complex"))
    set_answer = isinstance(answer, sp.Set) and not isinstance(answer, sp.FiniteSet)
    probs = []
    try:
        if kind in ("equivalent", "factored") and (is_inequality(res) or set_answer):
            got = solution_set(res, var, "real")
            if not same_solution_set(got, answer):
                probs.append(f"not equivalent: {res} -> {got}, answer {answer}")
        elif kind in ("equivalent", "factored"):
            e = _eq_expr(res)
            got = _solutions(e, var, dom)
            if step.get("may_add"):
                if not all(any(same_value(a, g) for g in got) for a in answer):
                    probs.append(f"lost a solution: {res}")
            elif not same_set(got, answer):
                probs.append(f"not equivalent: {res} -> {sorted(map(str, got))}, answer {sorted(map(str, answer))}")
            if kind == "factored":
                lhs = kb_expr(res.split("=")[0])
                if not _is_product(lhs, var):
                    probs.append(f"not factored: {res}")
        elif kind == "pm_equation":
            if "+-" not in res:
                probs.append(f"pm_equation needs +- in the result: {res}")
            got = set()
            for v in _pm_variants(res):
                got |= _solutions(_eq_expr(v), var, dom)
            if not same_set(got, answer):
                probs.append(f"± equation doesn't give the answer: {res}")
        elif kind == "each":
            got = set()
            for part in res.split(";"):
                got |= _solutions(_eq_expr(part), var, dom)
            if step.get("may_add"):
                if not all(any(same_value(a, g) for g in got) for a in answer):
                    probs.append(f"lost a solution: {res}")
            elif not same_set(got, answer):
                probs.append(f"pieces don't give the answer: {res}")
        elif kind == "solutions":
            got = parse_keyboard(res, "list")
            if step.get("of_equation"):
                want = _solutions(_eq_expr(fill(step["of_equation"], env)), var,
                                  "complex" if dom == "complex" else "real")
            else:
                want = answer
            if not same_set(got, want):
                probs.append(f"solutions wrong: {res}")
        elif kind == "u_equation":
            u = sp.Symbol("u")
            ueq = _eq_expr(res)
            uo = kb_expr(fill(step["u"], env))
            orig = _eq_expr(fill(_rel_text(recipe), env))
            got = _solutions_by_sub(orig, var, uo, dom)
            via = set()
            for u0 in _solutions(ueq, u, "complex" if dom == "complex" else "real"):
                via |= _solutions(uo - u0, var, dom)
            via = {r for r in via if sp.simplify(orig.subs(var, r)) == 0} if dom == "real" else via
            if not same_set(got, answer) or not same_set(via, answer):
                probs.append(f"u-equation doesn't lead to the answer: {res}")
        elif kind == "values":
            for part in res.split(","):
                name, val = part.split("=")
                ref = env[step["names"][name.strip()]]
                if not same_value(kb_expr(val), ref):
                    probs.append(f"{name.strip()} should be {kb(ref)}: {res}")
        elif kind == "equal":
            a = kb_expr(res)
            b = kb_expr(fill(step["to"], env))
            if not same_value(a, b):
                probs.append(f"{res} != {fill(step['to'], env)}")
        elif kind == "substitution":
            if _task(recipe) != "solve":
                probs.append("substitution needs a solve task")
            else:
                rel = fill(_rel_text(recipe), env)
                if set_answer or is_inequality(rel):
                    for pt in _sample_points(answer):
                        if not _holds(rel, var, pt):
                            probs.append(f"{kb(pt)} is in the answer but fails {rel}")
                    outside = sp.Complement(sp.S.Reals, answer)
                    for pt in _sample_points(outside)[:3]:
                        if _holds(rel, var, pt):
                            probs.append(f"{kb(pt)} is outside the answer but satisfies {rel}")
                else:
                    orig = _eq_expr(rel)
                    o = _real_odd_roots(orig) if dom == "real" else orig
                    for a in answer:
                        if sp.simplify(o.subs(var, a)) != 0:
                            probs.append(f"{kb(a)} doesn't check")
        elif kind == "rejects":
            orig = _eq_expr(fill(_rel_text(recipe), env))
            for a in parse_keyboard(res, "list"):
                bad = sp.simplify(orig.subs(var, a)) == 0 and not recipe["answer"].get("reject_if")
                if bad:
                    probs.append(f"{kb(a)} should fail the check but solves the equation")
                if recipe["answer"].get("reject_if") and any(
                        same_value(a, t) for t in _reject(recipe, env, set(answer))):
                    probs.append(f"{kb(a)} is rejected but is in the answer")
        elif kind == "text":
            pass  # a stated sentence (e.g. the final statement); checked by answer
        else:
            probs.append(f"unknown check {kind!r}")
    except (MathParseError, KeyError, ValueError, TypeError, NotImplementedError) as exc:
        probs.append(f"error in step {step['name']!r}: {exc}")
    return [f"step {step['name']!r}: {p}" for p in probs]


def check_form(recipe: dict, env: dict) -> list[str]:
    if _kind(recipe) in ("graph", "none", "all_reals"):
        return []
    forms = recipe["answer"].get("form", [])
    probs = form_problems(fill(recipe["answer"]["value"], env), forms)
    if recipe["answer"].get("display"):
        probs += [f"display: {p}" for p in form_problems(fill(recipe["answer"]["display"], env), forms)]
    return probs


_V2_STEP_CHECKS = {"pm_equation"}


def _v2_features(recipe: dict) -> list[str]:
    used = []
    p, a = recipe.get("problem", {}), recipe.get("answer", {})
    if p.get("task", "solve") != "solve":
        used.append("problem.task")
    if is_inequality(p.get("equation") or p.get("relation") or ""):
        used.append("inequality")
    for k in ("reject_if", "display", "type"):
        if k in a:
            used.append(f"answer.{k}")
    if a.get("kind") in ("none", "all_reals", "graph"):
        used.append(f"answer kind {a['kind']}")
    if any(str(f).startswith("approx:") for f in a.get("form", [])):
        used.append("approx form")
    if any(s.get("check") in _V2_STEP_CHECKS for s in recipe.get("steps", [])):
        used.append("pm_equation step")
    if any("form_violation" in m.get("rule", {}) for m in recipe.get("mistakes", [])):
        used.append("form_violation mistake")
    return used


def _check_mistake(mk: dict, recipe: dict, env: dict, truth, k: int) -> list[str]:
    rule = mk.get("rule", {})
    out = []
    if mk.get("applies_if") and not cond(mk["applies_if"], env):
        return out
    try:
        if "answer_solves" in rule:
            if _kind(recipe) not in ("list", "none"):
                return [f"mistake {mk['id']!r}: answer_solves only fits list answers"]
            wrong = _solutions(_eq_expr(fill(rule["answer_solves"], env)), _var(recipe), "complex")
            if _same(recipe, wrong, truth):
                out.append(f"instance {k}: mistake {mk['id']!r} gives the right answer (rule would misfire)")
        elif "answer_equals" in rule:
            wrong = _answer_obj(recipe, env, rule["answer_equals"])
            if _same(recipe, wrong, truth):
                out.append(f"instance {k}: mistake {mk['id']!r} gives the right answer (rule would misfire)")
        elif "form_violation" in rule:
            form = rule["form_violation"]
            if form not in recipe["answer"].get("form", []):
                out.append(f"mistake {mk['id']!r}: form {form!r} is not in answer.form")
            ex = rule.get("example")
            if not ex:
                out.append(f"mistake {mk['id']!r}: form_violation needs an 'example' (right value, wrong form)")
            else:
                ex_text = fill(ex, env)
                if not _same(recipe, _answer_obj(recipe, env, ex), truth):
                    out.append(f"instance {k}: mistake {mk['id']!r}: example {ex_text} doesn't have the right value")
                if not form_problems(ex_text, [form]):
                    out.append(f"instance {k}: mistake {mk['id']!r}: example {ex_text} doesn't break {form}")
        elif "step_result_equals" in rule:
            pass
        else:
            out.append(f"mistake {mk.get('id')!r} has no detection rule")
    except (MathParseError, KeyError) as exc:
        out.append(f"instance {k}: mistake {mk['id']!r}: {exc}")
    if not mk.get("message"):
        out.append(f"mistake {mk.get('id')!r} has no message")
    return out


def validate_recipe(recipe: dict, n: int = 20, cards: list | None = None) -> dict:
    rid = recipe.get("id", "?")
    probs: list[str] = []
    for key in ("format", "id", "title", "section", "prerequisites", "params", "problem", "steps",
                "answer", "mistakes", "hints"):
        if key not in recipe:
            probs.append(f"missing key {key!r}")
    if recipe.get("format") not in FORMATS:
        probs.append(f"format must be one of {FORMATS}")
    if probs:
        return {"id": rid, "ok": False, "problems": probs, "instances": 0, "step_checks": 0}
    v2 = _v2_features(recipe)
    if v2 and recipe["format"] == FORMAT:
        probs.append(f"uses format-2 features ({', '.join(v2)}): set format to mathpath-recipe/2")
    task, kind = _task(recipe), _kind(recipe)
    if task not in TASKS:
        probs.append(f"unknown task {task!r} (use {', '.join(TASKS)})")
    if kind not in KINDS:
        probs.append(f"unknown answer kind {kind!r} (use {', '.join(KINDS)})")
    if task != "solve" and not recipe["problem"].get("function"):
        probs.append(f"task {task!r} needs problem.function")
    if task == "solve" and not _rel_text(recipe):
        probs.append("task solve needs problem.equation")
    if task == "evaluate" and "at" not in recipe["problem"]:
        probs.append("task evaluate needs problem.at")
    if task == "extreme" and recipe["answer"].get("type") not in ("minimum", "maximum"):
        probs.append("task extreme needs answer.type: minimum or maximum")
    if _places(recipe) is not None and "exact" in recipe["answer"].get("form", []):
        probs.append("answer forms exact and approx can't both apply")
    step_names = [s["name"] for s in recipe["steps"]]
    hint_steps = [h.get("step") for h in recipe["hints"]]
    for s in step_names:
        if s not in hint_steps:
            probs.append(f"no hint for step {s!r}")
    for h in recipe["hints"]:
        if list(k for k in h if k in ("hint", "why")) != ["hint", "why"]:
            probs.append(f"hint for {h.get('step')!r} must have 'hint' then 'why'")
    if cards is not None and recipe.get("process_card"):
        pc = [c for c in cards if c.get("kind") == "process" and recipe["process_card"] in re.sub(r"<[^>]+>", "", c["text"])]
        if not pc:
            probs.append(f"process card {recipe['process_card']!r} not found")
        else:
            blanks = [m.group(1).strip() for m in _CLOZE.finditer(pc[0]["text"])]
            if len(blanks) == 1:
                from math_cards import _item_spans
                b = blanks[0]
                blanks = [b[s:e] for s, e in _item_spans(b)]
            if blanks != step_names:
                probs.append(f"step names differ from the process card: {step_names} vs {blanks}")
    if probs:
        return {"id": rid, "ok": False, "problems": probs, "instances": 0, "step_checks": 0}
    nchecks = 0
    examples = []
    for k in range(n):
        try:
            env = instance(recipe, seed=1000 + k)
        except RuntimeError as exc:
            probs.append(str(exc))
            break
        try:
            answer = _answer_obj(recipe, env)
            truth = _truth(recipe, env)
        except (MathParseError, KeyError, ValueError, NotImplementedError) as exc:
            probs.append(f"instance {k}: {exc}")
            continue
        if kind == "graph":
            probs += [f"instance {k}: {p}" for p in _graph_problems(answer, truth, _var(recipe))]
        elif not _same(recipe, answer, truth):
            probs.append(f"instance {k}: answer {fill(recipe['answer']['value'], env)} but SymPy gets "
                         f"{_show(truth)} for {_problem_text(recipe, env)}")
        if task == "extreme" and truth["type"] != recipe["answer"].get("type"):
            probs.append(f"instance {k}: answer.type {recipe['answer'].get('type')!r} but it is a {truth['type']}")
        if recipe["answer"].get("display"):
            try:
                if not _same(recipe, _answer_obj(recipe, env, recipe["answer"]["display"]), truth):
                    probs.append(f"instance {k}: display {fill(recipe['answer']['display'], env)} != the answer")
            except MathParseError as exc:
                probs.append(f"instance {k}: display: {exc}")
        # steps work on every root; reject_if (applied problems) only trims the final answer
        step_truth = truth
        if recipe["answer"].get("reject_if") and task == "solve":
            step_truth = _truth(dict(recipe, answer=dict(recipe["answer"], reject_if=[])), env)
        for st in recipe["steps"]:
            nchecks += 1
            probs += [f"instance {k}: {p}" for p in check_step(st, recipe, env, step_truth)]
        probs += [f"instance {k}: {p}" for p in check_form(recipe, env)]
        for mk in recipe["mistakes"]:
            probs += _check_mistake(mk, recipe, env, truth, k)
        if k < 3:
            ans = recipe["answer"].get("display") or recipe["answer"]["value"]
            examples.append({"prompt": fill(recipe["problem"]["prompt"], env), "answer": fill(ans, env)})
    probs = list(dict.fromkeys(probs))
    return {"id": rid, "ok": not probs, "problems": probs[:40], "instances": n,
            "step_checks": nchecks, "examples": examples}


def _show(truth) -> str:
    if isinstance(truth, (set, frozenset)):
        return str(sorted(map(str, truth)))
    if isinstance(truth, dict):
        return str({k: v for k, v in truth.items() if k != "f"})
    return str(truth)


def _problem_text(recipe: dict, env: dict) -> str:
    if _task(recipe) == "solve":
        return fill(_rel_text(recipe), env)
    return f"{_task(recipe)} of {fill(recipe['problem']['function'], env)}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("paths", nargs="+")
    ap.add_argument("--cards")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--report")
    a = ap.parse_args()
    files = []
    for p in a.paths:
        files += sorted(glob.glob(os.path.join(p, "*.json"))) if os.path.isdir(p) else [p]
    cards = json.load(open(a.cards, encoding="utf-8")) if a.cards else None
    results = [validate_recipe(json.load(open(f, encoding="utf-8")), a.n, cards) for f in files]
    lines = ["| Recipe | Result | Instances | Step checks |", "|---|---|---|---|"]
    for r in results:
        lines.append(f"| {r['id']} | {'pass' if r['ok'] else 'FAIL'} | {r['instances']} | {r['step_checks']} |")
    for r in results:
        if r["problems"]:
            lines.append(f"\n**{r['id']}**")
            lines += [f"- {p}" for p in r["problems"]]
    lines.append("\nExamples (first 2 instances each):")
    for r in results:
        for e in r.get("examples", [])[:2]:
            lines.append(f"- {r['id']}: {e['prompt']} → {e['answer']}")
    out = "\n".join(lines)
    print(out)
    if a.report:
        open(a.report, "w", encoding="utf-8").write(out + "\n")
    sys.exit(0 if all(r["ok"] for r in results) else 1)


if __name__ == "__main__":
    main()
