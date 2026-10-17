"""Math Path notes are left alone (v0.6.1): a note type with both a ``RecipeId`` and a
``Recipe`` field is never drilled, held back or released; the sections table counts it as
"can't drill" and the exam tracker as New."""

from __future__ import annotations

from pathlib import Path

from anki.cards import Card
from anki.collection import Collection
from anki_fixtures import add_math_path_model, add_note, deck
from exam_scene import build as build_exam
from exam_scene import storage

from recalldrill.anki_io.exam_tracker import read_trackers
from recalldrill.anki_io.holdback import apply_hold_back, plan_hold_back
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.sections import read_progress
from recalldrill.anki_io.select import Scope, SelectOptions, select_cards
from recalldrill.storage import Storage


def _mp_note(col: Collection, did: int, rid: str, tags: tuple[str, ...] = ()) -> Card:
    note = add_note(
        col,
        "Math Path recipe",
        did,  # type: ignore[arg-type]
        {
            "Title": f"Solve {rid}",
            "Section": "3.2",
            "RecipeId": rid,
            "Version": "1",
            "Prompt": "Solve: x^2 = 4",
            "Recipe": "{}",
        },
        ("mp::recipe", *tags),
    )
    return note.cards()[0]


def _lab2(col: Collection, tmp_path: Path) -> tuple[Storage, int, list[Card], Card, Card]:
    """Lab 2 with two chapter subdecks: four ordinary new cards, a suspended Math Path
    note and an unsuspended one."""
    add_math_path_model(col)
    st = storage(tmp_path)
    lab2 = int(deck(col, "Lab::Lab 2"))
    ch9 = int(deck(col, "Lab::Lab 2::Ch 9"))
    plain: list[Card] = []
    for i in range(4):
        note = add_note(col, "Basic", ch9, {"Front": f"q{i}", "Back": f"a{i}"}, ())  # type: ignore[arg-type]
        plain.append(note.cards()[0])
    suspended = _mp_note(col, ch9, "ca.quad.solve_factoring")
    col.sched.suspend_cards([suspended.id])
    loose = _mp_note(col, ch9, "ca.quad.solve_formula")
    return st, lab2, plain, suspended, loose


def test_drill_next_never_picks_math_path_notes(col: Collection, tmp_path: Path) -> None:
    _st, lab2, plain, suspended, loose = _lab2(col, tmp_path)
    sel = select_cards(col, Scope(deck_id=lab2), SelectOptions(), MappingTable(col))
    picked = {c.snap.cid for c in sel.picked}
    assert picked == {c.id for c in plain}
    assert suspended.id not in picked and loose.id not in picked
    assert sel.ineligible["math_path"] == 2


def test_the_rule_is_the_two_fields_whatever_the_note_type_is_called(
    col: Collection, tmp_path: Path
) -> None:
    add_math_path_model(col, "My recipes")
    ch = int(deck(col, "Lab::Lab 2::Ch 9"))
    note = add_note(
        col, "My recipes", ch,  # type: ignore[arg-type]
        {"Title": "t", "RecipeId": "x.y.z", "Recipe": "{}"},
    )
    sel = select_cards(col, Scope(deck_id=ch), SelectOptions(), MappingTable(col))
    assert sel.ineligible["math_path"] == 1 and not sel.picked
    assert note.cards()[0].id not in {c.snap.cid for c in sel.picked}


def test_hold_back_neither_holds_nor_releases_them(col: Collection, tmp_path: Path) -> None:
    st, lab2, plain, suspended, loose = _lab2(col, tmp_path)
    # Even a suspended Math Path note that carries rd::held is not released.
    held = _mp_note(col, int(deck(col, "Lab::Lab 2::Ch 9")), "ca.abs.solve_eq", ("rd::held",))
    col.sched.suspend_cards([held.id])
    plan = plan_hold_back(col, st, lab2)
    assert set(plan.suspend) == {c.id for c in plain}
    assert loose.id in plan.left_alone and dict(plan.left_alone_reasons) == {"math_path": 1}
    assert not plan.release
    apply_hold_back(col, plan)
    for card in (suspended, held):
        assert col.get_card(card.id).queue == -1
    assert col.get_card(loose.id).queue == 0  # still in the new queue, unsuspended
    again = plan_hold_back(col, st, lab2)
    assert not again.suspend and not again.release


def test_the_sections_table_puts_them_in_cant_drill(col: Collection, tmp_path: Path) -> None:
    st, lab2, _plain, _suspended, _loose = _lab2(col, tmp_path)
    p = read_progress(col, st, lab2)
    assert sum(r.cant_drill for r in p.rows) == 2
    assert sum(r.new for r in p.rows) == 4  # the four ordinary cards only


def test_the_exam_tracker_counts_them_as_new(col: Collection, tmp_path: Path) -> None:
    base = build_exam(col, storage(tmp_path / "a"))
    before = read_trackers(col, base.st).numbers[base.lab2]
    add_math_path_model(col)
    _mp_note(col, base.ch10, "ca.quad.solve_factoring")
    suspended = _mp_note(col, base.ch10, "ca.quad.solve_formula")
    col.sched.suspend_cards([suspended.id])
    after = read_trackers(col, base.st).numbers[base.lab2]
    assert after.new == before.new + 2
    assert after.drill == before.drill
