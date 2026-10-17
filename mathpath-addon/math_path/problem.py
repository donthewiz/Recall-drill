"""One fresh problem from a recipe (pure, lazy SymPy).

``make_problem(recipe, seed)`` draws the parameters with the checker's own ``instance`` (a seed
replays the same problem), fills every template, and computes the truth once (``_truth``,
SymPy's independent answer, which the step checks need). The result is cached on the
:class:`Problem`; nothing is recomputed while the learner works on it.

"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass
from typing import Any

from . import loader
from .display import fill_prompt, kb_html, kb_math_html
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


def make_problem(recipe: Recipe, seed: int) -> Problem:
    """Build the problem for ``seed`` (``RuntimeError`` if the recipe has no clean instance)."""
    t0 = time.perf_counter()
    core = loader.load()
    v = core.validator
    env = v.instance(recipe.raw, seed)
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
