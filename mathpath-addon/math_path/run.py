"""One problem being worked, in any stage (pure).

A :class:`ProblemRun` holds everything on screen for one problem: the typed fields, each step's
state, the help ladder, the verdicts and the log of what was typed. It knows nothing about
sessions or Anki; ``session.py`` (the learn stages) and ``review.py`` (one solo problem and its
rating) drive it.

Modes:

- ``study``: a worked example. Nothing to type; ``finish_study`` ends it.
- ``faded``: some or all of the checkable steps are blank palette fields, then the final answer.
- ``plan``: one text box per step; the step names typed from memory.
- ``solo``: the problem and the answer field only.

Help ladder (Faded, Solo and reviews): per step **Hint**, then **Why**, then **Show step**; a recipe
with no hint (or no why) for a step goes straight to the next rung. In Solo and reviews the ladder
walks the recipe's steps from the first one not yet shown; in Faded it acts on the blank being
worked on. **Show answer** is the last rung, always there; it ends the problem.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from . import grading, plan_match
from .grading import AnswerVerdict, StepVerdict
from .problem import Problem

STUDY = "study"
FADED = "faded"
PLAN = "plan"
SOLO = "solo"
MODES: tuple[str, ...] = (STUDY, FADED, PLAN, SOLO)

ANSWER_FIELD = "ans"
VERTEX_FIELD = "vertex"
OTHER_FIELD = "other"
IDLE_CAP_MS = 120_000
"""The most one gap between actions counts as working time (a break doesn't)."""

HINT, WHY, SHOW, ANSWER = "hint", "why", "show", "answer"
RUNGS: tuple[str, ...] = (HINT, WHY, SHOW, ANSWER)


def step_field(index: int) -> str:
    return f"s{index}"


def plan_field(index: int) -> str:
    return f"plan{index}"


@dataclass
class StepState:
    index: int
    blank: bool = False
    """A palette field to fill in (Faded)."""
    worked: bool = False
    """Its worked result is on screen from the start."""
    typed: str = ""
    ok: bool | None = None
    wrong: int = 0
    hint_shown: bool = False
    why_shown: bool = False
    shown: bool = False
    """The "Show step" rung was used: the worked result is on screen."""
    note: str = ""
    """The latest message for this step ("Can't read that", "Not right yet")."""


def blank_set(problem: Problem, level: int) -> tuple[int, ...]:
    """Which steps Faded blanks: level 1 the last half of the checkable steps (rounded up), level 2
    all of them."""
    blanks = problem.blank_indexes
    if level >= 2 or not blanks:
        return blanks
    count = (len(blanks) + 1) // 2
    return blanks[-count:]


@dataclass
class ProblemRun:
    problem: Problem
    mode: str
    level: int = 1
    clock: Callable[[], int] = lambda: 0
    steps: list[StepState] = field(default_factory=list[StepState])
    fields: dict[str, str] = field(default_factory=dict[str, str])
    """Math field id -> LaTeX typed."""
    shape: str = ""
    answer_ok: bool | None = None
    verdict: AnswerVerdict | None = None
    wrong_tries: int = 0
    """Wrong final answers (a right value in the wrong form counts; an unfinished field doesn't)."""
    mistakes: list[str] = field(default_factory=list[str])
    plan_typed: dict[int, str] = field(default_factory=dict[int, str])
    plan_ok: dict[int, bool] = field(default_factory=dict[int, bool])
    plan_missed: set[int] = field(default_factory=set[int])
    """Boxes that were wrong at least once: the plan counts as helped."""
    plan_checked: bool = False
    help_open: bool = False
    answer_shown: bool = False
    rungs: list[str] = field(default_factory=list[str])
    """``hint:2``, ``why:2``, ``show:2``, ``answer``: every rung used, in order."""
    active_step: int | None = None
    message: str = ""
    study_done: bool = False
    log: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    active_ms: int = 0
    _last: int | None = None

    def __post_init__(self) -> None:
        if self.mode not in MODES:
            raise ValueError(f"unknown mode {self.mode!r}")
        blanks = set(blank_set(self.problem, self.level)) if self.mode == FADED else set[int]()
        first_blank = min(blanks) if blanks else len(self.problem.steps)
        for st in self.problem.steps:
            self.steps.append(
                StepState(
                    st.index,
                    blank=st.index in blanks,
                    worked=self.mode == STUDY
                    or (self.mode == FADED and st.index not in blanks and st.index < first_blank),
                )
            )
        self._last = self.clock()

    # -- time ------------------------------------------------------------------------------

    def touch(self) -> None:
        """Count the time since the last action (at most the idle cap)."""
        now = self.clock()
        if self._last is not None and not self.done:
            self.active_ms += max(0, min(now - self._last, IDLE_CAP_MS))
        self._last = now

    # -- what is on screen ----------------------------------------------------------------

    @property
    def recipe(self) -> Any:
        return self.problem.recipe

    @property
    def is_graph(self) -> bool:
        return self.problem.recipe.kind == "graph"

    @property
    def offers_choices(self) -> bool:
        """The "No solution" and "All real numbers" buttons sit by the field on every solve task."""
        return self.problem.recipe.task == "solve" and not self.is_graph

    def instruction_only(self, index: int) -> bool:
        """A step shown by its name alone: it has nothing to type, and in Faded it comes at or
        after the first blank, where showing its worked result could give the answer away."""
        step = self.problem.steps[index]
        if self.mode == STUDY or step.blankable:
            return False
        if self.mode == FADED:
            return not self.steps[index].worked
        return True

    # -- typing ------------------------------------------------------------------------------

    def set_field(self, field_id: str, latex: str) -> None:
        self.fields[field_id] = latex
        if field_id.startswith("s") and field_id[1:].isdigit():
            i = int(field_id[1:])
            if 0 <= i < len(self.steps):
                st = self.steps[i]
                if st.typed != latex and st.ok is not True:
                    st.ok = None
                    st.note = ""
                st.typed = latex
        elif field_id == ANSWER_FIELD or field_id in (VERTEX_FIELD, OTHER_FIELD):
            self.verdict = None if self.answer_ok is not True else self.verdict
            if self.answer_ok is False:
                self.answer_ok = None

    def focus(self, field_id: str) -> None:
        """The field the learner is working in (the help ladder acts on it in Faded)."""
        if field_id.startswith("s") and field_id[1:].isdigit():
            i = int(field_id[1:])
            if 0 <= i < len(self.steps) and self.steps[i].blank:
                self.active_step = i
                return
        self.active_step = None

    def choose_shape(self, shape: str) -> None:
        self.shape = shape if shape in grading.SHAPES else ""
        if self.answer_ok is not True:
            self.answer_ok = None
            self.verdict = None

    def set_plan(self, index: int, text: str) -> None:
        if self.plan_ok.get(index):
            return
        self.plan_typed[index] = text

    # -- checking ----------------------------------------------------------------------------

    @property
    def done(self) -> bool:
        if self.answer_shown:
            return True
        if self.mode == STUDY:
            return self.study_done
        if self.mode == PLAN:
            return len(self.problem.steps) == len(self.plan_ok) and all(self.plan_ok.values())
        if self.mode == FADED:
            return self.answer_ok is True and all(s.ok for s in self.steps if s.blank)
        return self.answer_ok is True

    def finish_study(self) -> None:
        if self.mode == STUDY:
            self.study_done = True

    def check_step(self, index: int) -> StepVerdict | None:
        """Check the blank for step ``index`` with the checker's own step check."""
        st = self.steps[index]
        if not st.blank or st.ok is True or self.answer_shown:
            return None
        verdict = grading.check_step_typed(self.problem, index, st.typed)
        if verdict.unreadable:
            st.note = verdict.unreadable
            return verdict
        st.ok = verdict.ok
        st.wrong += 0 if verdict.ok else 1
        st.note = "" if verdict.ok else "Not right yet."
        self.log.append({"kind": "step", "i": index, "typed": st.typed, "ok": verdict.ok})
        return verdict

    def check_answer(self) -> AnswerVerdict | None:
        if self.answer_shown or self.answer_ok is True:
            return None
        if self.is_graph:
            verdict = grading.check_graph(
                self.problem,
                self.shape,
                self.fields.get(VERTEX_FIELD, ""),
                self.fields.get(OTHER_FIELD, ""),
            )
            vertex = self.fields.get(VERTEX_FIELD, "")
            other = self.fields.get(OTHER_FIELD, "")
            typed = f"{self.shape}; {vertex}; {other}"
        else:
            typed = self.fields.get(ANSWER_FIELD, "")
            verdict = grading.check_typed(self.problem, typed)
        return self._take_answer(verdict, typed)

    def choose(self, choice: str) -> AnswerVerdict | None:
        """The "No solution" / "All real numbers" buttons."""
        if self.answer_shown or self.answer_ok is True or not self.offers_choices:
            return None
        verdict = grading.check_choice(self.problem, choice)
        self.fields[ANSWER_FIELD] = ""
        return self._take_answer(
            verdict, "no solution" if choice == grading.NONE_ANSWER else "all reals"
        )

    def _take_answer(self, verdict: AnswerVerdict, typed: str) -> AnswerVerdict:
        self.verdict = verdict
        if verdict.unreadable:
            self.answer_ok = None
            return verdict
        self.answer_ok = verdict.ok
        if not verdict.ok:
            self.wrong_tries += 1
            if verdict.mistake is not None:
                self.mistakes.append(verdict.mistake.id)
        entry: dict[str, Any] = {"kind": "answer", "typed": typed, "ok": verdict.ok}
        if verdict.mistake is not None:
            entry["mistake"] = verdict.mistake.id
        if verdict.forms:
            entry["forms"] = list(verdict.forms)
        self.log.append(entry)
        return verdict

    def check_all(self) -> None:
        """Faded's Check: every unchecked blank that has text, then the answer."""
        self.message = ""
        if self.mode == FADED:
            for st in self.steps:
                if st.blank and st.ok is not True and st.typed.strip():
                    self.check_step(st.index)
            empty = [
                s.index + 1
                for s in self.steps
                if s.blank and s.ok is not True and not s.typed.strip()
            ]
            if empty:
                self.message = "Fill in step " + ", ".join(str(n) for n in empty) + " first."
        if self.answer_ok is not True and self._answer_typed():
            self.check_answer()
        elif self.answer_ok is not True and not self.message:
            self.message = "Type your answer first."

    def _answer_typed(self) -> bool:
        if self.is_graph:
            return bool(self.shape or self.fields.get(VERTEX_FIELD) or self.fields.get(OTHER_FIELD))
        return bool(self.fields.get(ANSWER_FIELD, "").strip())

    def check_plan(self) -> None:
        """Plan's Check: each box against its step's name, in order. A wrong box is marked, shows
        the right name and is cleared to be retyped; the plan then counts as helped."""
        self.plan_checked = True
        for i, step in enumerate(self.problem.steps):
            if self.plan_ok.get(i):
                continue
            typed = self.plan_typed.get(i, "")
            if plan_match.matches(typed, step.name):
                self.plan_ok[i] = True
                self.log.append({"kind": "plan", "i": i, "typed": typed, "ok": True})
            else:
                self.plan_missed.add(i)
                self.log.append({"kind": "plan", "i": i, "typed": typed, "ok": False})
                self.plan_typed[i] = ""

    # -- help --------------------------------------------------------------------------------

    def ladder_target(self) -> int | None:
        """The step the help buttons act on, or None when every step is shown."""
        if self.mode == FADED:
            if self.active_step is not None:
                st = self.steps[self.active_step]
                if st.blank and st.ok is not True:
                    return st.index
            for st in self.steps:
                if st.blank and st.ok is not True and not st.shown:
                    return st.index
            for st in self.steps:
                if st.blank and st.ok is not True:
                    return st.index
            return None
        for st in self.steps:
            if not st.shown:
                return st.index
        return None

    def next_rung(self) -> str | None:
        """The step ladder's next rung for the target step: hint, why or show."""
        t = self.ladder_target()
        if t is None:
            return None
        st = self.steps[t]
        hint = self.recipe.hint_for(self.recipe.steps[t])
        if not st.hint_shown and hint is not None and hint.hint.strip():
            return HINT
        if not st.why_shown and hint is not None and hint.why.strip():
            return WHY
        return SHOW if not st.shown else None

    def can_help(self) -> bool:
        return self.mode in (FADED, SOLO) and not self.answer_shown and not self.done

    def use_help(self, rung: str) -> bool:
        """Climb one rung of the ladder (False when that rung isn't the next one)."""
        if not self.can_help():
            return False
        if rung == ANSWER:
            self.answer_shown = True
            self.help_open = True
            self.rungs.append(ANSWER)
            return True
        if self.next_rung() != rung:
            return False
        t = self.ladder_target()
        assert t is not None
        st = self.steps[t]
        if rung == HINT:
            st.hint_shown = True
        elif rung == WHY:
            st.why_shown = True
        else:
            st.shown = True
        self.rungs.append(f"{rung}:{t}")
        self.help_open = True
        return True

    def close_help(self) -> None:
        self.help_open = False

    # -- outcome ------------------------------------------------------------------------------

    @property
    def helped(self) -> bool:
        """Any rung of the ladder was used (or, in Plan, a box was wrong)."""
        return bool(self.rungs) or bool(self.plan_missed)

    @property
    def used_show(self) -> bool:
        """A step or the answer was shown: more than a nudge."""
        return self.answer_shown or any(r.startswith(f"{SHOW}:") for r in self.rungs)

    @property
    def unaided_right(self) -> bool:
        """Right with no help and no wrong try: what passes Faded and counts as an unaided solo."""
        if not self.done or self.answer_shown:
            return False
        if self.mode == PLAN:
            return not self.plan_missed
        if self.mode == FADED:
            return (
                not self.rungs
                and self.wrong_tries == 0
                and all(s.wrong == 0 for s in self.steps if s.blank)
            )
        return not self.rungs and self.wrong_tries == 0

    def history_line(self) -> dict[str, Any]:
        """What the history keeps about this problem (the session adds its own keys)."""
        return {
            "seed": self.problem.seed,
            "recipe": self.problem.recipe.id,
            "version": self.problem.recipe.version,
            "stage": self.mode,
            "level": self.level if self.mode == FADED else None,
            "typed": list(self.log),
            "mistakes": list(self.mistakes),
            "help": list(self.rungs),
            "active_ms": self.active_ms,
            "right": self.answer_ok is True,
        }
