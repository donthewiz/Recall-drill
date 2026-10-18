"""A review: one fresh solo problem and the Anki rating it earns."""

from __future__ import annotations

from typing import Any

import pytest
from drive import note_for, sequential_problems, type_answer
from recipe_files import CH03, V2, load

from math_path.pages import Command
from math_path.problem import make_problem
from math_path.review import (
    AGAIN,
    DONE,
    EASY,
    EFFECT_CLOSE,
    EFFECT_NONE,
    EFFECT_RATE,
    GOOD,
    HARD,
    PREPARING,
    RATING_NAMES,
    RUN,
    ReviewSession,
    outcome_text,
    suggested_rating,
)
from math_path.run import ANSWER_FIELD, SOLO, ProblemRun
from math_path.session import ListHistory

FACTORING = load(CH03 / "ca.quad.solve_factoring.json")


def review(**kw: Any) -> tuple[ReviewSession, ListHistory]:
    history = ListHistory()
    s = ReviewSession(
        note_for(FACTORING, 100),
        4242,
        kw.pop("get_problem", sequential_problems()),
        history,
        now_iso=lambda: "2026-10-17T10:00:00Z",
        **kw,
    )
    return s, history


def cmd(s: ReviewSession, kind: str, a: str = "", b: str = "") -> str:
    return s.command(Command(kind, a, b))


def right(s: ReviewSession) -> None:
    assert s.run is not None
    type_answer(s.run)
    cmd(s, "act", "check")


def wrong(s: ReviewSession) -> None:
    assert s.run is not None
    type_answer(s.run, right=False)
    cmd(s, "act", "check")


def test_the_rating_table() -> None:
    p = make_problem(FACTORING, 1001)

    def run() -> ProblemRun:
        return ProblemRun(p, SOLO)

    clean = run()
    type_answer(clean)
    clean.check_answer()
    assert suggested_rating(clean) == GOOD

    after_wrong = run()
    type_answer(after_wrong, right=False)
    after_wrong.check_answer()
    type_answer(after_wrong)
    after_wrong.check_answer()
    assert suggested_rating(after_wrong) == AGAIN

    wrong_and_hint = run()
    wrong_and_hint.use_help("hint")
    type_answer(wrong_and_hint, right=False)
    wrong_and_hint.check_answer()
    type_answer(wrong_and_hint)
    wrong_and_hint.check_answer()
    assert suggested_rating(wrong_and_hint) == AGAIN

    for rungs in (["hint"], ["hint", "why"]):
        helped = run()
        for r in rungs:
            helped.use_help(r)
        type_answer(helped)
        helped.check_answer()
        assert suggested_rating(helped) == HARD

    shown = run()
    for r in ("hint", "why", "show"):
        shown.use_help(r)
    type_answer(shown)
    shown.check_answer()
    assert suggested_rating(shown) == AGAIN

    gave_up = run()
    gave_up.use_help("answer")
    assert suggested_rating(gave_up) == AGAIN


def test_easy_is_never_picked_automatically() -> None:
    p = make_problem(FACTORING, 1002)
    for how in ("clean", "wrong", "hint", "show", "answer"):
        r = ProblemRun(p, SOLO)
        if how == "wrong":
            type_answer(r, right=False)
            r.check_answer()
        elif how == "hint":
            r.use_help("hint")
        elif how == "show":
            r.use_help("hint")
            r.use_help("why")
            r.use_help("show")
        elif how == "answer":
            r.use_help("answer")
        if how != "answer":
            type_answer(r)
            r.check_answer()
        assert suggested_rating(r) != EASY


def test_the_done_screen_says_how_it_went() -> None:
    p = make_problem(FACTORING, 1003)
    r = ProblemRun(p, SOLO)
    type_answer(r)
    r.check_answer()
    assert outcome_text(r) == "Right on the first try, no help."
    r2 = ProblemRun(p, SOLO)
    type_answer(r2, right=False)
    r2.check_answer()
    type_answer(r2)
    r2.check_answer()
    assert outcome_text(r2) == "Right after a wrong try."
    r2.wrong_tries = 2
    assert outcome_text(r2) == "Right after 2 wrong tries."
    r3 = ProblemRun(p, SOLO)
    r3.use_help("hint")
    type_answer(r3)
    r3.check_answer()
    assert outcome_text(r3) == "Right, with a hint."
    r3.wrong_tries = 1
    assert outcome_text(r3) == "Right after a wrong try and a hint."
    r4 = ProblemRun(p, SOLO)
    for rung in ("hint", "why", "show"):
        r4.use_help(rung)
    assert "step was shown" in outcome_text(r4)
    r5 = ProblemRun(p, SOLO)
    r5.use_help("answer")
    assert "gave up" in outcome_text(r5)


def test_the_window_opens_on_a_fresh_solo_problem() -> None:
    s, _h = review()
    assert s.screen == RUN and s.run is not None and s.run.mode == "solo"
    assert s.run.offers_choices and s.focus_id == ANSWER_FIELD


def test_the_problem_may_not_be_ready() -> None:
    calls = {"n": 0}
    real = sequential_problems()

    def slow(recipe: Any) -> Any:
        calls["n"] += 1
        return None if calls["n"] < 3 else real(recipe)

    s, _h = review(get_problem=slow)
    assert s.screen == PREPARING and not s.problem_ready()
    assert s.problem_ready() and s.screen == RUN
    assert not s.problem_ready()


def test_finishing_picks_the_rating_and_next_applies_it() -> None:
    s, _h = review()
    right(s)
    assert s.screen == DONE and s.finished
    assert (s.suggested, s.rating) == (GOOD, GOOD)
    assert cmd(s, "act", "next") == EFFECT_RATE


def test_a_wrong_try_then_right_suggests_again_and_the_chips_change_it() -> None:
    s, _h = review()
    wrong(s)
    assert s.screen == RUN and s.run is not None and s.run.wrong_tries == 1
    right(s)
    assert s.screen == DONE and (s.suggested, s.rating) == (AGAIN, AGAIN)
    assert cmd(s, "act", "rate", str(EASY)) == EFFECT_NONE
    assert s.rating == EASY and s.suggested == AGAIN
    cmd(s, "act", "rate", "7")  # not a rating
    cmd(s, "act", "rate", "x")
    assert s.rating == EASY
    assert RATING_NAMES[s.rating] == "Easy"


def test_giving_up_suggests_again_and_ends_the_problem() -> None:
    s, _h = review()
    cmd(s, "act", "help", "answer")
    assert s.screen == DONE and s.suggested == AGAIN


def test_the_help_ladder_and_esc() -> None:
    s, _h = review()
    assert s.run is not None
    cmd(s, "act", "help", "hint")
    assert s.run.help_open
    cmd(s, "esc")
    assert not s.run.help_open
    cmd(s, "act", "help", "why")
    cmd(s, "act", "help", "show")
    assert s.run.used_show
    right(s)
    assert s.suggested == AGAIN


def test_enter_checks_and_on_the_done_screen_means_next() -> None:
    s, _h = review()
    assert s.run is not None
    cmd(s, "field", ANSWER_FIELD, "99999")
    assert cmd(s, "enter", ANSWER_FIELD) == EFFECT_NONE and s.run.wrong_tries == 1
    assert cmd(s, "ctrl-enter") == EFFECT_NONE  # only on the done screen
    type_answer(s.run)
    cmd(s, "enter", ANSWER_FIELD)
    assert s.screen == DONE
    assert cmd(s, "enter", "") == EFFECT_RATE
    assert cmd(s, "ctrl-enter") == EFFECT_RATE


def test_the_choice_buttons_work_in_a_review() -> None:
    history = ListHistory()
    p = make_problem(load(V2 / "ca.rat.no_solution.json"), 1000)
    s = ReviewSession(note_for(load(V2 / "ca.rat.no_solution.json"), 5), 1, lambda _r: p, history)
    cmd(s, "act", "choose", "all_reals")
    assert s.screen == RUN and s.run is not None and s.run.wrong_tries == 1
    cmd(s, "act", "choose", "none")
    assert s.screen == DONE and s.suggested == AGAIN


def test_close_asks_the_window_to_close() -> None:
    s, _h = review()
    assert cmd(s, "act", "close") == EFFECT_CLOSE
    assert cmd(s, "act", "next") == EFFECT_NONE  # nothing to rate yet


def test_the_history_row_has_the_seed_the_typing_the_help_and_the_rating() -> None:
    s, h = review()
    assert s.run is not None
    cmd(s, "act", "help", "hint")
    wrong(s)
    right(s)
    cmd(s, "act", "rate", str(GOOD))
    s.applied_rating(True)
    (line,) = h.lines
    assert line["type"] == "problem" and line["mode"] == "review" and line["stage"] == "solo"
    assert line["nid"] == 100 and line["cid"] == 4242 and line["recipe"] == FACTORING.id
    assert line["version"] == 1 and line["seed"] == s.run.problem.seed
    assert line["help"] == ["hint:0"] and line["suggested"] == AGAIN and line["rating"] == GOOD
    assert line["rated"] is True and [e["ok"] for e in line["typed"]] == [False, True]
    s.log()
    s.applied_rating(True)
    assert len(h.lines) == 1  # one line per problem


def test_a_rating_that_was_not_applied_is_logged_as_none() -> None:
    s, h = review()
    right(s)
    s.applied_rating(False, "The reviewer is no longer on this card, so it wasn't rated.")
    assert h.lines[0]["rating"] is None and h.lines[0]["rated"] is False
    assert s.not_rated_reason.startswith("The reviewer")


def test_an_unfinished_problem_rates_nothing_and_logs_nothing() -> None:
    s, h = review()
    wrong(s)
    s.log()
    assert h.lines == [] and not s.finished


def test_a_finished_but_unrated_problem_is_still_logged_on_close() -> None:
    s, h = review()
    right(s)
    s.log()  # what the window does when it closes
    assert len(h.lines) == 1 and h.lines[0]["rating"] is None and h.lines[0]["suggested"] == GOOD


@pytest.mark.parametrize("ok", [True, False])
def test_result_reports_the_rating_and_whether_it_applied(ok: bool) -> None:
    s, _h = review()
    right(s)
    s.applied_rating(ok)
    assert s.result() == {"rating": GOOD, "applied": ok}
