"""The learn session: choosing recipes, the stage table transition by transition, interleaving,
spacing between solos, help, resume, the summary."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest
from drive import (
    new_session,
    new_store,
    next_problem,
    note_for,
    sequential_problems,
    solve,
)
from recipe_files import CH03, ch03, load

from math_path.config import Config
from math_path.notes import RecipeNote
from math_path.pages import Command
from math_path.progress import (
    FADED,
    LEARNED,
    PLAN,
    SOLO,
    NoteProgress,
    ProgressStore,
)
from math_path.recipe import Recipe, loads_recipe
from math_path.run import ANSWER_FIELD, ProblemRun
from math_path.session import (
    EFFECT_CLOSE,
    EFFECT_END,
    EFFECT_HANDOFF,
    EFFECT_NONE,
    EFFECT_PROGRESS,
    PREPARING,
    RESULT,
    RUN,
    SUMMARY,
    LearnSession,
    ListHistory,
    is_learned,
    locked_by,
    pick_for_session,
)
from math_path.storage import Storage

FACTORING = load(CH03 / "ca.quad.solve_factoring.json")
MULTIPLY = load(CH03 / "ca.cx.multiply.json")
SQUARE_ROOT = load(CH03 / "ca.quad.solve_square_root.json")


note = note_for
store = new_store
session = new_session


def play(s: LearnSession, right: bool = True) -> None:
    solve(s, right=right)


def stage(s: LearnSession, i: int = 0) -> str:
    return s.items[i].progress.stage


def cmd(s: LearnSession, kind: str, a: str = "", b: str = "") -> str:
    return s.command(Command(kind, a, b))


# -- choosing the recipes -----


def test_picking_takes_unlearned_unlocked_recipes_up_to_the_limit() -> None:
    notes = [note(r, 10 + i) for i, r in enumerate(ch03()) if r.section_number == "3.2"]
    assert len(notes) == 7
    picked = pick_for_session(notes, notes, {}, Config())
    assert len(picked) == 3
    learned = {picked[0].nid: NoteProgress(stage=LEARNED)}
    again = pick_for_session(notes, notes, learned, Config())
    assert picked[0].nid not in {n.nid for n in again} and len(again) == 3
    tagged = [
        n if i else RecipeNote(**{**n.__dict__, "tags": ("mp::learned",)})
        for i, n in enumerate(notes)
    ]
    assert tagged[0].nid not in {n.nid for n in pick_for_session(tagged, tagged, {}, Config())}
    # some of the 3.2 recipes need another one first, so they are locked until it is learned
    assert len(pick_for_session(notes, notes, {}, Config(problems_per_session=5))) == 3
    assert (
        len(pick_for_session(notes, notes, {}, Config(problems_per_session=5, prereq_lock=False)))
        == 5
    )
    assert len(pick_for_session(notes, notes, {}, Config(), limit=1)) == 1


def _with(recipe: Recipe, **changes: Any) -> Recipe:
    data = json.loads(json.dumps(recipe.raw))
    data.update(changes)
    return loads_recipe(json.dumps(data))


def test_the_order_is_prerequisites_then_priority_then_note_order() -> None:
    a = _with(FACTORING, id="x.a", priority="low", prerequisites=[])
    b = _with(FACTORING, id="x.b", priority="high", prerequisites=["x.a"])
    c = _with(FACTORING, id="x.c", priority="medium", prerequisites=[])
    d = _with(FACTORING, id="x.d", priority="high", prerequisites=[])
    notes = [note(r, i) for i, r in enumerate([a, b, c, d], start=1)]
    cfg = Config(prereq_lock=False, problems_per_session=4)
    order = [n.recipe_id for n in pick_for_session(notes, notes, {}, cfg)]
    # d (high) and c (medium) first by priority; b needs a, which is low, so a comes before b
    assert order == ["x.d", "x.c", "x.a", "x.b"]
    # same priority: note order
    e = _with(FACTORING, id="x.e", priority="high")
    f = _with(FACTORING, id="x.f", priority="high")
    notes2 = [note(e, 7), note(f, 3)]
    assert [n.recipe_id for n in pick_for_session(notes2, notes2, {}, cfg)] == ["x.f", "x.e"]


def test_a_recipe_is_locked_by_an_unlearned_prerequisite_that_is_a_note() -> None:
    pre = _with(FACTORING, id="x.pre", prerequisites=[])
    dep = _with(FACTORING, id="x.dep", prerequisites=["x.pre", "x.no_note_for_this"])
    notes = [note(pre, 1), note(dep, 2)]
    assert locked_by(notes[1], notes, {}, Config()) == [pre.title]
    assert (
        locked_by(notes[0], notes, {}, Config()) == []
    )  # no note for the other prerequisite: ignored
    assert [n.nid for n in pick_for_session(notes, notes, {}, Config())] == [1]
    assert locked_by(notes[1], notes, {1: NoteProgress(stage=LEARNED)}, Config()) == []
    tagged = [RecipeNote(**{**notes[0].__dict__, "tags": ("mp::learned",)}), notes[1]]
    assert locked_by(tagged[1], tagged, {}, Config()) == []  # the tag is as good as progress
    assert locked_by(notes[1], notes, {}, Config(prereq_lock=False)) == []
    assert is_learned(tagged[0], {}) and not is_learned(notes[0], {})


# -- one recipe through the stages -----


def test_a_recipe_goes_study_faded_faded_plan_solo_solo_learned(tmp_path: Path) -> None:
    s, st, history = session(tmp_path, [FACTORING])
    assert s.screen == RUN and s.run is not None and s.run.mode == "study"
    assert s.stage_label == "Study"
    play(s)  # Study: Next
    assert stage(s) == FADED and s.run is not None and s.run.mode == "faded"
    assert s.items[0].progress.faded_level == 1 and s.stage_label == "Faded · level 1"
    blanks = [x.blank for x in s.run.steps]
    assert blanks == [False, False, True, True, False]
    play(s)  # level 1 passes
    assert s.screen == RESULT and s.result is not None and s.result.ok
    assert "level 2" in " ".join(s.result.lines)
    next_problem(s)
    assert s.run is not None and [x.blank for x in s.run.steps] == [True, True, True, True, False]
    assert s.items[0].progress.faded_level == 2
    play(s)  # level 2 passes
    assert stage(s) == PLAN and s.result is not None and "say the plan" in s.result.lines[0].lower()
    next_problem(s)
    assert s.run is not None and s.run.mode == "plan"
    play(s)  # the plan, every step right
    assert stage(s) == SOLO
    next_problem(s)
    assert s.run is not None and s.run.mode == "solo" and s.stage_label == "Solo"
    play(s)  # solo 1
    assert stage(s) == SOLO and s.items[0].progress.solo_clean == 1 and s.result is not None
    assert "1 of 2" in s.result.headline
    next_problem(s)
    play(s)  # solo 2, straight after: one recipe left, so the gap is waived
    assert stage(s) == LEARNED and s.result is not None and s.result.learned
    assert next_problem_effect(s) == EFFECT_HANDOFF
    assert s.screen == SUMMARY and s.learned_notes == (100,)
    stages = [(h["stage"], h["after"]) for h in history.lines if h["type"] == "problem"]
    assert stages == [
        ("study", "faded"), ("faded", "faded"), ("faded", "plan"), ("plan", "solo"),
        ("solo", "solo"), ("solo", "learned"),
    ]  # fmt: skip
    assert st.get(100).stage == LEARNED


def next_problem_effect(s: LearnSession) -> str:
    return cmd(s, "act", "next")


def test_study_goes_straight_on_without_a_result_screen(tmp_path: Path) -> None:
    s, _st, _h = session(tmp_path, [FACTORING])
    assert cmd(s, "act", "next") == EFFECT_NONE  # Study's Next
    assert s.screen == RUN and s.run is not None and s.run.mode == "faded"


def _to_faded(tmp_path: Path, level: int = 1) -> tuple[LearnSession, ProgressStore, ListHistory]:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=FADED, faded_level=level))
    return session(tmp_path, [FACTORING], st)


def test_help_or_a_wrong_answer_repeats_the_faded_level(tmp_path: Path) -> None:
    s, st, _h = _to_faded(tmp_path)
    assert s.run is not None
    cmd(s, "act", "help", "hint")  # any help
    solve(s)
    assert s.result is not None and not s.result.ok and "help" in s.result.headline
    assert (stage(s), s.items[0].progress.faded_level, s.items[0].progress.faded_tries) == (
        FADED,
        1,
        1,
    )
    next_problem(s)
    assert s.run is not None and s.run.mode == "faded"
    solve(s, right=False)  # a wrong answer
    assert s.result is not None and "wrong" in s.result.headline
    assert (stage(s), s.items[0].progress.faded_level, s.items[0].progress.faded_tries) == (
        FADED,
        1,
        2,
    )
    assert "try 3 of 3" in s.result.lines[0]
    assert st.get(100).faded_tries == 2


def test_the_third_failed_try_moves_on_and_marks_needed_help(tmp_path: Path) -> None:
    s, st, history = _to_faded(tmp_path, level=1)
    for _ in range(3):
        solve(s, right=False)
        next_problem(s)
    assert s.items[0].progress.faded_level == 2 and s.items[0].progress.faded_tries == 0
    assert s.items[0].progress.needed_help and st.get(100).needed_help
    last = [h for h in history.lines if h["type"] == "problem"][-1]
    assert last["needed_help"] is True and last["after"] == "faded"
    for _ in range(3):  # level 2: three more, then on to the plan
        solve(s, right=False)
        next_problem(s)
    assert stage(s) == PLAN and s.items[0].progress.needed_help


def test_level_1_passes_to_level_2_and_level_2_to_the_plan(tmp_path: Path) -> None:
    s, _st, _h = _to_faded(tmp_path, level=1)
    solve(s)
    assert s.items[0].progress.faded_level == 2 and s.items[0].progress.faded_tries == 0
    next_problem(s)
    solve(s)
    assert stage(s) == PLAN and not s.items[0].progress.needed_help


def test_a_wrong_plan_box_means_plan_again(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=PLAN))
    s, st, _h = session(tmp_path, [FACTORING], st)
    solve(s, right=False)  # a miss, then retyped
    assert stage(s) == PLAN and s.result is not None and not s.result.ok
    assert "Plan again" in " ".join(s.result.lines)
    next_problem(s)
    assert s.run is not None and s.run.mode == "plan"
    solve(s)
    assert stage(s) == SOLO and s.items[0].progress.solo_clean == 0


@pytest.mark.parametrize("how", ["wrong", "hint", "answer"])
def test_a_solo_that_is_wrong_or_helped_goes_back_to_faded_level_2(
    tmp_path: Path, how: str
) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO, solo_clean=1, faded_level=1))
    s, st, history = session(tmp_path, [FACTORING], st)
    assert s.run is not None and s.run.mode == "solo"
    if how == "wrong":
        solve(s, right=False)
    elif how == "hint":
        cmd(s, "act", "help", "hint")
        solve(s)
    else:
        cmd(s, "act", "help", "answer")
    p = s.items[0].progress
    assert (p.stage, p.faded_level, p.faded_tries, p.solo_clean) == (FADED, 2, 0, 0)
    assert history.lines[-1]["after"] == "faded" and history.lines[-1]["stage"] == "solo"
    next_problem(s)
    assert s.run is not None and s.run.mode == "faded" and s.run.level == 2


def test_the_help_ladder_in_the_session_commands(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO))
    s, _st, _h = session(tmp_path, [FACTORING], st)
    run = s.run
    assert run is not None
    cmd(s, "act", "help", "why")  # not the next rung: ignored
    assert run.rungs == []
    cmd(s, "act", "help", "hint")
    cmd(s, "act", "help", "why")
    cmd(s, "act", "help", "show")
    assert run.rungs == ["hint:0", "why:0", "show:0"] and run.help_open
    assert cmd(s, "esc") == EFFECT_NONE and not run.help_open
    cmd(s, "act", "help", "answer")
    assert s.screen == RESULT  # showing the answer ends the problem


# -- interleaving and the spacing between solos -----


def test_recipes_take_turns(tmp_path: Path) -> None:
    s, _st, history = session(tmp_path, [FACTORING, MULTIPLY, SQUARE_ROOT])
    order: list[str] = []
    for _ in range(7):
        assert s.item is not None
        order.append(s.item.recipe.id)
        play(s)
        if s.screen == RESULT:
            next_problem(s)
    assert order == [r.id for r in (FACTORING, MULTIPLY, SQUARE_ROOT)] * 2 + [FACTORING.id]
    assert [h["stage"] for h in history.lines[:3]] == ["study"] * 3


def test_two_solos_of_one_recipe_have_another_recipes_problem_between_them(tmp_path: Path) -> None:
    st = store(tmp_path)
    for nid in (100, 101):
        st.put(nid, NoteProgress(stage=SOLO))
    s, _st, history = session(tmp_path, [FACTORING, MULTIPLY], st)
    seen: list[tuple[str, int]] = []
    guard = 0
    while s.screen != SUMMARY and guard < 20:
        guard += 1
        assert s.item is not None
        seen.append((s.item.recipe.id, s.item.progress.solo_clean))
        play(s)
        cmd(s, "act", "next")
    assert s.screen == SUMMARY
    assert seen == [
        (FACTORING.id, 0),
        (MULTIPLY.id, 0),
        (FACTORING.id, 1),
        (MULTIPLY.id, 1),
    ]  # A, B, A, B: never A twice in a row while B is still going
    assert s.learned_notes == (100, 101)


def test_a_solo_too_soon_after_the_first_does_not_count_while_others_remain(tmp_path: Path) -> None:
    st = store(tmp_path)
    for nid in (100, 101):
        st.put(nid, NoteProgress(stage=SOLO))
    s, _st, _h = session(tmp_path, [FACTORING, MULTIPLY], st)
    a = s.items[0]
    s.turn_no = 10
    assert s._count_solo(a) and a.progress.solo_clean == 1 and a.first_solo_turn == 10  # type: ignore[attr-defined]
    s.turn_no = 11  # straight after, with the other recipe still going
    assert not s._count_solo(a)  # type: ignore[attr-defined]
    assert a.progress.solo_clean == 1 and a.first_solo_turn == 11
    s.turn_no = 13  # a problem in between
    assert s._count_solo(a) and a.progress.solo_clean == 2  # type: ignore[attr-defined]


def test_with_one_recipe_left_the_second_solo_may_follow_directly(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO))
    s, _st, _h = session(tmp_path, [FACTORING], st)
    a = s.items[0]
    s.turn_no = 4
    assert s._count_solo(a)  # type: ignore[attr-defined]
    s.turn_no = 5
    assert s._count_solo(a) and a.progress.solo_clean == 2  # type: ignore[attr-defined]


def test_the_gap_to_a_solo_from_an_earlier_session_is_certain(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO, solo_clean=1))
    st.put(101, NoteProgress(stage=SOLO))
    s, _st, _h = session(tmp_path, [FACTORING, MULTIPLY], st)
    assert s.items[0].first_solo_turn is None
    play(s)
    assert (
        stage(s) == LEARNED
    )  # its first solo counted in the earlier session: this one is the second


# -- resume, ending, the summary -----


def test_a_closed_window_resumes_at_the_same_stage_with_a_fresh_problem(tmp_path: Path) -> None:
    s, st, _h = session(tmp_path, [FACTORING])
    play(s)
    play(s)  # faded level 1 passed
    next_problem(s)
    assert s.run is not None
    first_seed = s.run.problem.seed
    on_disk = json.loads(Path(st.storage.path("progress.json")).read_text(encoding="utf-8"))
    assert on_disk["data"]["notes"]["100"]["stage"] == "faded"
    assert on_disk["data"]["notes"]["100"]["faded_level"] == 2
    # the window is closed; a new one opens on the same note
    s2, _st2, _h2 = session(tmp_path, [FACTORING], ProgressStore(Storage(tmp_path / "uf", "p")))
    assert s2.run is not None and s2.run.mode == "faded" and s2.run.level == 2
    assert s2.run.problem.seed != first_seed


def test_learned_notes_are_not_offered_again(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=LEARNED))
    s, _st, _h = session(tmp_path, [FACTORING, MULTIPLY], st)
    assert [i.note.nid for i in s.items] == [101]


def test_a_session_with_nothing_to_do_is_the_summary(tmp_path: Path) -> None:
    s, _st, _h = session(tmp_path, [])
    assert s.screen == SUMMARY and s.summary().rows == ()


def test_the_problem_may_not_be_ready_yet(tmp_path: Path) -> None:
    calls = {"n": 0}
    real = sequential_problems()

    def slow(recipe: Recipe) -> Any:
        calls["n"] += 1
        return None if calls["n"] < 3 else real(recipe)

    s = LearnSession([note(FACTORING, 1)], store(tmp_path), ListHistory(), slow)
    assert s.screen == PREPARING and s.run is None
    assert not s.problem_ready() and s.screen == PREPARING
    assert s.problem_ready() and s.screen == RUN and s.run is not None
    assert not s.problem_ready()  # nothing is being waited for any more


def test_end_session_hands_off_what_was_learned_and_keeps_the_rest_suspended(
    tmp_path: Path,
) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO, solo_clean=1))
    st.put(101, NoteProgress(stage=FADED, faded_level=2))
    s, _st, history = session(tmp_path, [FACTORING, MULTIPLY], st)
    play(s)  # FACTORING's second solo: learned
    assert s.result is not None and s.result.learned
    assert cmd(s, "act", "end") == EFFECT_END
    assert s.end_early() == EFFECT_HANDOFF
    assert s.screen == SUMMARY and s.learned_notes == (100,)
    summary = s.summary()
    assert [r.learned for r in summary.rows] == [True, False]
    assert summary.rows[1].stage == "Faded · level 2"
    s.handoff_done([100], [555])
    assert s.learned_notes == () and s.summary().handed_off == (100,)
    assert st.get(100).handed_off and not st.get(101).handed_off
    assert history.lines[-1] == {
        "type": "handoff", "ts": "2026-10-17T10:00:00Z", "nids": [100], "cids": [555],
    }  # fmt: skip
    s.handoff_failed("boom")
    assert s.summary().handoff_error == "boom"


def test_ending_with_nothing_learned_asks_for_no_handoff(tmp_path: Path) -> None:
    s, _st, _h = session(tmp_path, [FACTORING])
    assert s.end_early() == EFFECT_NONE and s.screen == SUMMARY


def test_the_summary_has_stage_help_and_time_per_recipe(tmp_path: Path) -> None:
    clock = {"t": 0}
    st = store(tmp_path)
    s = LearnSession(
        [note(FACTORING, 100)], st, ListHistory(), sequential_problems(),
        clock=lambda: clock["t"], now_iso=lambda: "t",
    )  # fmt: skip
    clock["t"] = 7_000
    play(s)  # Study, 7 s
    cmd(s, "act", "help", "hint")
    clock["t"] = 20_000
    solve(s)
    s.end_early()
    row = s.summary().rows[0]
    assert row.title == FACTORING.title and row.stage == "Faded · level 1"
    assert row.helped and not row.learned and row.turns == 2 and row.time_ms >= 7_000


def test_the_other_commands(tmp_path: Path) -> None:
    s, _st, _h = session(tmp_path, [FACTORING])
    assert cmd(s, "act", "progress") == EFFECT_PROGRESS
    assert cmd(s, "act", "close") == EFFECT_CLOSE
    assert cmd(s, "act", "unknown") == EFFECT_NONE
    assert cmd(s, "focus", "s2") == EFFECT_NONE and s.focus_id == "s2"
    assert cmd(s, "ctrl-enter") == EFFECT_NONE  # only on a result screen


def test_enter_checks_or_goes_on_and_ctrl_enter_is_next_on_a_result(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=SOLO))
    s, _st, _h = session(tmp_path, [FACTORING], st)
    assert s.run is not None
    cmd(s, "field", ANSWER_FIELD, "99999")
    cmd(s, "enter", ANSWER_FIELD)
    assert s.run.wrong_tries == 1 and s.screen == RUN
    from drive import type_answer

    type_answer(s.run)
    cmd(s, "enter", ANSWER_FIELD)
    assert s.screen == RESULT
    cmd(s, "ctrl-enter")
    assert s.screen == RUN  # the next problem (solo again: the recipe went back to faded)
    assert s.run is not None and s.run.mode == "faded"


def test_faded_enter_in_a_step_checks_it_and_moves_on(tmp_path: Path) -> None:
    s, _st, _h = _to_faded(tmp_path, level=2)
    assert s.run is not None
    from drive import tex_of

    cmd(s, "field", "s0", tex_of(s.run.problem.steps[0].result))
    cmd(s, "enter", "s0")
    assert s.run.steps[0].ok is True and s.focus_id == "s1"
    cmd(s, "field", "s1", "7777")
    cmd(s, "enter", "s1")
    assert s.run.steps[1].ok is False and s.focus_id == "s1"  # stays on the step to fix it


def test_plan_enter_moves_to_the_next_box_and_checks_on_the_last(tmp_path: Path) -> None:
    st = store(tmp_path)
    st.put(100, NoteProgress(stage=PLAN))
    s, _st, _h = session(tmp_path, [FACTORING], st)
    assert s.run is not None
    run: ProblemRun = s.run
    for i, step in enumerate(run.problem.steps):
        cmd(s, "text", f"plan{i}", step.name)
    cmd(s, "enter", "plan0")
    assert s.focus_id == "plan1" and not run.plan_ok
    last = len(run.problem.steps) - 1
    cmd(s, "enter", f"plan{last}")
    assert s.screen == RESULT and s.result is not None and s.result.ok
