"""The progress map's model: chips, NEXT, the Recall line, what a session takes."""

from __future__ import annotations

import json
from typing import Any

from recipe_files import CH03, load

from math_path.config import Config
from math_path.course_model import (
    CardState,
    CourseData,
    SectionData,
    build_map,
    next_section,
    session_notes,
    unhanded,
)
from math_path.notes import RecipeNote
from math_path.progress import FADED, LEARNED, SOLO, NoteProgress
from math_path.recipe import Recipe, loads_recipe


def _recipe(base: Recipe, **changes: Any) -> Recipe:
    data = json.loads(json.dumps(base.raw))
    data.update(changes)
    return loads_recipe(json.dumps(data))


BASE = load(CH03 / "ca.quad.solve_factoring.json")


def note(
    rid: str, nid: int, prereq: list[str] | None = None, tags: tuple[str, ...] = ()
) -> RecipeNote:
    r = _recipe(BASE, id=rid, prerequisites=prereq or [], title=f"Title {rid}")
    return RecipeNote(nid, rid, 1, r.title, "3.2", r, "", tags, 1, 10, (nid * 10,))


def section(
    did: int, number: str, notes: list[RecipeNote], total: int = 0, drilled: int = 0
) -> SectionData:
    return SectionData(
        did, f"Course::{number} Name", f"{number} Name", tuple(notes), total, drilled, number
    )


def course(sections: list[SectionData], states: dict[int, CardState] | None = None) -> CourseData:
    notes = tuple(n for s in sections for n in s.notes)
    return CourseData(1, "Course", tuple(sections), states or {}, notes)


def test_chips_say_the_stage_what_a_locked_one_needs_and_where_a_learned_one_is() -> None:
    a, b, c, d = (
        note("x.a", 1),
        note("x.b", 2, ["x.a"]),
        note("x.c", 3),
        note("x.d", 4, tags=("mp::learned",)),
    )
    cs = course(
        [section(10, "3.1", [a, b, c, d])], {4: CardState("review", "review, due Mon Oct 19")}
    )
    progress = {1: NoteProgress(stage=FADED, faded_level=2), 3: NoteProgress(stage=SOLO)}
    m = build_map(cs, progress, Config())
    chips = {ch.nid: ch for ch in m.rows[0].chips}
    assert (chips[1].stage, chips[1].kind, chips[1].learnable) == ("Faded", "learning", True)
    assert (chips[2].stage, chips[2].detail, chips[2].kind) == (
        "Locked",
        "needs Title x.a",
        "locked",
    )
    assert chips[3].stage == "Solo"
    assert (chips[4].stage, chips[4].detail, chips[4].kind) == (
        "In Anki",
        "review, due Mon Oct 19",
        "learned",
    )
    assert not chips[2].learnable and not chips[4].learnable


def test_a_learned_recipe_unlocks_what_needed_it() -> None:
    a, b = note("x.a", 1), note("x.b", 2, ["x.a"])
    cs = course([section(10, "3.1", [a, b])])
    m = build_map(cs, {1: NoteProgress(stage=LEARNED, handed_off=True)}, Config())
    assert [c.stage for c in m.rows[0].chips] == ["In Anki", "Study"]
    pending = build_map(cs, {1: NoteProgress(stage=LEARNED)}, Config())
    assert (
        pending.rows[0].chips[0].stage == "Learned"
        and pending.rows[0].chips[0].detail == "ready to hand off"
    )
    assert pending.rows[0].chips[1].stage == "Study"  # learned counts for the lock
    off = build_map(cs, {}, Config(prereq_lock=False))
    assert off.rows[0].chips[1].stage == "Study"


def test_next_is_the_first_section_with_a_recipe_that_can_be_learned() -> None:
    a, b = note("x.a", 1), note("x.b", 2, ["x.a"])
    c = note("x.c", 3)
    cs = course([section(10, "3.1", [a]), section(11, "3.2", [b]), section(12, "3.3", [c])])
    m = build_map(cs, {1: NoteProgress(stage=LEARNED, handed_off=True)}, Config())
    assert [r.is_next for r in m.rows] == [False, True, False]  # 3.1 is done; 3.2 is unlocked now
    assert m.next_row is m.rows[1]
    assert (
        next_section(cs, {1: NoteProgress(stage=LEARNED, handed_off=True)}, Config())
        is cs.sections[1]
    )
    # 3.2 only has a recipe that needs one in 3.3: NEXT skips it
    locked_only = build_map(
        course([section(11, "3.2", [b]), section(12, "3.3", [a])]), {}, Config()
    )
    assert [r.is_next for r in locked_only.rows] == [False, True]
    assert [r.can_learn for r in locked_only.rows] == [False, True]
    done = {1: NoteProgress(stage=LEARNED, handed_off=True)}
    all_done = build_map(course([section(10, "3.1", [a])]), done, Config())
    assert all_done.next_row is None and not all_done.rows[0].can_learn
    assert next_section(course([section(10, "3.1", [a])]), done, Config()) is None


def test_the_recall_line_and_cell() -> None:
    a = note("x.a", 1)
    cs = course(
        [
            section(10, "3.3", [a], total=52, drilled=12),
            section(11, "3.4", [], 61, 61),
            section(12, "3.5", [], 0, 0),
        ]
    )
    rows = build_map(cs, {}, Config()).rows
    assert rows[0].recall_cell == "12 / 52"
    assert (
        rows[0].recall_warning
        == "Recall cards for 3.3: 12 / 52 drilled. Drilling them first helps."
    )
    assert rows[1].recall_cell == "61 / 61" and rows[1].recall_warning == ""
    assert rows[2].recall_cell == "—" and rows[2].recall_warning == ""


def test_an_unreadable_recipe_is_a_broken_chip_and_never_learnable() -> None:
    broken = RecipeNote(5, "x.broken", 1, "Broken", "3.2", None, "missing steps", (), 1, 10, (50,))
    m = build_map(course([section(10, "3.2", [broken])]), {}, Config())
    chip = m.rows[0].chips[0]
    assert (chip.stage, chip.kind, chip.detail, chip.learnable) == (
        "Unreadable",
        "broken",
        "missing steps",
        False,
    )
    assert not m.rows[0].can_learn


def test_a_session_takes_what_the_section_has_ready() -> None:
    notes = [note(f"x.{i}", i + 1) for i in range(5)]
    cs = course([section(10, "3.1", notes)])
    picked = session_notes(cs.sections[0], cs, {}, Config())
    assert [n.nid for n in picked] == [1, 2, 3]
    picked = session_notes(
        cs.sections[0], cs, {1: NoteProgress(stage=LEARNED)}, Config(problems_per_session=2)
    )
    assert [n.nid for n in picked] == [2, 3]


def test_unhanded_lists_learned_notes_that_never_reached_anki() -> None:
    a, b, c = note("x.a", 1), note("x.b", 2), note("x.c", 3, tags=("mp::learned",))
    progress = {
        1: NoteProgress(stage=LEARNED),
        2: NoteProgress(stage=LEARNED, handed_off=True),
        3: NoteProgress(stage=LEARNED),
    }
    assert [n.nid for n in unhanded([a, b, c], progress)] == [1]
