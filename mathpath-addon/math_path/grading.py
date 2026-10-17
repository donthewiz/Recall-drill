"""Checking what the learner typed (pure, lazy SymPy). A thin wrapper over the copied checker.

The core files are never edited; this module only calls them:

- the final answer: ``verify_math.check_answer(typed, key, kind, forms)`` (value first, then the
  written form on the text as typed); right only when ``ok``. A right value with form problems
  is "Right value, but ..." and does not count;
- named mistakes: the recipe's ``mistakes`` in order, compared with the core's own
  ``_answer_obj`` / ``_same`` / ``_solutions`` (no second checker);
- a typed step: ``recipe_validator.check_step`` with the learner's text in place of the recipe's
  ``result``, passed through the environment so a ``{`` in the answer is never read as a template;
- a graph answer typed as a shape and two points: ``parse_graph`` / ``_graph_problems``.

Nothing here reveals the answer: the core's messages name the right value, so they are never shown.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, cast

from . import loader
from .palette import UnreadableAnswer, palette_to_keyboard
from .problem import Problem
from .recipe import Mistake

TYPED = "mp_typed"
"""The environment name that carries the learner's text into the checker's templates."""

SHAPES: tuple[str, ...] = ("parabola", "line", "absolute value")
"""The three shapes the graph answer offers (v0.1 types the graph; a drawn tool is later)."""

NONE_ANSWER = "none"
ALL_REALS_ANSWER = "all_reals"

_FORM_WORDS: tuple[tuple[str, str], ...] = (
    (r"^fraction not reduced", "the fraction isn't reduced"),
    (r"^radical not simplified", "the radical isn't simplified"),
    (r"^not exact", "the answer should be exact, not a decimal"),
    (
        r"^square root of a negative",
        "a square root of a negative number is left in: write it with i",
    ),
    (r"^not interval notation", "write the answer in interval notation"),
    (r"^not rounded to (\d+) decimal places", r"round to \1 decimal places"),
)
_FORM_SENTINEL = "the answer isn't written in the form the problem asks for"


def form_words(problems: list[str]) -> tuple[str, ...]:
    """The checker's form problems in plain words (the numbers it names are dropped)."""
    out: list[str] = []
    for p in problems:
        for pattern, words in _FORM_WORDS:
            m = re.match(pattern, p)
            if m:
                out.append(m.expand(words))
                break
        else:
            out.append(_FORM_SENTINEL)
    return tuple(dict.fromkeys(out))


@dataclass(frozen=True)
class AnswerVerdict:
    ok: bool
    value_ok: bool = False
    forms: tuple[str, ...] = ()
    """The form problems, in plain words (non-empty only for a right value in the wrong form)."""
    mistake: Mistake | None = None
    unreadable: str = ""
    """Why the input couldn't be read at all (an unfinished fraction...). Not a wrong try."""
    graph_problems: tuple[str, ...] = field(default=())

    @property
    def counts_as_try(self) -> bool:
        return not self.unreadable

    @property
    def headline(self) -> str:
        if self.unreadable:
            return self.unreadable
        if self.ok:
            return "Right."
        if self.value_ok and self.forms:
            return "Right value, but " + "; ".join(self.forms) + "."
        if self.graph_problems:
            return "Not right yet: " + " ".join(self.graph_problems)
        return "Not right yet."


@dataclass(frozen=True)
class StepVerdict:
    ok: bool
    unreadable: str = ""

    @property
    def counts_as_try(self) -> bool:
        return not self.unreadable


# -- final answers ------------------------------------------------------------------------------


def check_typed(problem: Problem, latex: str) -> AnswerVerdict:
    """Grade the palette field's LaTeX as the problem's final answer."""
    try:
        typed = palette_to_keyboard(latex)
    except UnreadableAnswer as exc:
        return AnswerVerdict(False, unreadable=str(exc))
    return check_keyboard(problem, typed)


def _with_typed(problem: Problem, typed: str) -> dict[str, Any]:
    env = dict(problem.env)
    env[TYPED] = typed
    return env


def _typed_object(problem: Problem, typed: str) -> Any:
    """The typed answer as the checker's comparable object, or None if it can't be read."""
    core = loader.load()
    try:
        return core.validator._answer_obj(
            problem.recipe.raw, _with_typed(problem, typed), "{" + TYPED + "}"
        )
    except Exception:  # noqa: BLE001 (any parse failure just means "no mistake can match")
        return None


def _var(problem: Problem) -> str:
    v = problem.recipe.raw.get("var", "x")
    return v if isinstance(v, str) and v else "x"


def _top_split(text: str, sep: str = ",") -> list[str]:
    """Split at ``sep`` outside any bracket (an interval's comma stays inside its piece)."""
    parts: list[str] = []
    depth = 0
    start = 0
    for i, ch in enumerate(text):
        if ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
        elif ch == sep and depth == 0:
            parts.append(text[start:i])
            start = i + 1
    parts.append(text[start:])
    return parts


def drop_var_labels(typed: str, var: str) -> str:
    """``x = -5/2, x = -9`` is the list ``-5/2, -9`` (built after review, 2026-10-17).

    Only when *every* piece is ``<var> = <value>`` with nothing else relational in the value;
    anything else is returned unchanged."""
    label = re.compile(rf"^\s*{re.escape(var)}\s*=\s*(.+?)\s*$")
    values: list[str] = []
    for piece in _top_split(typed):
        m = label.match(piece)
        if m is None or any(op in m.group(1) for op in ("=", "<", ">")):
            return typed
        values.append(m.group(1))
    return ", ".join(values)


def commas_between_equations(typed: str) -> str:
    """``2x+5=0, x+9=0`` is ``2x+5=0; x+9=0`` for an "each" step: the palette has a comma but
    no semicolon (built after review, 2026-10-17). Unchanged unless every piece is one equation."""
    if ";" in typed:
        return typed
    pieces = _top_split(typed)
    if len(pieces) < 2 or any(p.count("=") != 1 for p in pieces):
        return typed
    return "; ".join(p.strip() for p in pieces)


def check_keyboard(problem: Problem, typed: str) -> AnswerVerdict:
    """Grade keyboard-form text as the final answer (the palette path ends here)."""
    recipe = problem.recipe
    core = loader.load()
    if recipe.kind in ("list", "expr"):
        typed = drop_var_labels(typed, _var(problem))
    if recipe.kind == "graph":
        return AnswerVerdict(False, unreadable="Use the shape and point fields for a graph answer.")
    if recipe.kind in ("none", "all_reals"):
        obj = _typed_object(problem, typed)
        if obj is None:
            return AnswerVerdict(
                False, unreadable="That can't be read as math. Check the brackets."
            )
        value_ok = _same(problem, obj, problem.truth)
        return _verdict(problem, typed, obj, value_ok, ())
    try:
        res = core.verify.check_answer(typed, problem.key, recipe.kind, list(recipe.forms))
        value_ok = bool(res["value_ok"])
        form_problems: list[str] = list(res["form_problems"])
    except Exception:  # noqa: BLE001 (the checker raises ValueError on a malformed interval)
        value_ok, form_problems = False, []
    obj = None if value_ok else _typed_object(problem, typed)
    return _verdict(problem, typed, obj, value_ok, tuple(form_problems))


def check_choice(problem: Problem, choice: str) -> AnswerVerdict:
    """The "No solution" / "All real numbers" buttons (shown on every solve task)."""
    core = loader.load()
    obj: Any = set[Any]() if choice == NONE_ANSWER else core.sympy.S.Reals
    value_ok = problem.recipe.kind == choice and _same(problem, obj, problem.truth)
    typed = "no solution" if choice == NONE_ANSWER else "all reals"
    return _verdict(problem, typed, obj, value_ok, ())


def _verdict(
    problem: Problem, typed: str, obj: Any, value_ok: bool, form_problems: tuple[str, ...]
) -> AnswerVerdict:
    forms = form_words(list(form_problems))
    if value_ok and not form_problems:
        return AnswerVerdict(True, True)
    broken: set[str] = _broken_forms(problem, typed) if value_ok else set[str]()
    mistake = _find_mistake(problem, typed, obj, value_ok, broken)
    return AnswerVerdict(False, value_ok, forms, mistake)


def _broken_forms(problem: Problem, typed: str) -> set[str]:
    core = loader.load()
    out: set[str] = set()
    for form in problem.recipe.forms:
        try:
            if core.verify.form_problems(typed, [form]):
                out.add(form)
        except Exception:  # noqa: BLE001
            continue
    return out


def _same(problem: Problem, a: Any, b: Any) -> bool:
    """Is answer object ``a`` the answer object ``b`` (value only)? Uses the core's comparison."""
    core = loader.load()
    recipe = problem.recipe
    try:
        if recipe.kind == "graph":
            return _same_graph(a, b)
        if recipe.task == "extreme":
            return bool(core.verify.same_set(_as_set(a), _as_set(b)))
        return bool(core.validator._same(recipe.raw, a, b))
    except Exception:  # noqa: BLE001
        return False


def _as_set(v: Any) -> Any:
    if isinstance(v, (set, frozenset)):
        return cast(Any, v)
    return frozenset[Any]([v])


def _same_graph(a: Any, b: Any) -> bool:
    core = loader.load()
    if a["shape"] != b["shape"] or len(a["points"]) != len(b["points"]):
        return False
    return all(
        len(p) == len(q) and all(core.verify.same_value(x, y) for x, y in zip(p, q, strict=True))
        for p, q in zip(a["points"], b["points"], strict=True)
    )


def _find_mistake(
    problem: Problem, typed: str, obj: Any, value_ok: bool, broken: set[str]
) -> Mistake | None:
    """The first of the recipe's named mistakes that matches this answer."""
    core = loader.load()
    v = core.validator
    recipe = problem.recipe
    for mk in recipe.mistakes:
        try:
            if mk.applies_if and not v.cond(mk.applies_if, problem.env):
                continue
            rule = mk.rule
            if "form_violation" in rule:
                if value_ok and rule["form_violation"] in broken:
                    return mk
                continue
            if value_ok or obj is None:
                continue
            if "answer_equals" in rule:
                wrong = v._answer_obj(recipe.raw, problem.env, rule["answer_equals"])
                if _same(problem, obj, wrong):
                    return mk
            elif "answer_solves" in rule:
                eq = v._eq_expr(v.fill(rule["answer_solves"], problem.env))
                wrong = v._solutions(eq, v._var(recipe.raw), "complex")
                if _same(problem, obj, wrong):
                    return mk
        except Exception:  # noqa: BLE001 (a rule that can't be evaluated here simply doesn't match)
            continue
    return None


# -- graph answers --------------------------------------------------------------------------------


def check_graph(problem: Problem, shape: str, vertex_latex: str, other_latex: str) -> AnswerVerdict:
    """Grade a graph answer typed as a shape chip plus two palette points."""
    core = loader.load()
    if shape not in SHAPES:
        return AnswerVerdict(False, unreadable="Pick the shape of the graph first.")
    try:
        vertex = palette_to_keyboard(vertex_latex)
        other = palette_to_keyboard(other_latex)
    except UnreadableAnswer as exc:
        return AnswerVerdict(False, unreadable=str(exc))
    typed = f"{shape}; {vertex}; {other}"
    try:
        ans = core.validator.parse_graph(typed)
    except Exception:  # noqa: BLE001
        return AnswerVerdict(False, unreadable="Write each point as (x, y).")
    if any(len(p) != 2 for p in ans["points"]):
        return AnswerVerdict(False, unreadable="Write each point as (x, y).")
    try:
        probs: list[str] = core.validator._graph_problems(
            ans, problem.truth, core.validator._var(problem.recipe.raw)
        )
    except Exception:  # noqa: BLE001
        probs = ["not right"]
    if not probs:
        return AnswerVerdict(True, True)
    mistake = _find_mistake(problem, typed, ans, False, set())
    return AnswerVerdict(False, False, (), mistake, graph_problems=_graph_words(probs))


def _graph_words(problems: list[str]) -> tuple[str, ...]:
    out: list[str] = []
    for p in problems:
        if p.startswith("shape") or p.startswith("unknown shape"):
            out.append("That isn't the shape of this graph.")
        elif p.startswith("point"):
            out.append("A point you gave is not on the graph.")
        elif "vertex" in p:
            out.append("The vertex isn't right.")
        elif "repeat" in p:
            out.append("Use two different points.")
        elif "at least 2" in p:
            out.append("Give the vertex and one more point.")
    return tuple(dict.fromkeys(out))


# -- steps ----------------------------------------------------------------------------------------


def check_step_typed(problem: Problem, index: int, latex: str) -> StepVerdict:
    """Grade the palette text typed for step ``index`` with the checker's own step check."""
    try:
        typed = palette_to_keyboard(latex)
    except UnreadableAnswer as exc:
        return StepVerdict(False, str(exc))
    return check_step_keyboard(problem, index, typed)


def check_step_keyboard(problem: Problem, index: int, typed: str) -> StepVerdict:
    core = loader.load()
    step = problem.recipe.steps[index]
    if not step.blankable:
        return StepVerdict(True)
    if step.check == "each":
        typed = commas_between_equations(typed)
    elif step.check == "solutions":
        var = step.raw.get("var", _var(problem))
        typed = drop_var_labels(typed, var if isinstance(var, str) and var else _var(problem))
    as_typed = dict(step.raw, result="{" + TYPED + "}")
    try:
        problems: list[str] = core.validator.check_step(
            as_typed, problem.recipe.raw, _with_typed(problem, typed), problem.step_truth
        )
    except Exception:  # noqa: BLE001 (anything the checker can't evaluate is simply not right)
        problems = ["error"]
    return StepVerdict(not problems)
