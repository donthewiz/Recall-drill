"""One problem being worked: blanks, typed steps, the help ladder, the plan, verdicts."""

from __future__ import annotations

import json

from drive import tex_of, type_answer, type_steps
from problems_cache import problems
from recipe_files import CH03, V2, load

from math_path import grading
from math_path.problem import Problem, make_problem
from math_path.recipe import Recipe, loads_recipe
from math_path.run import (
    ANSWER,
    ANSWER_FIELD,
    FADED,
    HINT,
    IDLE_CAP_MS,
    PLAN,
    SHOW,
    SOLO,
    STUDY,
    WHY,
    ProblemRun,
    blank_set,
    plan_field,
    step_field,
)

FACTORING = load(CH03 / "ca.quad.solve_factoring.json")
# steps: 0 standard form (equivalent), 1 factor (factored), 2 set each factor (each),
#        3 solve each (solutions), 4 check (substitution: never blank)


def _problem(recipe: Recipe = FACTORING) -> Problem:
    return problems(recipe, 3)[2]


def _run(mode: str, level: int = 1, recipe: Recipe = FACTORING) -> ProblemRun:
    t = [0]

    def clock() -> int:
        return t[0]

    run = ProblemRun(_problem(recipe), mode, level, clock)
    run._clock = t  # type: ignore[attr-defined]
    return run


def test_level_1_blanks_the_last_half_of_the_checkable_steps_rounded_up() -> None:
    p = _problem()
    assert p.blank_indexes == (0, 1, 2, 3)
    assert blank_set(p, 1) == (2, 3)
    assert blank_set(p, 2) == (0, 1, 2, 3)
    odd = _problem(load(CH03 / "ca.quad.solve_square_root.json"))
    assert odd.blank_indexes == (0, 1, 2) and blank_set(odd, 1) == (1, 2)  # 3 steps: 2 blank
    one = _problem(load(CH03 / "ca.cx.express_i.json"))
    assert len(blank_set(one, 1)) == (len(one.blank_indexes) + 1) // 2


def test_study_shows_every_step_worked_and_ends_on_next() -> None:
    run = _run(STUDY)
    assert all(s.worked for s in run.steps) and not run.done
    assert not any(run.instruction_only(i) for i in range(len(run.steps)))
    run.finish_study()
    assert run.done and not run.can_help()


def test_faded_level_1_shows_the_first_steps_worked_and_blanks_the_rest() -> None:
    run = _run(FADED, 1)
    assert [s.blank for s in run.steps] == [False, False, True, True, False]
    assert [s.worked for s in run.steps] == [True, True, False, False, False]
    assert run.instruction_only(4) and not run.instruction_only(0)  # "check": a name only
    level2 = _run(FADED, 2)
    assert [s.blank for s in level2.steps] == [True, True, True, True, False]
    assert level2.instruction_only(4)


def test_an_instruction_step_before_the_first_blank_is_shown_worked() -> None:
    recipe = load(CH03 / "ca.abs.solve_ineq_less.json")  # last step is a "text" step
    run = _run(FADED, 1, recipe)
    names = [s.blank for s in run.steps]
    assert names[-1] is False and run.instruction_only(len(run.steps) - 1)


def test_typed_steps_are_checked_and_right_ones_lock_in() -> None:
    run = _run(FADED, 2)
    run.set_field(step_field(0), tex_of(run.problem.steps[0].result))
    run.set_field(step_field(1), "123456789")
    assert run.check_step(0).ok  # type: ignore[union-attr]
    assert run.steps[0].ok is True and run.check_step(0) is None  # already right
    assert run.check_step(1).ok is False  # type: ignore[union-attr]
    assert (
        run.steps[1].ok is False
        and run.steps[1].wrong == 1
        and run.steps[1].note == "Not right yet."
    )
    run.set_field(step_field(1), "")  # editing clears the "wrong" mark
    assert run.steps[1].ok is None


def test_an_unfinished_field_is_a_note_not_a_try() -> None:
    run = _run(FADED, 2)
    run.set_field(step_field(0), r"\frac{\placeholder{}}{2}")
    v = run.check_step(0)
    assert v is not None and v.unreadable and run.steps[0].ok is None and run.steps[0].wrong == 0
    assert "fraction" in run.steps[0].note


def test_faded_is_done_only_when_every_blank_and_the_answer_are_right() -> None:
    run = _run(FADED, 2)
    type_steps(run)
    run.check_all()
    assert all(s.ok for s in run.steps if s.blank) and not run.done
    assert "answer" in run.message.lower()
    type_answer(run)
    run.check_all()
    assert run.done and run.unaided_right and run.answer_ok


def test_a_wrong_step_means_the_level_was_not_passed_cleanly() -> None:
    run = _run(FADED, 2)
    type_steps(run, right=False)
    run.check_all()
    assert not run.done and all(s.ok is False for s in run.steps if s.blank)
    type_steps(run)
    type_answer(run)
    run.check_all()
    assert run.done and not run.unaided_right and run.answer_ok


def test_an_empty_blank_is_named_when_checking_everything() -> None:
    run = _run(FADED, 2)
    run.set_field(step_field(0), tex_of(run.problem.steps[0].result))
    type_answer(run)
    run.check_all()
    assert "Fill in step 2, 3, 4 first." in run.message
    assert run.answer_ok is True and not run.done


def test_the_answer_verdicts_count_tries_and_name_mistakes() -> None:
    p = _problem()
    run = ProblemRun(p, SOLO)
    run.set_field(ANSWER_FIELD, r"\frac{\placeholder{}}{2}")
    run.check_answer()
    assert run.wrong_tries == 0 and run.verdict is not None and run.verdict.unreadable
    run.set_field(ANSWER_FIELD, "99999")
    run.check_answer()
    assert run.wrong_tries == 1 and run.answer_ok is False
    run.set_field(ANSWER_FIELD, tex_of(p.key))
    run.check_answer()
    assert run.done and not run.unaided_right and run.wrong_tries == 1


def test_a_named_mistake_is_recorded() -> None:
    p = _problem()
    mk = FACTORING.mistakes[0]
    wrong = grading.loader.load().validator.fill(mk.rule["answer_equals"], p.env)
    run = ProblemRun(p, SOLO)
    run.set_field(ANSWER_FIELD, tex_of(wrong))
    run.check_answer()
    assert run.mistakes == [mk.id]
    assert run.history_line()["mistakes"] == [mk.id]


def test_a_right_value_in_the_wrong_form_is_not_done() -> None:
    p = make_problem(load(CH03 / "ca.abs.solve_eq.json"), 1000)
    assert p.key == "-17/8, 9/8"
    run = ProblemRun(p, SOLO)
    run.set_field(ANSWER_FIELD, r"-\frac{34}{16},\frac{9}{8}")
    run.check_answer()
    assert run.verdict is not None and run.verdict.value_ok and run.verdict.forms
    assert run.wrong_tries == 1 and not run.done
    assert "Right value, but the fraction isn't reduced" in run.verdict.headline
    run.set_field(ANSWER_FIELD, r"-\frac{17}{8},\frac{9}{8}")
    run.check_answer()
    assert run.done and not run.unaided_right


def test_a_graph_answer_uses_a_shape_and_two_points() -> None:
    recipe = load(CH03 / "ca.quadgraph.graph.json")
    p = make_problem(recipe, 1000)
    run = ProblemRun(p, SOLO)
    assert run.is_graph and not run.offers_choices
    run.check_answer()
    assert run.verdict is not None and "shape" in run.verdict.unreadable.lower()
    type_answer(run, right=False)
    run.check_answer()
    assert run.wrong_tries == 1 and not run.done
    run.choose_shape("circle")
    assert run.shape == ""
    type_answer(run)
    run.check_answer()
    assert run.done


def test_the_choice_buttons_are_on_every_solve_task_and_nothing_else() -> None:
    assert ProblemRun(_problem(), SOLO).offers_choices
    vertex = make_problem(load(CH03 / "ca.quadgraph.vertex.json"), 1000)
    assert not ProblemRun(vertex, SOLO).offers_choices
    no_solution = make_problem(load(V2 / "ca.rat.no_solution.json"), 1000)
    run = ProblemRun(no_solution, SOLO)
    assert run.offers_choices
    run.choose("all_reals")
    assert run.wrong_tries == 1 and not run.done
    run.choose("none")
    assert run.done and run.answer_ok
    other = ProblemRun(_problem(), SOLO)
    other.choose("none")
    other.choose("all_reals")
    assert other.wrong_tries == 2 and not other.done  # offering them gives nothing away


# -- the help ladder -----


def test_the_ladder_in_solo_walks_the_steps_from_the_first_not_shown() -> None:
    run = _run(SOLO)
    assert run.ladder_target() == 0 and run.next_rung() == HINT
    assert not run.use_help(WHY) and not run.use_help(SHOW)  # not the next rung
    assert run.use_help(HINT) and run.next_rung() == WHY
    assert run.use_help(WHY) and run.next_rung() == SHOW
    assert run.use_help(SHOW) and run.steps[0].shown
    assert run.ladder_target() == 1 and run.next_rung() == HINT  # on to the next step
    assert run.rungs == ["hint:0", "why:0", "show:0"]
    assert run.help_open and run.helped and run.used_show and not run.unaided_right
    run.close_help()
    assert not run.help_open  # Esc closes the text, never the window


def test_a_step_with_no_hint_goes_straight_to_show_step() -> None:
    data = json.loads(json.dumps(FACTORING.raw))
    data["hints"] = [h for h in data["hints"] if h["step"] != FACTORING.steps[0].name]
    data["hints"][0]["why"] = ""  # and the next one has a hint but no why
    recipe = loads_recipe(json.dumps(data))
    run = ProblemRun(make_problem(recipe, 1001), SOLO)
    assert run.next_rung() == SHOW
    assert run.use_help(SHOW)
    assert run.ladder_target() == 1 and run.next_rung() == HINT
    run.use_help(HINT)
    assert run.next_rung() == SHOW  # the empty "why" is skipped


def test_show_answer_is_the_last_rung_and_ends_the_problem() -> None:
    run = _run(SOLO)
    assert run.use_help(ANSWER)
    assert run.done and run.answer_shown and run.used_show and not run.unaided_right
    assert not run.use_help(HINT) and not run.can_help()
    assert run.rungs == ["answer"]


def test_hint_and_why_only_are_a_nudge_not_a_show() -> None:
    run = _run(SOLO)
    run.use_help(HINT)
    run.use_help(WHY)
    assert run.helped and not run.used_show


def test_in_faded_the_ladder_acts_on_the_blank_being_worked_on() -> None:
    run = _run(FADED, 2)
    assert run.ladder_target() == 0
    run.focus(step_field(2))
    assert run.ladder_target() == 2
    run.use_help(HINT)
    assert run.steps[2].hint_shown and not run.steps[0].hint_shown
    run.focus(ANSWER_FIELD)  # the answer field has no step: back to the first open blank
    assert run.ladder_target() == 0
    run.focus(step_field(4))  # "check" is not a blank
    assert run.ladder_target() == 0


def test_show_step_in_faded_still_asks_for_the_step_to_be_typed() -> None:
    run = _run(FADED, 2)
    for rung in (HINT, WHY, SHOW):
        assert run.use_help(rung)
    st = run.steps[0]
    assert st.shown and st.ok is not True and st.blank  # the field stays: retype it to go on
    run.set_field(step_field(0), tex_of(run.problem.steps[0].result))
    assert run.check_step(0).ok  # type: ignore[union-attr]
    assert not run.unaided_right
    assert run.ladder_target() == 1


def test_a_solved_step_leaves_the_faded_ladder() -> None:
    run = _run(FADED, 2)
    run.set_field(step_field(0), tex_of(run.problem.steps[0].result))
    run.check_step(0)
    assert run.ladder_target() == 1


# -- the plan -----


def test_plan_marks_a_wrong_step_shows_it_and_asks_for_a_retype() -> None:
    run = _run(PLAN)
    names = [s.name for s in run.problem.steps]
    for i, name in enumerate(names):
        run.set_plan(i, name if i != 1 else "no idea")
    run.check_plan()
    assert run.plan_ok == {0: True, 2: True, 3: True, 4: True}
    assert run.plan_missed == {1} and run.plan_typed[1] == "" and not run.done
    run.set_plan(0, "ignored: it was right already")
    assert run.plan_typed[0] == names[0]
    run.set_plan(1, names[1].upper())
    run.check_plan()
    assert run.done and run.helped and not run.unaided_right  # the retype counts as help


def test_a_clean_plan_is_unaided() -> None:
    run = _run(PLAN)
    for i, step in enumerate(run.problem.steps):
        run.set_plan(i, step.name)
    run.check_plan()
    assert run.done and run.unaided_right and not run.helped


def test_plan_order_matters() -> None:
    run = _run(PLAN)
    names = [s.name for s in run.problem.steps]
    for i, name in enumerate(reversed(names)):
        run.set_plan(i, name)
    run.check_plan()
    assert len(run.plan_missed) >= 4 and not run.done


# -- time -----


def test_active_time_counts_each_gap_up_to_the_idle_cap() -> None:
    run = _run(SOLO)
    clock = run._clock  # type: ignore[attr-defined]
    clock[0] = 5_000
    run.touch()
    clock[0] = 5_000 + IDLE_CAP_MS * 10  # a long break
    run.touch()
    assert run.active_ms == 5_000 + IDLE_CAP_MS
    run.answer_shown = True
    clock[0] += 99_000
    run.touch()
    assert run.active_ms == 5_000 + IDLE_CAP_MS  # nothing counts once it is done


def test_history_line_has_what_the_spec_keeps() -> None:
    run = _run(FADED, 2)
    type_steps(run)
    type_answer(run)
    run.check_all()
    line = run.history_line()
    assert line["seed"] == run.problem.seed and line["recipe"] == FACTORING.id
    assert line["version"] == 1 and line["stage"] == FADED and line["level"] == 2
    assert [e["kind"] for e in line["typed"]] == ["step"] * 4 + ["answer"]
    assert all(e["ok"] for e in line["typed"]) and line["right"] and line["help"] == []
    assert plan_field(3) == "plan3" and step_field(3) == "s3"
