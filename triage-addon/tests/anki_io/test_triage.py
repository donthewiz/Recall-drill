from __future__ import annotations

import json
from pathlib import Path

import pytest
from anki.collection import Collection
from scenes import (
    add_note,
    card_ids,
    make_learning,
    make_review,
    new_collection,
    revlog_count,
    set_custom_data,
    set_flag,
    state,
    states,
)

from card_triage.anki_io import triage
from card_triage.rules import Verdict


@pytest.fixture
def col(tmp_path: Path):
    c = new_collection(tmp_path)
    yield c
    c.close()


def undo_label(col: Collection) -> str:
    return col.undo_status().undo


def test_new_card_is_set_aside_and_one_undo_restores_it(col: Collection) -> None:
    nid = add_note(col, "A&P 1::Lecture::Lecture 3", "ligament")
    (cid,) = card_ids(col, nid)
    before = state(col, cid)
    revlogs = revlog_count(col)

    out = triage.set_aside(col, cid)

    assert out.verdict is Verdict.OK
    assert out.changes.study_queues  # the reviewer moves on to the next card
    after = state(col, cid)
    assert json.loads(after.custom_data) == {"tri": 0}
    assert (after.flag, after.suspended, after.type, after.due) == (1, True, 0, before.due)
    assert after.tags == ("triage",)
    assert revlog_count(col) == revlogs
    assert undo_label(col) == "Set aside card"

    col.undo()

    assert state(col, cid) == before
    assert col.undo_status().undo != "Set aside card"


def test_prior_flag_and_prior_custom_data_are_kept_and_restored(col: Collection) -> None:
    nid = add_note(col, "d", "x", tags="rd::drill keep")
    (cid,) = card_ids(col, nid)
    set_flag(col, cid, 2)
    set_custom_data(col, cid, '{"fsrs":"a"}')
    before = state(col, cid)

    triage.set_aside(col, cid)

    after = state(col, cid)
    assert json.loads(after.custom_data) == {"fsrs": "a", "tri": 2}
    assert after.flag == 1
    assert after.tags == ("keep", "rd::drill", "triage")

    col.undo()
    assert state(col, cid) == before


def test_learning_card_stays_learning(col: Collection) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    make_learning(col, cid)
    before = state(col, cid)

    assert triage.set_aside(col, cid).verdict is Verdict.OK
    mid = state(col, cid)
    assert (mid.type, mid.due, mid.left) == (1, before.due, before.left)
    assert mid.suspended

    col.undo()
    assert state(col, cid) == before


@pytest.mark.parametrize("relearning", [False, True])
def test_review_and_relearning_cards_are_refused_unchanged(
    col: Collection, relearning: bool
) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    make_review(col, cid, relearning=relearning)
    before = state(col, cid)
    status = col.undo_status().undo

    out = triage.set_aside(col, cid)

    assert out.verdict is Verdict.NOT_NEW_OR_LEARNING
    assert state(col, cid) == before
    assert col.undo_status().undo == status  # no undo step was made


def test_a_card_that_is_already_set_aside_is_not_marked_twice(col: Collection) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    set_flag(col, cid, 3)
    triage.set_aside(col, cid)
    before = state(col, cid)

    out = triage.set_aside(col, cid)

    assert out.verdict is Verdict.ALREADY_SET_ASIDE
    assert state(col, cid) == before
    assert json.loads(before.custom_data) == {"tri": 3}


def test_a_card_suspended_by_another_tool_is_refused(col: Collection) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    col.sched.suspend_cards([cid])
    before = state(col, cid)
    assert triage.set_aside(col, cid).verdict is Verdict.SUSPENDED
    assert state(col, cid) == before


def test_custom_data_with_no_room_is_refused_and_nothing_changes(col: Collection) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    set_custom_data(col, cid, json.dumps({"a": "x" * 85}, separators=(",", ":")))
    before = state(col, cid)

    assert triage.set_aside(col, cid).verdict is Verdict.TOO_BIG
    assert state(col, cid) == before


def test_has_cd_finds_exactly_the_set_aside_cards(col: Collection) -> None:
    cids = [card_ids(col, add_note(col, "d", f"c{i}"))[0] for i in range(4)]
    set_custom_data(col, cids[3], '{"other":1}')  # custom_data, but not ours
    col.sched.suspend_cards([cids[2]])  # suspended, but not ours
    triage.set_aside(col, cids[0])
    triage.set_aside(col, cids[1])

    assert set(triage.set_aside_cards(col)) == {cids[0], cids[1]}


def test_learn_again_count_counts_only_learn_type_agains(col: Collection) -> None:
    from scenes import add_revlog

    (cid,) = card_ids(col, add_note(col, "d", "x"))
    make_learning(col, cid, agains=2)
    add_revlog(col, cid, type_=0, ease=3)  # learn, Good
    add_revlog(col, cid, type_=1, ease=1)  # review, Again
    assert triage.learn_again_count(col, cid) == 2


# release ------------------------------------------------------------------------------------


def test_release_with_nothing_set_aside_changes_nothing(col: Collection) -> None:
    add_note(col, "d", "x")
    status = col.undo_status().undo
    out = triage.release_all(col)
    assert out.released == 0
    assert col.undo_status().undo == status


def test_release_returns_cards_to_where_they_were_as_one_undo_step(col: Collection) -> None:
    n1 = add_note(col, "d", "a")
    n2 = add_note(col, "d", "b", tags="keep")
    (c1,) = card_ids(col, n1)
    (c2,) = card_ids(col, n2)
    set_flag(col, c2, 5)
    set_custom_data(col, c2, '{"k":1}')
    make_learning(col, c1)
    before = states(col, [c1, c2])
    revlogs = revlog_count(col)
    triage.set_aside(col, c1)
    triage.set_aside(col, c2)
    set_aside_state = states(col, [c1, c2])

    out = triage.release_all(col)

    assert out.released == 2
    assert states(col, [c1, c2]) == before
    assert revlog_count(col) == revlogs
    assert undo_label(col) == "Release set-aside cards"
    assert triage.set_aside_cards(col) == []

    col.undo()  # one step brings the set-aside state back
    assert states(col, [c1, c2]) == set_aside_state


def test_release_leaves_a_sibling_suspended_by_another_tool(col: Collection) -> None:
    nid = add_note(col, "d", "pair", model="Basic (and reversed card)")
    mine, sibling = card_ids(col, nid)
    col.sched.suspend_cards([sibling])
    set_flag(col, sibling, 1)
    sibling_before = state(col, sibling)
    triage.set_aside(col, mine)

    triage.release_all(col)

    assert state(col, sibling) == sibling_before  # still suspended, red, no marker
    assert state(col, mine).suspended is False
    assert state(col, mine).tags == ()  # no card of the note is set aside any more


def test_release_cleans_a_card_unsuspended_by_hand(col: Collection) -> None:
    (cid,) = card_ids(col, add_note(col, "d", "x"))
    set_flag(col, cid, 4)
    before = state(col, cid)
    triage.set_aside(col, cid)
    col.sched.unsuspend_cards([cid])  # Don did this in Browse

    out = triage.release_all(col)

    assert out.released == 1
    assert state(col, cid) == before


def test_flag_goes_back_only_if_still_red(col: Collection) -> None:
    a = card_ids(col, add_note(col, "d", "a"))[0]
    b = card_ids(col, add_note(col, "d", "b"))[0]
    set_flag(col, a, 2)
    set_flag(col, b, 2)
    triage.set_aside(col, a)
    triage.set_aside(col, b)
    set_flag(col, b, 6)  # Don re-flagged it since

    triage.release_all(col)

    assert state(col, a).flag == 2
    assert state(col, b).flag == 6


def test_both_cards_of_a_note_set_aside_then_released_drop_the_tag_and_keep_others(
    col: Collection,
) -> None:
    nid = add_note(col, "d", "pair", model="Basic (and reversed card)", tags="keep")
    first, second = card_ids(col, nid)
    triage.set_aside(col, first)
    triage.set_aside(col, second)
    assert set(col.get_note(nid).tags) == {"keep", "triage"}

    triage.release_all(col)

    assert col.get_note(nid).tags == ["keep"]
