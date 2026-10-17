"""Handoff B on scratch collections: unsuspended, front of the new queue, buried, mp::learned,
one undo step, back after the rollover."""

from __future__ import annotations

from pathlib import Path

import pytest
from anki.cards import CardId
from anki.collection import Collection
from anki.consts import (
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_SUSPENDED,
)
from anki.notes import NoteId
from scenes import make_course, recipe_dir

from math_path.anki_io import handoff, importer, notetype
from math_path.anki_io.undo import StepFailed


def _import(col: Collection, tmp_path: Path, limit: int = 6) -> list[int]:
    make_course(col)
    files = importer.scan_folder(recipe_dir(tmp_path, limit=limit))
    summary = importer.apply_import(col, importer.plan_import(col, files))
    return list(summary.nids)


def _other_new_cards(col: Collection, n: int = 3) -> list[int]:
    deck = int(
        col.decks.id(
            "College Algebra::Ch 03 Quadratic Functions and Equations::3.1 The Complex Numbers"
        )
        or 0
    )
    out: list[int] = []
    for i in range(n):
        note = col.new_note(col.models.by_name("Basic"))  # type: ignore[arg-type]
        note["Front"], note["Back"] = f"plain {i}", "x"
        col.add_note(note, deck)  # type: ignore[arg-type]
        out.append(int(note.cards()[0].id))
    return out


def _state(col: Collection, nid: int) -> tuple[int, int, int]:
    card = col.get_note(NoteId(nid)).cards()[0]
    return card.type, card.queue, card.due


def test_learned_recipes_are_unsuspended_repositioned_buried_and_tagged(
    col: Collection, tmp_path: Path
) -> None:
    nids = _import(col, tmp_path)
    others = _other_new_cards(col)
    learned = [nids[3], nids[1]]  # the order they were learned in
    plan = handoff.plan_handoff(col, learned)
    assert plan.nids == tuple(learned) and plan.has_changes
    assert len(plan.unsuspend) == 2 and len(plan.bury) == 2 and len(plan.reposition) == 2
    handoff.apply_handoff(col, plan)
    for nid in learned:
        note = col.get_note(NoteId(nid))
        assert "mp::learned" in note.tags
        t, q, _due = _state(col, nid)
        assert t == CARD_TYPE_NEW and q == QUEUE_TYPE_MANUALLY_BURIED  # unsuspended, then buried
    # The others stay suspended and without the tag.
    for nid in (nids[0], nids[2], nids[4], nids[5]):
        note = col.get_note(NoteId(nid))
        assert "mp::learned" not in note.tags
        assert _state(col, nid)[1] == QUEUE_TYPE_SUSPENDED
    # Front of the new queue, in the order learned; the deck's other new cards shift back.
    due = {nid: _state(col, nid)[2] for nid in learned}
    assert due[learned[0]] < due[learned[1]]
    assert due[learned[1]] < min(col.get_card(CardId(c)).due for c in others)
    assert min(due.values()) == 0
    assert col.undo_status().undo == "Math Path: hand off"


def test_planning_again_after_a_handoff_plans_only_nothing_new(
    col: Collection, tmp_path: Path
) -> None:
    nids = _import(col, tmp_path)
    handoff.apply_handoff(col, handoff.plan_handoff(col, nids[:2]))
    again = handoff.plan_handoff(col, nids[:2])
    assert not again.has_changes


def test_the_handoff_is_one_undo_step(col: Collection, tmp_path: Path) -> None:
    nids = _import(col, tmp_path)
    handoff.apply_handoff(col, handoff.plan_handoff(col, nids[:3]))
    assert col.undo_status().undo == "Math Path: hand off"
    col.undo()
    for nid in nids[:3]:
        note = col.get_note(NoteId(nid))
        assert "mp::learned" not in note.tags
        assert _state(col, nid)[1] == QUEUE_TYPE_SUSPENDED
    assert col.undo_status().undo != "Math Path: hand off"


def test_a_failure_halfway_undoes_it_all(
    col: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    nids = _import(col, tmp_path)
    plan = handoff.plan_handoff(col, nids[:2])

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(col.sched, "bury_cards", boom)
    with pytest.raises(StepFailed) as info:
        handoff.apply_handoff(col, plan)
    assert info.value.rolled_back
    for nid in nids[:2]:
        assert "mp::learned" not in col.get_note(NoteId(nid)).tags
        assert _state(col, nid)[1] == QUEUE_TYPE_SUSPENDED


def test_a_note_that_is_gone_is_skipped(col: Collection, tmp_path: Path) -> None:
    nids = _import(col, tmp_path)
    plan = handoff.plan_handoff(col, [nids[0], 999_999_999])
    assert plan.missing == (999_999_999,) and plan.nids == (nids[0],)
    handoff.apply_handoff(col, plan)
    assert "mp::learned" in col.get_note(NoteId(nids[0])).tags


def test_a_card_already_in_review_keeps_its_schedule(col: Collection, tmp_path: Path) -> None:
    nids = _import(col, tmp_path, limit=2)
    card = col.get_note(NoteId(nids[0])).cards()[0]
    col.sched.unsuspend_cards([card.id])
    card = col.get_card(card.id)
    card.type, card.queue, card.ivl, card.due = CARD_TYPE_REV, 2, 9, col.sched.today + 4  # type: ignore[assignment]
    col.update_card(card)
    plan = handoff.plan_handoff(col, [nids[0]])
    assert plan.reposition == () and plan.unsuspend == () and plan.bury == (card.id,)
    handoff.apply_handoff(col, plan)
    after = col.get_card(card.id)
    assert (after.type, after.ivl, after.due) == (CARD_TYPE_REV, 9, col.sched.today + 4)
    assert after.queue == QUEUE_TYPE_MANUALLY_BURIED


def test_math_path_never_sets_a_due_date_or_an_interval(col: Collection, tmp_path: Path) -> None:
    nids = _import(col, tmp_path, limit=3)
    handoff.apply_handoff(col, handoff.plan_handoff(col, nids))
    for nid in nids:
        card = col.get_note(NoteId(nid)).cards()[0]
        assert card.type == CARD_TYPE_NEW and card.ivl == 0 and card.reps == 0
        assert (
            col.db is not None
            and col.db.scalar("select count() from revlog where cid = ?", card.id) == 0
        )


def test_buried_cards_return_after_the_rollover(tmp_path: Path) -> None:
    path = str(tmp_path / "rollover.anki2")
    col = Collection(path)
    try:
        nids = _import(col, tmp_path / "w", limit=2) if (tmp_path / "w").mkdir() is None else []
        handoff.apply_handoff(col, handoff.plan_handoff(col, nids))
        cid = col.get_note(NoteId(nids[0])).cards()[0].id
        assert col.get_card(cid).queue == QUEUE_TYPE_MANUALLY_BURIED
        day0 = col.sched.today
        assert col.db is not None
        col.db.execute("update col set crt = crt - 86400")
    finally:
        col.close()
    col = Collection(path)
    try:
        assert col.sched.today == day0 + 1
        assert col.get_card(cid).queue == QUEUE_TYPE_NEW  # back in the new queue, unsuspended
    finally:
        col.close()


def test_the_note_type_survives_the_handoff(col: Collection, tmp_path: Path) -> None:
    nids = _import(col, tmp_path, limit=2)
    handoff.apply_handoff(col, handoff.plan_handoff(col, nids))
    again = {n.nid: n for n in notetype.read_notes(col)}
    assert set(again) == set(nids) and all(n.learned_tag for n in again.values())
