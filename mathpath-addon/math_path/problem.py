"""One fresh problem from a recipe (pure, lazy SymPy).

``make_problem(recipe, seed)`` draws the parameters with the checker's own ``instance`` (a seed
replays the same problem), fills every template, and computes the truth once (``_truth``,
SymPy's independent answer, which the step checks need). The result is cached on the
:class:`Problem`; nothing is recomputed while the learner works on it.

``ProblemBank`` keeps one problem per recipe ready ahead of time, built on a worker thread.
"""

from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass
from fractions import Fraction
from typing import Any

from . import loader
from .display import fill_prompt, kb_html, kb_math_html
from .fastgen import Prefilter
from .recipe import Recipe, Step


@dataclass(frozen=True)
class ProblemStep:
    index: int
    name: str
    check: str
    blankable: bool
    result: str
    """The worked result, filled, in keyboard form (``""`` for a step with nothing to compute)."""
    shown_html: str
    """What the step shows when it is worked: ``show`` (or ``result``) as MathJax and prose."""


@dataclass(frozen=True)
class Problem:
    recipe: Recipe
    seed: int
    prompt_html: str
    steps: tuple[ProblemStep, ...]
    key: str
    """The filled ``answer.value`` (keyboard form): what the answer is compared with."""
    answer_html: str
    """The answer in course notation (``answer.display`` when the recipe has it), as MathJax."""
    env: dict[str, Any]
    truth: Any
    step_truth: Any
    """The truth the step checks use: ``answer.reject_if`` only trims the *final* answer."""
    gen_ms: float

    @property
    def blank_indexes(self) -> tuple[int, ...]:
        return tuple(s.index for s in self.steps if s.blankable)


def new_seed(rng: random.Random | None = None) -> int:
    return (rng or random.SystemRandom()).randrange(1, 2**31 - 1)


def _answer_html(recipe: Recipe, env: dict[str, Any]) -> str:
    core = loader.load()
    fill = core.validator.fill
    ans = recipe.raw["answer"]
    if recipe.kind == "none":
        return "No solution"
    if recipe.kind == "all_reals":
        return "All real numbers"
    if recipe.kind == "graph":
        parts = [p.strip() for p in str(fill(ans["value"], env)).split(";") if p.strip()]
        shape = parts[0].capitalize() if parts else "Graph"
        bits = [shape]
        labels = ("vertex", "another point")
        for label, point in zip(labels, parts[1:], strict=False):
            bits.append(f"{label} {kb_math_html(point)}")
        return " · ".join(bits)
    text = str(fill(ans.get("display") or ans["value"], env))
    return kb_math_html(text)


def _fraction(value: Any) -> Fraction | None:
    """A SymPy number as an exact fraction (None for anything that isn't a rational)."""
    try:
        if getattr(value, "is_Rational", False):
            return Fraction(int(value.p), int(value.q))
    except (TypeError, ValueError):
        return None
    return None


def draw_instance(recipe: Recipe, seed: int, tries: int = 2000) -> dict[str, Any]:
    """``recipe_validator.instance(recipe, seed)``, with an exact quick pre-filter in front of
    the SymPy work (``fastgen``): the same draw sequence, so the same instance for a seed, found
    sooner when the recipe's constraints reject most draws."""
    core = loader.load()
    v = core.validator
    mpe = core.verify.MathParseError
    raw = recipe.raw
    lets: dict[str, str] = dict(raw.get("let", {}))
    constraints: list[str] = list(raw.get("constraints", []))
    pre = Prefilter.for_recipe(lets, constraints)
    var = raw.get("var", "x")
    rnd = random.Random(seed)
    for _ in range(tries):
        env = v.draw_params(raw["params"], rnd)
        exact = {k: f for k, val in env.items() if (f := _fraction(val)) is not None}
        if pre.rejects(exact):
            continue
        try:
            env = v.derive(lets, env, var)
        except (mpe, ZeroDivisionError):
            continue
        ok = True
        for c in constraints:
            try:
                if not v.cond(c, env):
                    ok = False
                    break
            except Exception:  # noqa: BLE001 (as the checker: a constraint that can't be evaluated fails)
                ok = False
                break
        if ok:
            return env
    raise RuntimeError(f"{recipe.id}: no clean instance in {tries} tries (seed {seed})")


def make_problem(recipe: Recipe, seed: int) -> Problem:
    """Build the problem for ``seed`` (``RuntimeError`` if the recipe has no clean instance)."""
    t0 = time.perf_counter()
    core = loader.load()
    v = core.validator
    env = draw_instance(recipe, seed)
    truth = v._truth(recipe.raw, env)
    answer = recipe.raw["answer"]
    step_truth = truth
    if answer.get("reject_if") and recipe.task == "solve":
        relaxed = dict(recipe.raw, answer=dict(answer, reject_if=[]))
        step_truth = v._truth(relaxed, env)
    steps: list[ProblemStep] = []
    for i, st in enumerate(recipe.steps):
        steps.append(_problem_step(i, st, env))
    return Problem(
        recipe=recipe,
        seed=seed,
        prompt_html=fill_prompt(recipe.raw["problem"]["prompt"], env),
        steps=tuple(steps),
        key=str(v.fill(answer["value"], env)),
        answer_html=_answer_html(recipe, env),
        env=env,
        truth=truth,
        step_truth=step_truth,
        gen_ms=(time.perf_counter() - t0) * 1000.0,
    )


def _problem_step(index: int, st: Step, env: dict[str, Any]) -> ProblemStep:
    v = loader.load().validator
    result = str(v.fill(st.result, env)) if st.result else ""
    shown = str(v.fill(st.show, env)) if st.show else result
    return ProblemStep(
        index=index,
        name=st.name,
        check=st.check,
        blankable=st.blankable,
        result=result,
        shown_html=kb_html(shown) if shown else "",
    )


def example_prompt_html(recipe: Recipe, seed: int = 1000) -> str:
    """The example problem for the note's ``Prompt`` field (a MathJax string)."""
    return make_problem(recipe, seed).prompt_html


def smoke_test(recipe: Recipe, seeds: tuple[int, ...] = (1000, 1001, 1002)) -> None:
    """Generate a few instances; raises on the first that fails (the import's smoke test)."""
    for seed in seeds:
        make_problem(recipe, seed)


class ProblemBank:
    """One prepared problem per recipe id, built on a worker thread.

    ``prepare(recipe)`` starts a background build if none is ready or running; ``take(recipe)``
    returns the ready problem (and starts the next build), or None when it isn't ready yet.
    ``take_blocking`` waits for it (used off the UI thread by tests and the first problem)."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._ready: dict[str, Problem] = {}
        self._running: dict[str, threading.Thread] = {}
        self._failed: dict[str, str] = {}
        self.listeners: list[Any] = []

    def _build(self, recipe: Recipe) -> None:
        try:
            problem = make_problem(recipe, new_seed())
            with self._lock:
                self._ready[recipe.id] = problem
        except Exception as exc:  # noqa: BLE001 (a broken recipe must not kill the thread silently)
            with self._lock:
                self._failed[recipe.id] = f"{type(exc).__name__}: {exc}"
        finally:
            with self._lock:
                self._running.pop(recipe.id, None)
            for fn in list(self.listeners):
                fn(recipe.id)

    def prepare(self, recipe: Recipe) -> None:
        with self._lock:
            if recipe.id in self._ready or recipe.id in self._running:
                return
            self._failed.pop(recipe.id, None)
            t = threading.Thread(target=self._build, args=(recipe,), daemon=True)
            self._running[recipe.id] = t
        t.start()

    def is_ready(self, recipe: Recipe) -> bool:
        with self._lock:
            return recipe.id in self._ready

    def failure(self, recipe: Recipe) -> str | None:
        with self._lock:
            return self._failed.get(recipe.id)

    def take(self, recipe: Recipe) -> Problem | None:
        with self._lock:
            problem = self._ready.pop(recipe.id, None)
        self.prepare(recipe)  # the next one, while the learner works on this
        return problem

    def take_blocking(self, recipe: Recipe, timeout: float = 60.0) -> Problem:
        self.prepare(recipe)
        with self._lock:
            t = self._running.get(recipe.id)
        if t is not None:
            t.join(timeout)
        failure = self.failure(recipe)
        if failure is not None:
            raise RuntimeError(failure)
        problem = self.take(recipe)
        if problem is None:
            raise RuntimeError("the problem could not be built")
        return problem
