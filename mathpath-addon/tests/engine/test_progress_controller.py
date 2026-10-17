"""The progress map's state machine: course choice, Learn, the amber Recall question."""

from __future__ import annotations

from test_course_model import course, note, section

from math_path.course_model import CardState
from math_path.pages import Command
from math_path.progress import LEARNED, NoteProgress
from math_path.progress_controller import (
    EFFECT_CLOSE,
    EFFECT_IMPORT,
    EFFECT_LEARN,
    EFFECT_NONE,
    EFFECT_REFRESH,
    ProgressController,
)


def act(a: str, b: str = "") -> Command:
    return Command("act", a, b)


def two_sections(total: int = 0, drilled: int = 0) -> ProgressController:
    s1 = section(10, "3.1", [note("x.a", 1)], total, drilled)
    s2 = section(20, "3.2", [note("x.b", 2, ["x.a"]), note("x.c", 3)])
    return ProgressController([course([s1, s2])], {})


def test_the_first_course_is_chosen_and_a_missing_one_falls_back() -> None:
    ctl = two_sections()
    assert ctl.selected == "Course" and ctl.course is not None
    ctl.selected = "gone"
    ctl.update(ctl.courses, {})
    assert ctl.selected == "Course"
    empty = ProgressController([], {})
    assert empty.course is None and empty.model() is None and empty.selected == ""


def test_plain_buttons_return_their_effects() -> None:
    ctl = two_sections()
    assert ctl.command(act("close")) == EFFECT_CLOSE
    assert ctl.command(act("import")) == EFFECT_IMPORT
    assert ctl.command(act("refresh")) == EFFECT_REFRESH
    assert ctl.command(act("nonsense")) == EFFECT_NONE
    assert ctl.command(Command("esc")) == EFFECT_NONE


def test_picking_a_course_and_ignoring_an_unknown_one() -> None:
    ctl = two_sections()
    assert ctl.command(Command("select", "course", "Other")) == EFFECT_NONE
    assert ctl.selected == "Course"


def test_learn_next_goes_to_the_next_section_and_learn_to_the_row_asked() -> None:
    ctl = two_sections()
    assert ctl.command(act("learn_next")) == EFFECT_LEARN and ctl.learn_did == 10
    assert ctl.command(act("learn", "20")) == EFFECT_LEARN and ctl.learn_did == 20


def test_a_row_with_nothing_to_learn_does_nothing() -> None:
    s1 = section(10, "3.1", [note("x.a", 1)])
    ctl = ProgressController([course([s1])], {1: NoteProgress(stage=LEARNED, handed_off=True)})
    assert ctl.command(act("learn_next")) == EFFECT_NONE
    assert ctl.command(act("learn", "10")) == EFFECT_NONE
    assert ctl.command(act("learn", "999")) == EFFECT_NONE
    assert ctl.command(act("learn", "x")) == EFFECT_NONE


def test_undrilled_recall_asks_first_and_never_locks() -> None:
    ctl = two_sections(total=52, drilled=12)
    assert ctl.command(act("learn", "10")) == EFFECT_NONE and ctl.confirm == 10
    row = ctl.row(10)
    assert row is not None
    assert row.recall_warning == (
        "Recall cards for 3.1: 12 / 52 drilled. Drilling them first helps."
    )
    ctl.command(act("cancel"))
    assert ctl.confirm is None
    ctl.command(act("learn", "10"))
    assert ctl.command(act("learn_anyway", "10")) == EFFECT_LEARN
    assert ctl.confirm is None and ctl.learn_did == 10


def test_learn_next_also_asks_about_recall() -> None:
    ctl = two_sections(total=4, drilled=0)
    assert ctl.command(act("learn_next")) == EFFECT_NONE and ctl.confirm == 10


def test_learn_anyway_cannot_open_a_row_with_nothing_to_learn() -> None:
    s1 = section(10, "3.1", [note("x.a", 1)], 5, 0)
    ctl = ProgressController([course([s1])], {1: NoteProgress(stage=LEARNED, handed_off=True)})
    assert ctl.command(act("learn_anyway", "10")) == EFFECT_NONE


def test_new_data_keeps_a_pending_question_only_while_the_row_exists() -> None:
    ctl = two_sections(total=4, drilled=0)
    ctl.command(act("learn", "10"))
    ctl.update(ctl.courses, {})
    assert ctl.confirm == 10
    ctl.update([course([section(30, "4.1", [note("y.a", 9)])])], {})
    assert ctl.confirm is None


def test_the_states_come_from_the_course() -> None:
    s1 = section(10, "3.1", [note("x.a", 1)])
    c = course([s1], {1: CardState("review", "review, due Mon Oct 19")})
    ctl = ProgressController([c], {1: NoteProgress(stage=LEARNED, handed_off=True)})
    model = ctl.model()
    assert model is not None and model.rows[0].chips[0].detail == "review, due Mon Oct 19"
