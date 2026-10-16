"""The drill controller on math cards (v0.6): checked by form before the engine."""

from __future__ import annotations

from typing import Any

import pytest
from controller_support import make, source

from recalldrill.drill_view import card_html
from recalldrill.engine.session import select_trial
from recalldrill.engine.types import DeckItem
from recalldrill.math_answer import engine_target

QUADRATIC = "x=(-b+-sqrt(b^2-4ac))/(2a)"


def math_deck(answers: list[str]) -> tuple[list[DeckItem], list[Any]]:
    deck: list[DeckItem] = [
        {"front": f"formula {i}", "back": engine_target(a)} for i, a in enumerate(answers)
    ]
    sources = [source(i, math_target=a) for i, a in enumerate(answers)]
    return deck, sources


def one(answer: str, **src: Any) -> Any:
    deck, sources = math_deck([answer])
    sources[0] = source(0, math_target=answer, **src)
    h = make(deck, sources=sources, encodeReps=1)
    h.ctrl.start()
    return h


# (typed, card answer, rd::math::equiv, verdict, message start)
CASES = [
    ("x^2", "x-2", False, "wrong", ""),
    ("1/2", "12", False, "wrong", ""),
    ("(x+3)(x-2)", "(x-2)(x+3)", False, "exact", None),
    ("-4ac+b^2", "b^2-4ac", False, "exact", None),
    (QUADRATIC, "x=(-b+-sqrt(b^2-4*a*c))/(2*a)", False, "exact", None),
    ("x=(-b-sqrt(b^2-4ac))/(2a)", QUADRATIC, False, "wrong", ""),
    ("x=-b/(2a)+-sqrt(b^2-4ac)/(2a)", QUADRATIC, False, "wrong", "Equivalent, but"),
    ("x=-b/(2a)+-sqrt(b^2-4ac)/(2a)", QUADRATIC, True, "exact", None),
    ("m=(y1-y2)/(x2-x1)", "m=(y2-y1)/(x2-x1)", False, "wrong", ""),
    ("m=(y_2-y_1)/(x_2-x_1)", "m=(y2-y1)/(x2-x1)", False, "exact", None),
    ("a^2-b^2", "(a+b)(a-b)", False, "wrong", "Equivalent, but"),
    ("(-2,5)", "[-2,5)", False, "wrong", ""),
    ("[-2,5)", "[-2,5)", False, "exact", None),
    ("2-3i", "2+3i", False, "wrong", ""),
    ("5>=x", "x<=5", False, "exact", None),
    ("x<5", "x<=5", False, "wrong", ""),
    (")(", "x+1", False, "wrong", "Couldn't read that as math"),
]


@pytest.mark.parametrize(("typed", "answer", "equiv", "verdict", "message"), CASES)
def test_the_table_through_the_controller(
    typed: str, answer: str, equiv: bool, verdict: str, message: str | None
) -> None:
    h = one(answer, math_equiv=equiv)
    h.ctrl.submit(typed)
    view = h.ctrl.view()
    assert view.feedback is not None and view.feedback.verdict == verdict
    assert view.feedback.diff is None  # never the word diff on a math card
    if verdict == "wrong":
        assert view.math is not None and view.math.feedback is not None
        fb = view.math.feedback
        assert fb.message.startswith(message or "")
        assert fb.target_latex  # the target, rendered
        assert view.buttons.override  # Count as correct still works
    else:
        assert view.math is not None and view.math.feedback is None


def test_a_math_card_is_one_item_in_the_full_stage() -> None:
    for answer in ("[-2,5)", "(1,2),(3,4),(5,6)", QUADRATIC, "x+" * 30 + "x"):
        deck, sources = math_deck([answer])
        h = make(deck, sources=sources, encodeReps=2, chunkDifficulty=15)
        item = h.ctrl.state["items"][0]
        assert item["chunks"] is None and item["stage"] == "full"


def test_a_full_session_drills_math_cards_through_every_stage() -> None:
    answers = [QUADRATIC, "m=(y2-y1)/(x2-x1)", "[-2,5)", "(a+b)(a-b)"]
    deck, sources = math_deck(answers)
    h = make(deck, sources=sources, encodeReps=2, batchSize=2)
    h.ctrl.start()
    seen: set[str] = set()
    for _ in range(400):
        if h.ctrl.finished:
            break
        view = h.ctrl.view()
        if view.mode == "batch_done":
            h.do(h.ctrl.next_batch())
            continue
        if view.buttons.continue_:
            h.do(h.ctrl.continue_())
            continue
        trial = select_trial(h.ctrl.state)
        assert trial is not None
        seen.add(trial["stage"])
        h.submit(answers[trial["itemId"]])
    assert h.ctrl.finished == "complete"
    assert seen == {"full", "cycle", "final"}
    assert all(i["status"] == "mastered" and i.get("finalDone") for i in h.ctrl.state["items"])
    assert h.ctrl.state["stats"]["misses"] == 0
    done = h.ctrl.done_summary()
    assert done.mastered == 4 and done.is_complete


def test_a_miss_is_recorded_and_the_streak_resets() -> None:
    h = one("[-2,5)")
    h.ctrl.submit("(-2,5)")
    item = h.ctrl.state["items"][0]
    assert item["misses"] == 1 and item["encodeStreak"] == 0
    h.ctrl.continue_()
    h.ctrl.submit("[-2,5)")
    assert h.ctrl.view().feedback is not None
    assert h.ctrl.view().feedback.verdict == "exact"  # type: ignore[union-attr]
    h.ctrl.dwell_elapsed()
    assert h.ctrl.state["items"][0]["status"] == "ready"


def test_count_as_correct_credits_a_math_card() -> None:
    h = one("a^2-b^2")
    h.ctrl.submit("a^2+b^2")
    assert h.ctrl.view().buttons.override
    h.ctrl.override()
    assert h.ctrl.view().math is not None and h.ctrl.view().math.feedback is None  # type: ignore[union-attr]
    h.ctrl.dwell_elapsed()
    assert h.ctrl.state["stats"]["overrides"] == 1


def test_reveal_shows_the_target_rendered_and_counts_as_a_reveal() -> None:
    h = one(QUADRATIC)
    h.ctrl.reveal()
    view = h.ctrl.view()
    assert view.revealed and view.math is not None and view.math.sub_latex.startswith("x =")
    assert "\\frac" in view.sub_text and view.sub_text.startswith("\\(")
    assert engine_target(QUADRATIC) not in view.sub_text and view.placeholder != view.sub_text
    h.ctrl.submit(QUADRATIC)
    h.ctrl.dwell_elapsed()
    assert h.ctrl.state["items"][0].get("reveals") == 1


def test_the_first_cue_is_readable_not_the_engine_letters() -> None:
    h = one(QUADRATIC)
    view = h.ctrl.view()
    assert view.cue.kind == "firstLetter"
    assert view.cue.text == view.sub_text == "Type the whole formula"
    assert view.cue_badge == "Whole formula"
    assert engine_target(QUADRATIC) not in view.placeholder


def test_the_page_shows_answers_rendered_never_raw() -> None:
    h = one("a^2-b^2")
    h.ctrl.submit("a^2+b^2")
    page = card_html(h.ctrl.view(), lambda s: s)
    assert "Your answer" in page and "Target" in page
    assert "\\(a^{2} + b^{2}\\)" in page  # yours, in MathJax delimiters
    assert "\\(a^{2} - b^{2}\\)" in page  # the card's
    assert engine_target("a^2-b^2") not in page  # the engine's encoded text never shows
    assert "rd-diff" not in page
    assert "Not the same expression" in page


def test_an_unreadable_answer_is_shown_as_typed() -> None:
    h = one("x+1")
    h.ctrl.submit(")(")
    page = card_html(h.ctrl.view(), lambda s: s)
    assert "Couldn&#x27;t read that as math" in page or "Couldn't read that as math" in page
    assert ")(" in page and "rd-math-raw" in page


def test_the_equivalent_message_shows_the_target_rendered() -> None:
    h = one("(a+b)(a-b)")
    h.ctrl.submit("a^2-b^2")
    page = card_html(h.ctrl.view(), lambda s: s)
    assert "Equivalent, but this card wants:" in page
    assert page.count("\\left( a + b \\right) \\left( a - b \\right)") == 2  # row and message


def test_the_other_cards_answer_catch_skips_math_cards() -> None:
    deck, sources = math_deck(["x+1", "x+2"])
    sources[0] = source(0, math_target="x+1", colliding_answers=("x+2",))
    h = make(deck, sources=sources, encodeReps=1, chunkDifficulty=100)
    h.ctrl.start()
    h.ctrl.submit("x+2")  # the other card's answer: wrong, not a collision notice
    assert h.ctrl.collisions == 0
    assert h.ctrl.view().feedback is not None and h.ctrl.view().feedback.verdict == "wrong"  # type: ignore[union-attr]


def test_the_done_screen_renders_math_answers() -> None:
    h = one("x+1")
    h.ctrl.submit("x+2")
    h.ctrl.save_and_stop()
    done = h.ctrl.done_summary()
    assert done.hardest and done.hardest[0].back == "\\(x + 1\\)"


# -- non-math cards: unchanged, next to a math card ------------------------------------


def _drive(h: Any, answers: dict[int, str], miss: dict[int, int]) -> dict[int, dict[str, Any]]:
    """Answer every trial from ``answers``; item ``k`` is wrong ``miss[k]`` times first."""
    left = dict(miss)
    h.ctrl.start()
    for _ in range(600):
        if h.ctrl.finished:
            break
        view = h.ctrl.view()
        if view.mode == "batch_done":
            h.do(h.ctrl.next_batch())
            continue
        if view.buttons.continue_:
            h.do(h.ctrl.continue_())
            continue
        trial = select_trial(h.ctrl.state)
        assert trial is not None
        k = trial["itemId"]
        if left.get(k, 0) > 0 and trial["cue"]["kind"] != "present":
            left[k] -= 1
            h.submit("nope nope")
        else:
            h.submit(answers[k])
    assert h.ctrl.finished == "complete"
    return {i["id"]: i for i in h.ctrl.state["items"]}


def test_non_math_cards_behave_the_same_with_a_math_card_in_the_deck() -> None:
    plain: list[DeckItem] = [
        {"front": "heart", "back": "cardi"},
        {"front": "liver", "back": "hepat"},
        {"front": "kidney", "back": "nephr"},
    ]
    answers = {0: "cardi", 1: "hepat", 2: "nephr"}
    base = _drive(make(plain, encodeReps=2), answers, {1: 1})

    deck = [*plain, {"front": "formula", "back": engine_target("[-2,5)")}]
    sources = [source(i) for i in range(3)] + [source(3, math_target="[-2,5)")]
    mixed = _drive(
        make(deck, sources=sources, encodeReps=2), {**answers, 3: "[-2,5)"}, {1: 1, 3: 1}
    )

    keys = ("status", "attempts", "misses", "reveals", "nearMisses", "finalDone", "stage")
    for k in range(3):
        assert {key: mixed[k].get(key) for key in keys} == {key: base[k].get(key) for key in keys}
    assert mixed[3]["misses"] == 1 and mixed[3]["status"] == "mastered"


def test_a_non_math_view_is_untouched() -> None:
    h = make([{"front": "heart", "back": "cardi"}], encodeReps=1)
    h.ctrl.start()
    view = h.ctrl.view()
    assert view.math is None and view.cue.kind == "firstLetter" and view.cue.text == "c____"
    assert view.cue_badge == "First-Letter Cue"
    h.ctrl.submit("cardo")
    fb = h.ctrl.view().feedback
    assert fb is not None and fb.diff is not None and h.ctrl.view().math is None
    page = card_html(h.ctrl.view(), lambda s: s)
    assert "rd-diff" in page and "Your answer" not in page
