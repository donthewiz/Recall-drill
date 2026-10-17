"""Helpers that play the learner: type what the palette holds, press what a button sends."""

from __future__ import annotations

import itertools
from collections.abc import Callable
from pathlib import Path
from typing import Any

from math_path import loader
from math_path.notes import RecipeNote
from math_path.pages import Command
from math_path.problem import Problem, make_problem
from math_path.progress import ProgressStore
from math_path.recipe import Recipe
from math_path.run import (
    ANSWER_FIELD,
    OTHER_FIELD,
    VERTEX_FIELD,
    ProblemRun,
    step_field,
)
from math_path.session import LearnSession, ListHistory
from math_path.storage import Storage


def tex_of(text: str) -> str:
    """The LaTeX the palette would hold for keyboard ``text`` (Recall Drill's own writer); several
    ``;``-separated equations are typed with the keyboard's semicolon."""
    core = loader.load()
    if ";" in text:
        return ";".join(tex_of(part) for part in text.split(";"))
    if " or " in text:  # MathLive writes the typed letters "or" as \lor
        return " \\lor ".join(tex_of(part) for part in text.split(" or "))
    try:
        return str(core.parse.to_latex(core.parse.parse(text)))
    except core.parse.MathReadError:
        return str(core.sympy.latex(core.verify.kb_expr(text)))


def key_text(problem: Problem) -> str:
    ans = problem.recipe.raw["answer"]
    return str(loader.load().validator.fill(ans.get("display") or ans["value"], problem.env))


def type_answer(run: ProblemRun, *, right: bool = True) -> None:
    """Type the final answer: the right one, or an answer that is certainly wrong."""
    problem = run.problem
    if run.is_graph:
        parts = [p.strip() for p in str(problem.key).split(";")]
        run.choose_shape(parts[0] if right else "line" if parts[0] != "line" else "parabola")
        run.set_field(VERTEX_FIELD, tex_of(parts[1]))
        run.set_field(OTHER_FIELD, tex_of(parts[2]))
        return
    if right:
        if problem.recipe.kind in ("none", "all_reals"):
            run.choose(problem.recipe.kind)
        else:
            run.set_field(ANSWER_FIELD, tex_of(key_text(problem)))
    else:
        run.set_field(ANSWER_FIELD, "987654321")


def type_steps(run: ProblemRun, *, right: bool = True) -> None:
    for st in run.steps:
        if st.blank:
            text = run.problem.steps[st.index].result
            run.set_field(step_field(st.index), tex_of(text) if right else "123456789")


def solve(session: LearnSession, *, right: bool = True) -> None:
    """Work the current problem to its end, the way its stage asks, and press Check."""
    run = session.run
    assert run is not None, session.screen
    if run.mode == "study":
        session.command(Command("act", "next"))
        return
    if run.mode == "plan":
        for i, step in enumerate(run.problem.steps):
            run.set_plan(i, step.name if right else "something else entirely")
        session.command(Command("act", "check"))
        if not right:
            for i, step in enumerate(run.problem.steps):
                run.set_plan(i, step.name)
            session.command(Command("act", "check"))
        return
    if run.mode == "faded":
        type_steps(run, right=right)
    type_answer(run, right=right)
    session.command(Command("act", "check"))
    if not right:
        # the learner works it through to the end: right steps, right answer
        if run.mode == "faded":
            type_steps(run)
            session.command(Command("act", "check"))
        type_answer(run)
        session.command(Command("act", "check"))


def next_problem(session: LearnSession) -> None:
    session.command(Command("act", "next"))


def sequential_problems() -> Callable[[Recipe], Problem | None]:
    """A problem source: a fresh seed each call, built on the spot."""
    seeds = itertools.count(500)

    def get(recipe: Recipe) -> Problem | None:
        return make_problem(recipe, next(seeds))

    return get


def note_for(recipe: Recipe, nid: int, tags: tuple[str, ...] = ()) -> RecipeNote:
    return RecipeNote(
        nid=nid,
        recipe_id=recipe.id,
        version=recipe.version,
        title=recipe.title,
        section=recipe.section_number,
        recipe=recipe,
        error="",
        tags=tags,
        ntid=1,
        did=1,
    )


def new_store(tmp_path: Path) -> ProgressStore:
    return ProgressStore(Storage(tmp_path / "uf", "p"))


def new_session(
    tmp_path: Path, recipes: list[Recipe], st: ProgressStore | None = None, **kw: Any
) -> tuple[LearnSession, ProgressStore, ListHistory]:
    st = st or new_store(tmp_path)
    history = ListHistory()
    s = LearnSession(
        [note_for(r, 100 + i) for i, r in enumerate(recipes)],
        st,
        history,
        sequential_problems(),
        now_iso=lambda: "2026-10-17T10:00:00Z",
        **kw,
    )
    return s, st, history
