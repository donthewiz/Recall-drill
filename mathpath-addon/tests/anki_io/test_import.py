"""Importing recipes as suspended Math Path notes, on scratch collections."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from anki.collection import Collection
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.notes import NoteId
from recipe_files import CH03
from scenes import CHAPTER, make_course, recipe_dir

from math_path import recipe_note
from math_path.anki_io import importer, notetype
from math_path.anki_io.undo import StepFailed


def _import(col: Collection, folder: Path, picks: dict[str, int | None] | None = None):
    files = importer.scan_folder(folder)
    plan = importer.plan_import(col, files)
    return plan, importer.apply_import(col, plan, picks)


def test_the_note_type_is_created_with_the_contract_fields_and_one_template(
    col: Collection,
) -> None:
    assert col.models.by_name("Math Path recipe") is None
    model = notetype.ensure_notetype(col)
    assert [f["name"] for f in model["flds"]] == [
        "Title", "Section", "RecipeId", "Version", "Prompt", "Recipe", "Notes",
    ]  # fmt: skip
    assert [t["name"] for t in model["tmpls"]] == ["Problem"]
    assert "{{Title}}" in model["tmpls"][0]["qfmt"] and "{{Section}}" in model["tmpls"][0]["qfmt"]
    assert "pycmd('mathpath:open')" in model["tmpls"][0]["qfmt"]
    assert "Solve in Math Path" in model["tmpls"][0]["qfmt"]
    assert (
        "{{Prompt}}" in model["tmpls"][0]["afmt"] and "{{FrontSide}}" in model["tmpls"][0]["afmt"]
    )
    assert notetype.ensure_notetype(col)["id"] == model["id"]  # idempotent
    assert notetype.is_math_path_model(model)
    assert not notetype.is_math_path_model(col.models.by_name("Basic"))  # type: ignore[arg-type]


def test_all_thirty_import_suspended_in_section_decks_with_the_contract_tags(
    col: Collection, tmp_path: Path
) -> None:
    course = make_course(col)
    plan, summary = _import(col, recipe_dir(tmp_path))
    assert len(summary.added) == 30 and not summary.skipped and not summary.updated
    assert not plan.needing_deck
    notes = notetype.read_notes(col)
    assert len(notes) == 30
    by_section = {"3.1": 5, "3.2": 7, "3.3": 10, "3.4": 3, "3.5": 5}
    for number, count in by_section.items():
        cids = col.find_cards(f"did:{course.decks[number]}")
        assert len(cids) == count
    for n in notes:
        note = col.get_note(NoteId(n.nid))
        assert n.recipe is not None and n.error == ""
        assert set(note.tags) == {"mp::recipe", f"Recipe::{n.recipe_id}"}
        assert not any(t.lower().startswith("rd::") for t in note.tags)
        assert all(c.queue == QUEUE_TYPE_SUSPENDED for c in note.cards())
        assert "\\(" in note["Prompt"] or n.recipe_id == "ca.rat.no_solution"
        assert note["Notes"] == ""
        assert recipe_note.decode_recipe(note["Recipe"]) == json.loads(
            (CH03 / f"{n.recipe_id}.json").read_text(encoding="utf-8")
        )


def test_notes_are_added_in_file_name_order(col: Collection, tmp_path: Path) -> None:
    make_course(col)
    _import(col, recipe_dir(tmp_path))
    ids = [n.recipe_id for n in notetype.read_notes(col)]
    assert ids == sorted(ids) == [p.stem for p in sorted(CH03.glob("*.json"))]


def test_a_section_with_no_deck_or_several_waits_for_a_pick_and_skips_by_default(
    col: Collection, tmp_path: Path
) -> None:
    course = make_course(col, sections=("3.1", "3.2", "3.3", "3.4"))  # no 3.5 deck
    col.decks.id("Other Course::Ch 03 X::3.2 Quadratic Equations again")  # a second 3.2 deck
    folder = recipe_dir(tmp_path)
    files = importer.scan_folder(folder)
    plan = importer.plan_import(col, files)
    waiting = {i.recipe.id: i for i in plan.needing_deck if i.recipe is not None}
    assert {r for r in waiting if r.startswith("ca.abs.")} == {
        "ca.abs.solve_eq", "ca.abs.solve_ineq_greater", "ca.abs.solve_ineq_greater_eq",
        "ca.abs.solve_ineq_less", "ca.abs.solve_ineq_less_eq",
    }  # fmt: skip
    assert waiting["ca.abs.solve_eq"].candidates == ()
    # Two decks start with "3.2 ": the course name in the path chooses between them.
    assert not [r for r in waiting if r.startswith("ca.quad.solve_")]
    summary = importer.apply_import(col, plan)  # default: skip
    assert len(summary.added) == 25 and len(summary.skipped) == 5
    assert all("no deck picked" in why for _n, why in summary.skipped)
    # Now pick a deck for them.
    pick = int(col.decks.id("Pick me") or 0)
    plan2 = importer.plan_import(col, files)
    assert len(plan2.needing_deck) == 5 and plan2.count("unchanged") == 25
    summary2 = importer.apply_import(col, plan2, {r: pick for r in waiting})
    assert len(summary2.added) == 5
    assert len(col.find_cards(f"did:{pick}")) == 5
    assert course.decks["3.4"]


def test_two_matching_decks_with_no_course_to_tell_them_apart_ask(
    col: Collection, tmp_path: Path
) -> None:
    col.decks.id("Math::Ch 03::3.2 Quadratic Equations")
    col.decks.id("Stats::Ch 03::3.2 Something else")
    folder = tmp_path / "r"
    folder.mkdir()
    (folder / "ca.quad.solve_factoring.json").write_bytes(
        (CH03 / "ca.quad.solve_factoring.json").read_bytes()
    )
    plan = importer.plan_import(col, importer.scan_folder(folder))
    (item,) = plan.items
    assert item.needs_deck and len(item.candidates) == 2 and "several" in item.reason


def test_a_recipe_id_that_exists_is_updated_only_when_the_version_is_higher(
    col: Collection, tmp_path: Path
) -> None:
    make_course(col)
    folder = recipe_dir(tmp_path, limit=3)
    _import(col, folder)
    first = notetype.read_notes(col)[0]
    note = col.get_note(NoteId(first.nid))
    note["Notes"] = "my own note"
    col.update_note(note)
    col.sched.unsuspend_cards([c.id for c in note.cards()])
    cid = note.cards()[0].id
    due_before = col.get_card(cid).due
    # Same version again: left alone.
    plan, summary = _import(col, folder)
    assert plan.count("unchanged") == 3 and not summary.added and not summary.updated
    # A higher version: fields change, scheduling and tags stay.
    path = folder / f"{first.recipe_id}.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["version"] = 2
    data["title"] = "New title"
    path.write_text(json.dumps(data), encoding="utf-8")
    plan, summary = _import(col, folder)
    assert summary.updated == (first.recipe_id,) and not summary.added
    again = col.get_note(NoteId(first.nid))
    assert again["Title"] == "New title" and again["Version"] == "2"
    assert again["Notes"] == "my own note"
    assert set(again.tags) == {"mp::recipe", f"Recipe::{first.recipe_id}"}
    assert col.get_card(cid).queue != QUEUE_TYPE_SUSPENDED  # not re-suspended
    assert col.get_card(cid).due == due_before
    # A lower version never downgrades.
    data["version"] = 1
    data["title"] = "Old title"
    path.write_text(json.dumps(data), encoding="utf-8")
    plan, summary = _import(col, folder)
    assert not summary.updated and col.get_note(NoteId(first.nid))["Title"] == "New title"


def test_files_that_are_not_recipes_are_refused_with_a_reason(
    col: Collection, tmp_path: Path
) -> None:
    make_course(col)
    folder = recipe_dir(tmp_path, limit=2)
    (folder / "a.json").write_text("{not json", encoding="utf-8")
    (folder / "b.json").write_text(json.dumps({"format": "other/1", "id": "x"}), encoding="utf-8")
    (folder / "c.json").write_text(json.dumps(["list"]), encoding="utf-8")
    bad = json.loads((CH03 / "ca.cx.add_sub.json").read_text(encoding="utf-8"))
    del bad["steps"]
    (folder / "d.json").write_text(json.dumps(bad), encoding="utf-8")
    (folder / "notes.txt").write_text("ignored", encoding="utf-8")
    plan, summary = _import(col, folder)
    reasons = dict(summary.skipped)
    assert len(summary.added) == 2
    assert "not valid JSON" in reasons["a.json"]
    assert "other/1" in reasons["b.json"] and "mathpath-recipe/1" in reasons["b.json"]
    assert "c.json" in reasons
    assert "steps" in reasons["d.json"]
    assert "notes.txt" not in reasons


def test_a_recipe_that_cannot_make_a_problem_is_refused(col: Collection, tmp_path: Path) -> None:
    make_course(col)
    folder = tmp_path / "r"
    folder.mkdir()
    data = json.loads((CH03 / "ca.quad.solve_factoring.json").read_text(encoding="utf-8"))
    data["constraints"] = ["p == p + 1"]  # nothing satisfies it
    (folder / "broken.json").write_text(json.dumps(data), encoding="utf-8")
    plan, summary = _import(col, folder)
    assert not summary.added
    assert "can't generate a problem" in dict(summary.skipped)["broken.json"]


def test_a_repeated_recipe_id_in_one_folder_keeps_the_higher_version(
    col: Collection, tmp_path: Path
) -> None:
    make_course(col)
    folder = tmp_path / "r"
    folder.mkdir()
    base = json.loads((CH03 / "ca.cx.add_sub.json").read_text(encoding="utf-8"))
    (folder / "a.json").write_text(json.dumps(base), encoding="utf-8")
    (folder / "b.json").write_text(json.dumps(dict(base, version=3)), encoding="utf-8")
    plan, summary = _import(col, folder)
    assert len(summary.added) == 1 and col.get_note(NoteId(summary.nids[0]))["Version"] == "3"
    assert "a.json" in {n for n, _ in summary.skipped} or summary.skipped[0][0] == base["id"]


def test_one_import_is_one_undo_step(col: Collection, tmp_path: Path) -> None:
    make_course(col)
    _import(col, recipe_dir(tmp_path, limit=5))
    assert col.undo_status().undo == "Math Path: import recipes"
    col.undo()
    assert notetype.read_notes(col) == []


def test_a_failure_halfway_undoes_everything(
    col: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    make_course(col)
    folder = recipe_dir(tmp_path, limit=4)
    plan = importer.plan_import(col, importer.scan_folder(folder))
    calls = {"n": 0}
    real = importer.example_prompt_html

    def flaky(recipe, seed=1000):  # type: ignore[no-untyped-def]
        calls["n"] += 1
        if calls["n"] == 3:
            raise RuntimeError("boom")
        return real(recipe, seed)

    monkeypatch.setattr(importer, "example_prompt_html", flaky)
    with pytest.raises(StepFailed) as info:
        importer.apply_import(col, plan)
    assert info.value.rolled_back
    assert notetype.read_notes(col) == []


def test_the_chapter_deck_is_not_used_for_a_section(col: Collection, tmp_path: Path) -> None:
    col.decks.id(CHAPTER)  # only the chapter exists
    plan = importer.plan_import(
        col, importer.scan_folder(recipe_dir(tmp_path, limit=1), smoke=False)
    )
    assert plan.items[0].needs_deck
