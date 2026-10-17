"""Reading courses, sections, Recall Drill counts and card states from a scratch collection."""

from __future__ import annotations

from pathlib import Path

from anki.cards import CardId
from anki.collection import Collection
from anki.consts import CARD_TYPE_LRN, CARD_TYPE_REV, QUEUE_TYPE_LRN, QUEUE_TYPE_REV
from anki.notes import NoteId
from scenes import CHAPTER, SECTIONS, make_course, recipe_dir

from math_path.anki_io import courses, handoff, importer, notetype
from math_path.anki_io.courses import card_state, read_courses, section_number
from math_path.course_model import natural_key


def _import_all(col: Collection, tmp_path: Path) -> list[int]:
    make_course(col)
    files = importer.scan_folder(recipe_dir(tmp_path))
    return list(importer.apply_import(col, importer.plan_import(col, files)).nids)


def _basic(col: Collection, deck: int, front: str, tags: tuple[str, ...]) -> int:
    note = col.new_note(col.models.by_name("Basic"))  # type: ignore[arg-type]
    note["Front"], note["Back"] = front, "x"
    for t in tags:
        note.add_tag(t)
    col.add_note(note, deck)  # type: ignore[arg-type]
    return int(note.id)


def test_natural_order_is_textbook_order() -> None:
    names = ["Ch 10 X::3.10 B", "Ch 03 X::3.2 A", "Ch 03 X::3.10 C", "Ch 3 X::3.1 A"]
    assert sorted(names, key=natural_key) == [
        "Ch 3 X::3.1 A", "Ch 03 X::3.2 A", "Ch 03 X::3.10 C", "Ch 10 X::3.10 B",
    ]  # fmt: skip


def test_section_numbers_come_from_the_deck_name() -> None:
    assert section_number("3.2 Quadratic Equations, Functions") == "3.2"
    assert section_number("3.10 Later") == "3.10"
    assert section_number("12 Whole number") == "12"
    assert section_number("Ch 03 Quadratic") == ""
    assert section_number("3.2Quadratic") == ""


def test_a_course_is_a_top_deck_with_one_section_per_section_deck(
    col: Collection, tmp_path: Path
) -> None:
    _import_all(col, tmp_path)
    (course,) = read_courses(col)
    assert course.name == "College Algebra"
    assert [s.number for s in course.sections] == ["3.1", "3.2", "3.3", "3.4", "3.5"]
    assert [s.label for s in course.sections] == [
        SECTIONS[n] for n in ("3.1", "3.2", "3.3", "3.4", "3.5")
    ]
    assert [len(s.notes) for s in course.sections] == [5, 7, 10, 3, 5]
    assert len(course.notes) == 30 and len(course.states) == 30


def test_a_section_with_no_recipes_still_has_a_row_and_a_chapter_deck_does_not(
    col: Collection, tmp_path: Path
) -> None:
    _import_all(col, tmp_path)
    col.decks.id(f"{CHAPTER}::3.6 Nothing imported yet")
    col.decks.id("College Algebra::Appendix")
    (course,) = read_courses(col)
    assert [s.number for s in course.sections][-1] == "3.6"
    assert course.sections[-1].notes == ()
    assert all("Appendix" not in s.name and s.name != CHAPTER for s in course.sections)


def test_a_deck_holding_recipes_is_a_section_even_without_a_number(
    col: Collection, tmp_path: Path
) -> None:
    _import_all(col, tmp_path)
    odd = int(col.decks.id("College Algebra::Extra practice") or 0)
    nid = _import_all_one(col, odd)
    (course,) = read_courses(col)
    assert "Extra practice" in [s.label for s in course.sections]
    assert nid in {n.nid for s in course.sections for n in s.notes}


def _import_all_one(col: Collection, did: int) -> int:
    note = col.new_note(notetype.ensure_notetype(col))
    note["RecipeId"], note["Recipe"] = "x.y.z", "{}"
    col.add_note(note, did)  # type: ignore[arg-type]
    return int(note.id)


def test_the_recall_cells_count_exact_tags_and_never_a_wildcard(
    col: Collection, tmp_path: Path
) -> None:
    course_ids = make_course(col)
    d32 = course_ids.decks["3.2"]
    d33 = course_ids.decks["3.3"]
    for i in range(4):
        _basic(col, d32, f"a{i}", ("rd::drill::A1",))
    for i in range(3):
        _basic(col, d32, f"b{i}", ("rd::drilled",))
    for i in range(2):
        _basic(col, d32, f"c{i}", ("rd::undrilled",))
    _basic(col, d32, "both", ("rd::drill", "rd::drilled"))
    _basic(col, d32, "held", ("rd::held",))  # no wildcard: rd::held is not a Recall card here
    _basic(col, d32, "hard", ("rd::hard",))
    _basic(col, d32, "plain", ())
    _basic(col, d33, "other section", ("rd::drilled",))
    sub = int(col.decks.id(f"{CHAPTER}::{SECTIONS['3.2']}::Sub") or 0)
    _basic(col, sub, "in a subdeck", ("rd::drill::A2",))  # subdecks of the section count
    files = importer.scan_folder(recipe_dir(tmp_path, limit=1), smoke=False)
    importer.apply_import(
        col, importer.plan_import(col, files), {f.recipe.id: d32 for f in files if f.recipe}
    )
    (course,) = read_courses(col)
    s32 = next(s for s in course.sections if s.number == "3.2")
    assert (s32.recall_total, s32.recall_drilled) == (11, 6)
    s33 = next(s for s in course.sections if s.number == "3.3")
    assert (s33.recall_total, s33.recall_drilled) == (1, 1)
    s31 = next(s for s in course.sections if s.number == "3.1")
    assert (s31.recall_total, s31.recall_drilled) == (0, 0)


def test_two_courses_are_listed_in_name_order(col: Collection, tmp_path: Path) -> None:
    _import_all(col, tmp_path)
    other = int(col.decks.id("Statistics::Ch 01::1.1 Data") or 0)
    nid = _import_all_one(col, other)
    names = [c.name for c in read_courses(col)]
    assert names == ["College Algebra", "Statistics"]
    stats = read_courses(col)[1]
    assert [n.nid for n in stats.notes] == [nid] and stats.sections[0].number == "1.1"


def test_no_notes_no_courses(col: Collection) -> None:
    assert read_courses(col) == []
    notetype.ensure_notetype(col)
    assert read_courses(col) == []


def test_card_states_in_words(col: Collection, tmp_path: Path) -> None:
    nids = _import_all(col, tmp_path)

    def card(i: int):  # type: ignore[no-untyped-def]
        return col.get_note(NoteId(nids[i])).cards()[0]

    assert card_state(col, card(0)).text == "suspended"
    handoff.apply_handoff(col, handoff.plan_handoff(col, [nids[1]]))
    assert card_state(col, card(1)).text == "buried until tomorrow"
    c = card(2)
    col.sched.unsuspend_cards([c.id])
    assert card_state(col, col.get_card(CardId(c.id))).text == "new"
    r = col.get_card(CardId(c.id))
    r.type, r.queue, r.ivl, r.due = CARD_TYPE_REV, QUEUE_TYPE_REV, 3, col.sched.today + 3  # type: ignore[assignment]
    col.update_card(r)
    state = card_state(col, col.get_card(CardId(c.id)))
    assert (
        state.kind == "review"
        and state.text.startswith("review, due ")
        and "today" not in state.text
    )
    r.due = col.sched.today - 1
    col.update_card(r)
    assert card_state(col, col.get_card(CardId(c.id))).text == "review, due today"
    r.type, r.queue = CARD_TYPE_LRN, QUEUE_TYPE_LRN  # type: ignore[assignment]
    col.update_card(r)
    assert card_state(col, col.get_card(CardId(c.id))).kind == "learning"
    assert courses.TAG_DRILL == "rd::drill"
