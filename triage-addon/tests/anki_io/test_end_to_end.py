"""A study session's worth of set-asides on a scratch collection shaped like a real one."""

from __future__ import annotations

import json
from pathlib import Path

from scenes import (
    add_note,
    card_ids,
    make_learning,
    new_collection,
    revlog_count,
    set_flag,
    state,
    states,
)

from card_triage.anki_io import triage

LECTURE = "A&P 1::Lecture::Lecture 3"
LAB = "A&P 1::Lab::Lab 3"
REVERSED = "Basic (and reversed card)"


def test_set_aside_undo_and_release_leave_every_card_as_it_started(tmp_path: Path) -> None:
    col = new_collection(tmp_path)
    try:
        # 20 new cards over two notetypes: 8 one-card notes and 6 two-card notes.
        mine = []
        for i in range(8):
            mine += card_ids(col, add_note(col, LECTURE if i % 2 else LAB, f"basic {i}"))
        for i in range(6):
            deck = LAB if i % 2 else LECTURE
            mine += card_ids(col, add_note(col, deck, f"pair {i}", model=REVERSED))
        assert len(mine) == 20

        # 3 cards another tool suspended: red flag, rd::drill tag.
        theirs = []
        for i in range(3):
            (cid,) = card_ids(col, add_note(col, LECTURE, f"drilled {i}", tags="rd::drill"))
            set_flag(col, cid, 1)
            col.sched.suspend_cards([cid])
            theirs.append(cid)

        make_learning(col, mine[2])  # one learning card
        set_flag(col, mine[4], 2)  # one with a prior flag
        everything = mine + theirs
        start = states(col, everything)
        theirs_start = states(col, theirs)
        revlogs = revlog_count(col)

        # Set aside 5: the learning card, the flagged one, a sibling pair's two cards, one more.
        pair_a, pair_b = mine[8], mine[9]
        chosen = [mine[2], mine[4], pair_a, pair_b, mine[0]]
        for cid in chosen:
            assert triage.set_aside(col, cid).verdict.value == "ok"

        assert set(triage.set_aside_cards(col)) == set(chosen)
        assert col.get_note(col.get_card(pair_a).nid).tags == ["triage"]
        assert json.loads(state(col, mine[4]).custom_data) == {"tri": 2}
        assert state(col, mine[2]).type == 1 and state(col, mine[2]).suspended
        assert states(col, theirs) == theirs_start  # never touched
        assert revlog_count(col) == revlogs

        # Undo the last one (mine[0]).
        col.undo()
        assert states(col, [mine[0]]) == {int(mine[0]): start[int(mine[0])]}
        assert set(triage.set_aside_cards(col)) == set(chosen[:4])

        # Release all.
        assert triage.release_all(col).released == 4

        assert states(col, everything) == start  # field by field, all 23 cards
        assert states(col, theirs) == theirs_start
        assert revlog_count(col) == revlogs
        assert triage.set_aside_cards(col) == []
        assert not col.find_notes("tag:triage")
        assert len(col.find_cards("tag:rd::drill is:suspended flag:1")) == 3
    finally:
        col.close()
