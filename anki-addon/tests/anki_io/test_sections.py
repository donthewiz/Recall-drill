"""Section progress (v0.3) on a scratch collection with subdecks."""

from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path

from anki.cards import Card, CardId
from anki.collection import Collection
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki_fixtures import add_note, deck

from recalldrill import history_store
from recalldrill.anki_io.holdback import HoldBackPlan, apply_hold_back, plan_hold_back
from recalldrill.anki_io.sections import SELF_LABEL, children, read_sections
from recalldrill.sections import render_text
from recalldrill.storage import Storage


def _storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def _card(col: Collection, did: int, front: str, tags: tuple[str, ...] = ()) -> Card:
    note = add_note(col, "Basic", did, {"Front": front, "Back": f"{front} a"}, tags)  # type: ignore[arg-type]
    return note.cards()[0]


def _handoff(st: Storage, key: str, cards: list[Card]) -> None:
    stamp = time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime())
    history_store.append_handoff(
        st,
        key,
        {
            "type": "handoff",
            "sessionId": "s1",
            "timestamp": stamp,
            "groups": {"drilled_new": [c.id for c in cards]},
            "cards": [{"cid": c.id, "nid": c.nid, "ord": 0} for c in cards],
        },
    )


def course(col: Collection, st: Storage) -> int:
    """Lab 2 with Bones (all drilled), Joints (some held, some drilled, one untouched, a
    nested deck) and Muscles (released undrilled, one introduced). Created out of
    name order on purpose."""
    lab = int(deck(col, "Lab 2"))
    muscles = int(deck(col, "Lab 2::Muscles"))
    bones = int(deck(col, "Lab 2::Bones"))
    joints = int(deck(col, "Lab 2::Joints"))
    spine = int(deck(col, "Lab 2::Joints::Spine"))

    bone_cards = [_card(col, bones, f"bone{i}", ("rd::drilled",)) for i in range(4)]
    _handoff(st, str(bones), bone_cards)

    drilled_joints = [_card(col, joints, f"joint{i}", ("rd::drilled",)) for i in range(2)]
    _handoff(st, str(joints), drilled_joints)
    for i in range(2):
        _card(col, joints, f"held{i}", ("rd::drill::A",))
    _card(col, spine, "spine held", ("rd::drill::B",))
    _card(col, joints, "untouched")
    apply_hold_back(col, _plan_only_held(col, st, joints))

    for i in range(3):
        _card(col, muscles, f"muscle{i}", ("rd::undrilled",))
    rated = _card(col, muscles, "old")
    rated.type, rated.queue, rated.ivl, rated.due = CARD_TYPE_REV, QUEUE_TYPE_REV, 9, 100  # type: ignore[assignment]
    col.update_card(rated)
    return lab


def _plan_only_held(col: Collection, st: Storage, joints: int) -> HoldBackPlan:
    """Holds back the tagged cards only: 'untouched' stays out of Anki, not held."""
    plan = plan_hold_back(col, st, joints)
    untouched = next(
        c
        for c in plan.suspend
        if col.get_note(col.get_card(CardId(c)).nid).fields[0] == "untouched"
    )
    keep = tuple(c for c in plan.suspend if c != untouched)
    return replace(plan, suspend=keep)


def test_section_progress_counts_and_done(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab = course(col, st)
    rows = read_sections(col, st, lab)
    # Deck-tree order (by name), not creation order.
    assert [r.label for r in rows] == ["Bones", "Joints", "Muscles"]
    bones, joints, muscles = rows
    assert (bones.cards, bones.drilled, bones.released, bones.held, bones.open) == (4, 4, 0, 0, 0)
    assert bones.done and bones.status == "done" and bones.pct_drilled == 100
    # Joints includes its nested Spine deck: 2 drilled, 3 held (one in Spine), 1 untouched.
    assert (joints.cards, joints.drilled, joints.held, joints.open) == (6, 2, 3, 1)
    assert not joints.done and joints.status == "4 to go" and joints.pct_drilled == 33
    assert (muscles.cards, muscles.released, muscles.introduced, muscles.new) == (4, 3, 1, 3)
    assert muscles.done and muscles.status == "done" and muscles.drilled == 0
    assert render_text(rows).splitlines() == [
        "Section  Cards  Drilled  Released undrilled  Held / waiting  Not in Anki, not held  "
        "% drilled  Status",
        "Bones    4      4        0                   0               0                      "
        "100%       done",
        "Joints   6      2        0                   3               1                      "
        "33%        4 to go",
        "Muscles  4      0        3                   0               0                      "
        "0%         done",
    ]
    assert [r.did for r in rows] == [d for d, _n in children(col, lab)]


def test_a_section_without_new_cards_and_the_chosen_decks_own_cards(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Lab 2"))
    old = int(deck(col, "Lab 2::Old"))
    deck(col, "Lab 2::Empty")  # a subdeck with no cards at all
    for did, front in ((old, "a"), (old, "b")):
        c = _card(col, did, front)
        c.type, c.queue, c.ivl, c.due = CARD_TYPE_REV, QUEUE_TYPE_REV, 30, 100  # type: ignore[assignment]
        col.update_card(c)
    _card(col, lab, "direct")
    rows = read_sections(col, st, lab)
    # Subdecks come in the order their cards were made; one without cards goes last.
    assert [r.label for r in rows] == [SELF_LABEL, "Old", "Empty"]
    by = {r.label: r for r in rows}
    assert by["Old"].status == "done (no new cards)" and by["Old"].new == 0
    assert by[SELF_LABEL].open == 1 and by[SELF_LABEL].status == "1 to go"
    # A deck with no subdecks and no cards has no rows; with cards only, its own row.
    assert read_sections(col, st, int(deck(col, "Nothing"))) == []
    only = int(deck(col, "Solo"))
    _card(col, only, "s")
    (row,) = read_sections(col, st, only)
    assert row.label == SELF_LABEL and row.open == 1


def test_cards_in_a_filtered_deck_count_for_their_home_section(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Lab 2"))
    a = _card(col, int(deck(col, "Lab 2::A")), "a")
    _card(col, int(deck(col, "Lab 2::B")), "b")
    fid = col.decks.new_filtered("Cram")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [[f"cid:{a.id}", 100, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    rows = {r.label: r for r in read_sections(col, st, lab)}
    assert rows["A"].cards == 1 and rows["B"].cards == 1
