"""A review: one fresh Solo problem for a due Math Path card, and the rating it earns (pure).

When Anki's reviewer shows a Math Path card, the window opens on one fresh problem in Solo mode
(no stages: Anki owns scheduling). When it is finished the done screen says how it went and which
Anki rating Math Path picked; the four rating chips change it; **Next** applies it to *that* card
through the reviewer's normal answer path and the reviewer moves on. Closing the window without
finishing rates nothing.

=================================================  ======
What happened                                      Rating
=================================================  ======
right on the first try, no help                    Good
right after Hint/Why only (no wrong try)           Hard
a wrong try (even if then fixed), Show step or
Show answer used, or gave up                       Again
=================================================  ======

Easy is never picked automatically (it is one click away).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from .notes import RecipeNote
from .pages import Command
from .problem import Problem
from .recipe import Recipe
from .run import ANSWER_FIELD, SOLO, ProblemRun
from .session import HistorySink

AGAIN, HARD, GOOD, EASY = 1, 2, 3, 4
RATINGS: tuple[int, ...] = (AGAIN, HARD, GOOD, EASY)
RATING_NAMES: dict[int, str] = {AGAIN: "Again", HARD: "Hard", GOOD: "Good", EASY: "Easy"}

PREPARING = "preparing"
RUN = "run"
DONE = "done"

EFFECT_NONE = ""
EFFECT_RATE = "rate"
"""Apply :attr:`ReviewSession.rating` to the card through the reviewer, then close the window."""
EFFECT_CLOSE = "close"


def suggested_rating(run: ProblemRun) -> int:
    """The rating the table above gives a finished problem (never Easy)."""
    if run.used_show or run.answer_shown or run.wrong_tries > 0:
        return AGAIN
    if run.rungs:
        return HARD
    return GOOD


def outcome_text(run: ProblemRun) -> str:
    """One line for the done screen on how it went."""
    if run.answer_shown:
        return "You gave up and looked at the answer."
    if any(r.startswith("show:") for r in run.rungs):
        return "Right, but a step was shown."
    tries = run.wrong_tries
    helped = bool(run.rungs)
    if tries and helped:
        return f"Right after {_tries(tries)} and a hint."
    if tries:
        return f"Right after {_tries(tries)}."
    if helped:
        return "Right, with a hint."
    return "Right on the first try, no help."


def _tries(n: int) -> str:
    return "a wrong try" if n == 1 else f"{n} wrong tries"


@dataclass
class ReviewSession:
    """The state of one review window."""

    note: RecipeNote
    card_id: int
    get_problem: Callable[[Recipe], Problem | None]
    history: HistorySink
    clock: Callable[[], int] = lambda: 0
    now_iso: Callable[[], str] = lambda: ""

    def __post_init__(self) -> None:
        assert self.note.recipe is not None
        self.recipe: Recipe = self.note.recipe
        self.run: ProblemRun | None = None
        self.screen = PREPARING
        self.rating: int = GOOD
        self.suggested: int = GOOD
        self.focus_id = ANSWER_FIELD
        self.applied = False
        self.not_rated_reason = ""
        self._logged = False
        self.problem_ready()

    # -- the problem -----------------------------------------------------------------------

    def problem_ready(self) -> bool:
        if self.screen != PREPARING:
            return False
        problem = self.get_problem(self.recipe)
        if problem is None:
            return False
        self.run = ProblemRun(problem, SOLO, 1, self.clock)
        self.screen = RUN
        return True

    # -- commands --------------------------------------------------------------------------

    def command(self, cmd: Command) -> str:
        run = self.run
        if run is not None and self.screen == RUN:
            run.touch()
        if cmd.kind == "focus":
            self.focus_id = cmd.a
            return EFFECT_NONE
        if cmd.kind == "field" and run is not None and self.screen == RUN:
            run.set_field(cmd.a, cmd.b)
            return EFFECT_NONE
        if cmd.kind == "esc":
            if run is not None:
                run.close_help()
            return EFFECT_NONE
        if cmd.kind == "enter" or cmd.kind == "ctrl-enter":
            if self.screen == DONE:
                return self._next()
            if cmd.kind == "enter":
                return self._check()
            return EFFECT_NONE
        if cmd.kind == "act":
            return self._act(cmd.a, cmd.b)
        return EFFECT_NONE

    def _act(self, name: str, arg: str) -> str:
        run = self.run
        if name == "next":
            return self._next()
        if name == "close":
            return EFFECT_CLOSE
        if name == "rate" and self.screen == DONE and arg.isdigit() and int(arg) in RATINGS:
            self.rating = int(arg)
            return EFFECT_NONE
        if run is None or self.screen != RUN:
            return EFFECT_NONE
        if name == "check":
            return self._check()
        if name == "choose":
            run.choose(arg)
        elif name == "shape":
            run.choose_shape(arg)
        elif name == "help":
            run.use_help(arg)
        elif name == "close_help":
            run.close_help()
        self._after()
        return EFFECT_NONE

    def _check(self) -> str:
        run = self.run
        if run is None or self.screen != RUN:
            return EFFECT_NONE
        run.message = ""
        run.check_answer()
        self._after()
        return EFFECT_NONE

    def _after(self) -> None:
        run = self.run
        if run is not None and run.done and self.screen == RUN:
            run.touch()
            self.suggested = suggested_rating(run)
            self.rating = self.suggested
            self.screen = DONE

    def _next(self) -> str:
        return EFFECT_RATE if self.screen == DONE else EFFECT_NONE

    # -- finishing ---------------------------------------------------------------------------

    @property
    def finished(self) -> bool:
        return self.screen == DONE

    def applied_rating(self, ok: bool, reason: str = "") -> None:
        """The window tells us whether the reviewer took the rating (``ok``) or why not."""
        self.applied = ok
        self.not_rated_reason = reason
        self.log()

    def log(self) -> None:
        """Write the history line (once): only for a problem that was finished."""
        run = self.run
        if run is None or self._logged or not run.done:
            return
        self._logged = True
        self.history.append(
            {
                "type": "problem",
                "ts": self.now_iso(),
                "nid": self.note.nid,
                "cid": self.card_id,
                "mode": "review",
                **run.history_line(),
                "stage": SOLO,
                "suggested": self.suggested,
                "rating": self.rating if self.applied else None,
                "rated": self.applied,
            }
        )

    def result(self) -> dict[str, Any]:
        return {"rating": self.rating, "applied": self.applied}
