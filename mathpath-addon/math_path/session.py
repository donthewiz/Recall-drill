"""The learn session: which recipes, and the stages each goes through (pure).

``pick_for_session`` chooses up to ``problems_per_session`` recipes of a section: not learned, not
locked, ordered prerequisites first, then priority (high to low), then note order.

:class:`LearnSession` takes each through **Study → Faded → Plan → Solo → Learned**, one problem per
turn, **interleaved**: after one recipe's turn the next recipe gets one, so a recipe's two solos are
separated by problems of other recipes. When only one recipe is left the second solo follows
directly (``docs/DECISIONS.md``). Every finished problem saves the stage (``progress.json``) and a
history line, so a closed window resumes at the same stage with a fresh problem.

======  =======================================================================================
Stage   Passes when
======  =======================================================================================
Study   always (one worked example per recipe)
Faded   level 1 (last half of the checkable steps blank), then level 2 (all blank): done with no
        help and no wrong answer. Help or a wrong answer repeats the level with a fresh problem;
        after 3 tries the recipe moves on, marked "needed help".
Plan    every step name right (a wrong one is shown and retyped, and counts as help: Plan again)
Solo    2 unaided right solos with another problem between them. Any wrong answer or help sends the
        recipe back to Faded level 2 and the count restarts.
======  =======================================================================================
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from . import run as runmod
from .config import Config
from .notes import RecipeNote
from .pages import Command
from .problem import Problem
from .progress import (
    FADED,
    LEARNED,
    MAX_FADED_TRIES,
    PLAN,
    SOLO,
    SOLOS_TO_LEARN,
    STAGE_LABELS,
    STUDY,
    NoteProgress,
    ProgressStore,
)
from .recipe import Recipe
from .run import ANSWER_FIELD, ProblemRun, plan_field, step_field

# -- choosing the recipes ----------------------------------------------------------------------


def is_learned(note: RecipeNote, progress: Mapping[int, NoteProgress]) -> bool:
    """Learned in the learn session (``progress.json``) or handed off (the ``mp::learned`` tag,
    which syncs from another device)."""
    have = progress.get(note.nid)
    return note.learned_tag or (have is not None and have.is_learned)


def locked_by(
    note: RecipeNote,
    notes: Sequence[RecipeNote],
    progress: Mapping[int, NoteProgress],
    cfg: Config,
) -> list[str]:
    """The titles of the prerequisite recipes that block this one (empty: not locked).

    A prerequisite id that exists as a Math Path note and isn't learned blocks; an id with no note
    is ignored. With ``prereq_lock`` off nothing is locked."""
    if not cfg.prereq_lock or note.recipe is None:
        return []
    by_id = {n.recipe_id: n for n in notes}
    needs: list[str] = []
    for rid in note.recipe.prerequisites:
        pre = by_id.get(rid)
        if pre is not None and pre.nid != note.nid and not is_learned(pre, progress):
            needs.append(pre.title or rid)
    return needs


def pick_for_session(
    section_notes: Sequence[RecipeNote],
    all_notes: Sequence[RecipeNote],
    progress: Mapping[int, NoteProgress],
    cfg: Config,
    limit: int | None = None,
) -> list[RecipeNote]:
    """Up to ``limit`` (default ``problems_per_session``) recipes of a section to learn, in order.

    Only notes with a readable recipe that aren't learned and aren't locked are candidates. The
    order is prerequisites first (among the candidates), then priority, then note order."""
    n = cfg.problems_per_session if limit is None else limit
    pool = [
        note
        for note in section_notes
        if note.recipe is not None
        and not is_learned(note, progress)
        and not locked_by(note, all_notes, progress, cfg)
    ]
    return learn_order(pool, n)


def learn_order(notes: Sequence[RecipeNote], limit: int | None = None) -> list[RecipeNote]:
    """``notes`` in the order a learn session takes them: prerequisites first (among these
    notes), then priority, then note order (the map shows a section's chips in this order too)."""
    n = len(notes) if limit is None else limit
    pool = sorted(notes, key=lambda x: x.nid)
    ids = {x.recipe_id for x in pool}
    ordered: list[RecipeNote] = []
    done: set[str] = set()
    remaining = sorted(pool, key=lambda x: (x.recipe.priority_rank if x.recipe else 1, x.nid))
    while remaining and len(ordered) < n:
        ready = [
            x
            for x in remaining
            if x.recipe is None
            or all(p not in ids or p in done for p in x.recipe.prerequisites if p != x.recipe_id)
        ]
        nxt = (ready or remaining)[0]  # a prerequisite cycle: take the first anyway
        ordered.append(nxt)
        done.add(nxt.recipe_id)
        remaining.remove(nxt)
    return ordered


# -- the session ---------------------------------------------------------------------------------


@dataclass
class SessionItem:
    note: RecipeNote
    recipe: Recipe
    progress: NoteProgress
    start_stage: str
    turns: int = 0
    time_ms: int = 0
    helped: bool = False
    needed_help: bool = False
    first_solo_turn: int | None = None
    """The turn number of the unaided solo counted this session (None: none yet, or it was in an
    earlier session, where the gap to now is certain)."""
    finished: bool = False

    @property
    def title(self) -> str:
        return self.note.title or self.recipe.title


@dataclass(frozen=True)
class TurnResult:
    """What the done screen says about a finished problem."""

    ok: bool
    headline: str
    lines: tuple[str, ...] = ()
    stage_before: str = ""
    stage_after: str = ""
    learned: bool = False


@dataclass(frozen=True)
class SummaryRow:
    nid: int
    title: str
    stage: str
    """The stage label reached."""
    learned: bool
    helped: bool
    needed_help: bool
    time_ms: int
    turns: int


@dataclass(frozen=True)
class SessionSummary:
    rows: tuple[SummaryRow, ...]
    learned: tuple[int, ...]
    """Note ids that reached Learned and have not been handed off yet."""
    handed_off: tuple[int, ...] = ()
    handoff_error: str = ""

    @property
    def total_ms(self) -> int:
        return sum(r.time_ms for r in self.rows)


class HistorySink:
    """Where history lines go (a ``Storage`` in the window, a list in tests)."""

    def append(self, record: dict[str, Any]) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@dataclass
class ListHistory(HistorySink):
    lines: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    def append(self, record: dict[str, Any]) -> None:
        self.lines.append(record)


PREPARING = "preparing"
RUN = "run"
RESULT = "result"
SUMMARY = "summary"

# Effects a command asks the window for.
EFFECT_NONE = ""
EFFECT_CLOSE = "close"
EFFECT_PROGRESS = "progress"
EFFECT_HANDOFF = "handoff"
EFFECT_END = "end"


class LearnSession:
    """The state of one learn session. The window draws :attr:`screen` and feeds it commands."""

    def __init__(
        self,
        notes: Sequence[RecipeNote],
        store: ProgressStore,
        history: HistorySink,
        get_problem: Callable[[Recipe], Problem | None],
        *,
        clock: Callable[[], int] = lambda: 0,
        now_iso: Callable[[], str] = lambda: "",
        section: str = "",
        pending: Sequence[int] = (),
    ) -> None:
        self.store = store
        self.history = history
        self.get_problem = get_problem
        self.clock = clock
        self.now_iso = now_iso
        self.section = section
        self.pending = tuple(pending)
        """Notes learned in an earlier session whose handoff never ran: handed off with this one."""
        self.items: list[SessionItem] = []
        for note in notes:
            assert note.recipe is not None
            progress = store.get(note.nid)
            if progress.is_learned:
                continue
            self.items.append(SessionItem(note, note.recipe, progress, progress.stage))
        self.turn_no = 0
        self.current = -1
        self.run: ProblemRun | None = None
        self.result: TurnResult | None = None
        self.screen = PREPARING
        self.focus_id = ""
        self.handed_off: tuple[int, ...] = ()
        self.handoff_error = ""
        self.ended_early = False
        self._completed = False
        self._advance()

    # -- who is next -------------------------------------------------------------------------

    def active(self) -> list[int]:
        return [i for i, it in enumerate(self.items) if not it.finished]

    def _advance(self) -> None:
        """Pick the next recipe (round-robin: the next one after the current) and start its turn."""
        active = self.active()
        if not active:
            self._finish()
            return
        later = [i for i in active if i > self.current]
        self.current = later[0] if later else active[0]
        self._begin_turn()

    def _begin_turn(self) -> None:
        item = self.items[self.current]
        self.run = None
        self.result = None
        self._completed = False
        problem = self.get_problem(item.recipe)
        if problem is None:
            self.screen = PREPARING
            return
        self._start(problem)

    def problem_ready(self) -> bool:
        """Try again to get the problem the screen is waiting for (the window calls this when the
        background build finishes, and on a timer). True once the turn has started."""
        if self.screen != PREPARING or self.current < 0 or not self.active():
            return False
        problem = self.get_problem(self.items[self.current].recipe)
        if problem is None:
            return False
        self._start(problem)
        return True

    def _start(self, problem: Problem) -> None:
        item = self.items[self.current]
        stage = item.progress.stage
        mode = {STUDY: runmod.STUDY, FADED: runmod.FADED, PLAN: runmod.PLAN, SOLO: runmod.SOLO}[
            stage
        ]
        self.turn_no += 1
        self.run = ProblemRun(problem, mode, item.progress.faded_level, self.clock)
        self.screen = RUN
        self.focus_id = self._first_focus()

    def _first_focus(self) -> str:
        run = self.run
        if run is None:
            return ""
        if run.mode == runmod.PLAN:
            return plan_field(0)
        if run.mode == runmod.FADED:
            for st in run.steps:
                if st.blank:
                    return step_field(st.index)
        if run.mode in (runmod.FADED, runmod.SOLO):
            return runmod.VERTEX_FIELD if run.is_graph else ANSWER_FIELD
        return ""

    # -- accessors for the screens ---------------------------------------------------------------

    @property
    def item(self) -> SessionItem | None:
        return self.items[self.current] if 0 <= self.current < len(self.items) else None

    @property
    def stage(self) -> str:
        item = self.item
        return item.progress.stage if item is not None else ""

    @property
    def stage_label(self) -> str:
        if self.run is None:
            return STAGE_LABELS.get(self.stage, "")
        label = STAGE_LABELS[self.stage]
        if self.stage == FADED and self.item is not None:
            label += f" · level {self.item.progress.faded_level}"
        return label

    @property
    def learned_notes(self) -> tuple[int, ...]:
        """Notes that reached Learned in this session and haven't been handed off."""
        mine = tuple(
            it.note.nid
            for it in self.items
            if it.progress.is_learned and not it.progress.handed_off
        )
        return mine + tuple(
            n for n in self.pending if n not in mine and not self.store.get(n).handed_off
        )

    # -- commands ----------------------------------------------------------------------------

    def command(self, cmd: Command) -> str:
        """Handle one command from the page; returns the effect the window must carry out."""
        run = self.run
        if run is not None and self.screen == RUN:
            run.touch()
        if cmd.kind == "focus":
            self.focus_id = cmd.a
            if run is not None:
                run.focus(cmd.a)
            return EFFECT_NONE
        if cmd.kind == "field" and run is not None and self.screen == RUN:
            run.set_field(cmd.a, cmd.b)
            return EFFECT_NONE
        if cmd.kind == "text" and run is not None and self.screen == RUN:
            if cmd.a.startswith("plan") and cmd.a[4:].isdigit():
                run.set_plan(int(cmd.a[4:]), cmd.b)
            return EFFECT_NONE
        if cmd.kind == "esc":
            if run is not None and run.help_open:
                run.close_help()
            return EFFECT_NONE
        if cmd.kind == "ctrl-enter":
            return self._next() if self.screen == RESULT else EFFECT_NONE
        if cmd.kind == "enter":
            return self._enter(cmd.a)
        if cmd.kind == "act":
            return self._act(cmd.a, cmd.b)
        return EFFECT_NONE

    def _enter(self, field_id: str) -> str:
        run = self.run
        if self.screen == RESULT:
            return self._next()
        if self.screen == SUMMARY:
            return EFFECT_NONE
        if run is None or self.screen != RUN:
            return EFFECT_NONE
        if run.mode == runmod.STUDY:
            run.finish_study()
            self._after_check()
            return EFFECT_NONE
        if run.mode == runmod.PLAN:
            index = (
                int(field_id[4:]) if field_id.startswith("plan") and field_id[4:].isdigit() else -1
            )
            if 0 <= index < len(run.problem.steps) - 1 and not run.plan_ok.get(index + 1):
                self.focus_id = plan_field(index + 1)
                return EFFECT_NONE
            run.check_plan()
            self._after_check()
            return EFFECT_NONE
        if run.mode == runmod.FADED and field_id.startswith("s") and field_id[1:].isdigit():
            i = int(field_id[1:])
            if 0 <= i < len(run.steps) and run.steps[i].blank:
                verdict = run.check_step(i)
                if verdict is not None and verdict.ok:
                    self.focus_id = self._next_field_after(i)
                self._after_check()
                return EFFECT_NONE
        return self._check()

    def _next_field_after(self, index: int) -> str:
        run = self.run
        assert run is not None
        for st in run.steps:
            if st.index > index and st.blank and st.ok is not True:
                return step_field(st.index)
        return runmod.VERTEX_FIELD if run.is_graph else ANSWER_FIELD

    def _check(self) -> str:
        run = self.run
        if run is None or self.screen != RUN:
            return EFFECT_NONE
        if run.mode == runmod.STUDY:
            run.finish_study()
        elif run.mode == runmod.PLAN:
            run.check_plan()
        elif run.mode == runmod.FADED:
            run.check_all()
        else:
            run.message = ""
            if run.answer_ok is not True:
                run.check_answer()
        self._after_check()
        return EFFECT_NONE

    def _act(self, name: str, arg: str) -> str:
        run = self.run
        if name == "next":
            if self.screen == RUN and run is not None and run.mode == runmod.STUDY:
                run.finish_study()  # Study's Next
                self._after_check()
                return EFFECT_NONE
            return self._next()
        if name == "check":
            return self._check()
        if name == "progress":
            return EFFECT_PROGRESS
        if name == "close":
            return EFFECT_CLOSE
        if name == "end":
            return EFFECT_END
        if name == "handoff":
            return EFFECT_HANDOFF
        if run is None or self.screen != RUN:
            return EFFECT_NONE
        if name == "check_step" and arg.isdigit():
            run.message = ""
            run.check_step(int(arg))
            self._after_check()
        elif name == "choose":
            run.choose(arg)
            self._after_check()
        elif name == "shape":
            run.choose_shape(arg)
        elif name == "help":
            run.use_help(arg)
            self._after_check()
        elif name == "close_help":
            run.close_help()
        return EFFECT_NONE

    def _after_check(self) -> None:
        run = self.run
        if run is not None and run.done and not self._completed and self.screen == RUN:
            run.touch()
            self._complete()

    # -- finishing a problem ------------------------------------------------------------------

    def _complete(self) -> None:
        """The problem is done: apply the stage transition, save, and show the result."""
        run = self.run
        item = self.item
        assert run is not None and item is not None
        self._completed = True
        before = item.progress.stage
        result = self._transition(item, run)
        item.turns += 1
        item.time_ms += run.active_ms
        item.helped = item.helped or run.helped or run.wrong_tries > 0
        item.progress.last_seen = self.now_iso()
        self.store.put(item.note.nid, item.progress)
        line = {
            "type": "problem",
            "ts": self.now_iso(),
            "nid": item.note.nid,
            "mode": "learn",
            **run.history_line(),
            "stage": before,
            "needed_help": item.needed_help,
            "result": result.headline,
            "after": item.progress.stage,
            "rating": None,
        }
        self.history.append(line)
        self.result = result
        self.screen = RESULT
        if before == STUDY:  # nothing to report: go straight on to the next problem
            self._next()

    def _transition(self, item: SessionItem, run: ProblemRun) -> TurnResult:
        p = item.progress
        before = p.stage
        label = STAGE_LABELS[before]
        lines: list[str] = []
        ok = False
        learned = False
        if before == STUDY:
            p.stage, p.faded_level, p.faded_tries = FADED, 1, 0
            ok = True
            headline = "Studied. Next: a faded problem, the last half of the steps blank."
        elif before == FADED:
            ok = run.unaided_right
            level = p.faded_level
            if ok:
                headline = f"Faded level {level}: done with no help."
                self._leave_faded(p, level)
                lines.append(self._where_next(p))
            else:
                p.faded_tries += 1
                why = (
                    "a wrong answer"
                    if run.wrong_tries or any(s.wrong for s in run.steps)
                    else "help"
                )
                if p.faded_tries >= MAX_FADED_TRIES:
                    p.needed_help = True
                    item.needed_help = True
                    headline = f"Faded level {level}: {why}, third try."
                    lines.append("Moving on, marked “needed help”.")
                    self._leave_faded(p, level)
                    lines.append(self._where_next(p))
                else:
                    headline = f"Faded level {level}: {why}."
                    lines.append(
                        f"Same level again with a fresh problem (try {p.faded_tries + 1} of "
                        f"{MAX_FADED_TRIES})."
                    )
        elif before == PLAN:
            ok = not run.plan_missed
            if ok:
                p.stage, p.solo_clean = SOLO, 0
                headline = "Plan: every step right."
                lines.append("Next: a solo problem. Work it on paper, then type the answer.")
            else:
                headline = "Plan: a step needed the right name."
                lines.append("That counts as help: Plan again with a fresh problem.")
        else:  # solo
            ok = run.unaided_right
            if ok:
                counted = self._count_solo(item)
                if p.solo_clean >= SOLOS_TO_LEARN:
                    p.stage = LEARNED
                    learned = True
                    item.finished = True
                    headline = "Solo: right with no help. That's two. Learned!"
                    lines.append("It goes to Anki when the session ends.")
                elif counted:
                    headline = "Solo: right with no help (1 of 2)."
                    lines.append("One more, after a problem from another recipe.")
                else:
                    headline = "Solo: right with no help, but too soon after the last one."
                    lines.append("It needs another problem in between to count.")
            else:
                p.stage, p.faded_level, p.faded_tries, p.solo_clean = FADED, 2, 0, 0
                item.first_solo_turn = None
                if run.answer_shown:
                    headline = "Solo: the answer was shown."
                elif run.rungs:
                    headline = "Solo: help was used."
                else:
                    headline = "Solo: not right the first time."
                lines.append(
                    "Back to Faded level 2 with a fresh problem; the solo count starts over."
                )
        return TurnResult(
            ok=ok,
            headline=headline,
            lines=tuple(lines),
            stage_before=label,
            stage_after=STAGE_LABELS[p.stage],
            learned=learned,
        )

    @staticmethod
    def _leave_faded(p: NoteProgress, level: int) -> None:
        if level == 1:
            p.faded_level, p.faded_tries = 2, 0
        else:
            p.stage, p.faded_tries = PLAN, 0

    @staticmethod
    def _where_next(p: NoteProgress) -> str:
        if p.stage == PLAN:
            return "Next: say the plan."
        return "Next: level 2, every checkable step blank."

    def _count_solo(self, item: SessionItem) -> bool:
        """Count an unaided right solo, unless it follows the first one with no other problem
        between (False then). With only this recipe left, the second solo may follow directly."""
        p = item.progress
        if p.solo_clean == 0:
            p.solo_clean = 1
            item.first_solo_turn = self.turn_no
            return True
        alone = len(self.active()) == 1
        gap = item.first_solo_turn is None or self.turn_no - item.first_solo_turn >= 2
        if gap or alone:
            p.solo_clean = min(SOLOS_TO_LEARN, p.solo_clean + 1)
            return True
        item.first_solo_turn = self.turn_no  # the spacing restarts from this solo
        return False

    # -- moving on -----------------------------------------------------------------------------

    def _next(self) -> str:
        if self.screen != RESULT:
            return EFFECT_NONE
        if not self.active():
            self._finish()
            return EFFECT_HANDOFF if self.learned_notes else EFFECT_NONE
        self._advance()
        return EFFECT_NONE

    def _finish(self) -> None:
        self.run = None
        self.result = None
        self.screen = SUMMARY

    def end_early(self) -> str:
        """Stop here (End session, or closing the window): the unfinished recipes keep their stage
        and stay suspended; those that reached Learned are handed off."""
        self.ended_early = True
        self._finish()
        return EFFECT_HANDOFF if self.learned_notes else EFFECT_NONE

    # -- the handoff, and the summary -------------------------------------------------------------

    def handoff_done(self, nids: Sequence[int], cids: Sequence[int]) -> None:
        """The window handed these notes to Anki: remember it, and write the history line."""
        for item in self.items:
            if item.note.nid in nids:
                item.progress.handed_off = True
                self.store.put(item.note.nid, item.progress)
        for nid in nids:
            if not any(item.note.nid == nid for item in self.items):
                progress = self.store.get(nid)
                progress.handed_off = True
                self.store.put(nid, progress)
        self.handed_off = tuple(nids)
        self.handoff_error = ""
        self.history.append(
            {
                "type": "handoff",
                "ts": self.now_iso(),
                "nids": list(nids),
                "cids": list(cids),
            }
        )

    def handoff_failed(self, message: str) -> None:
        self.handoff_error = message

    def summary(self) -> SessionSummary:
        rows = tuple(
            SummaryRow(
                nid=it.note.nid,
                title=it.title,
                stage=STAGE_LABELS[it.progress.stage]
                + (f" · level {it.progress.faded_level}" if it.progress.stage == FADED else ""),
                learned=it.progress.is_learned,
                helped=it.helped,
                needed_help=it.needed_help,
                time_ms=it.time_ms,
                turns=it.turns,
            )
            for it in self.items
        )
        return SessionSummary(
            rows=rows,
            learned=self.learned_notes,
            handed_off=self.handed_off,
            handoff_error=self.handoff_error,
        )
