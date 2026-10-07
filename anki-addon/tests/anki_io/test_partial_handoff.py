"""A session finished early, handed off on a scratch collection (Phase 8): the
returned cards are never siblings, stay suspended, and the next selection
picks them. ``apply_handoff`` itself is covered by test_handoff.py."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import anki.collection  # noqa: F401  # must load before anki.cards
from anki.cards import Card, CardId
from anki.collection import Collection
from anki.consts import CARD_TYPE_NEW, QUEUE_TYPE_MANUALLY_BURIED, QUEUE_TYPE_SUSPENDED
from anki_fixtures import add_bqe_model, add_bqe_note, deck

from recalldrill import history_store, sessions
from recalldrill.anki_io.build import build_session
from recalldrill.anki_io.handoff import (
    TAG_DRILLED,
    HandoffSettings,
    apply_handoff,
    describe,
    handoff_line,
    plan_handoff,
    saved_returned,
)
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.revlog import waiting_for_anki
from recalldrill.anki_io.select import Scope, SelectOptions, options_to_json, select_cards
from recalldrill.controller import ControllerSettings
from recalldrill.engine.session import select_trial
from recalldrill.storage import Storage

WHEN = datetime(2026, 10, 8, 4, 0)
B = HandoffSettings(mode="B")
NOW = 1_790_000_000_000


def card(col: Collection, cid: int) -> Card:
    return col.get_card(CardId(cid))


def _drive(ctrl: sessions.DrillController, stop_at_batch_done: bool) -> None:
    for _ in range(2000):
        if ctrl.finished or (stop_at_batch_done and ctrl.state["phase"] == "batch-done"):
            return
        if ctrl.state["phase"] == "batch-done":
            ctrl.next_batch()
        elif ctrl.view().buttons.continue_:
            ctrl.continue_()
        else:
            trial = select_trial(ctrl.state)
            assert trial is not None
            ctrl.submit(trial["target"])
            if ctrl.processing:
                ctrl.dwell_elapsed()
    raise AssertionError("didn't stop")


def _cut_and_finished_session(col: Collection, st: Storage) -> tuple[int, Scope, dict[str, object]]:
    """Three suspended two-card notes, drilled one card per batch, stopped after the
    first batch, finished early with that one card, and its Final check answered."""
    add_bqe_model(col)
    did = deck(col, "Medical Terminology::3 - Skeletal System")
    for i in range(3):
        add_bqe_note(col, did, f"term{i}", f"meaning {i}")
    col.sched.suspend_cards(col.find_cards(f"did:{did}"))
    table = MappingTable(col)
    scope = Scope(deck_id=int(did))
    options = SelectOptions()
    res = build_session(col, select_cards(col, scope, options, table), None, table, {})
    assert len(res.sources) == 6
    key = sessions.deck_key(int(did))
    ctrl, _ = sessions.start_session(
        st,
        key=key,
        deck_items=res.deck_items,
        sources=res.sources,
        config={
            "encodeReps": 1,
            "chunkDifficulty": 100,
            "stemTolerance": True,
            "ladderMode": "cumulative",
            "strictPunctuation": False,
            "batchSize": 1,
        },
        scope=sessions.scope_json(deck_id=int(did)),
        select_options=options_to_json(options),
        deck_settings={},
        hints=False,
        settings=ControllerSettings(),
        now_ms=lambda: NOW,
    )
    ctrl.start()
    _drive(ctrl, stop_at_batch_done=True)
    assert ctrl.state["phase"] == "batch-done"
    ctrl.save_and_stop()
    saved = sessions.load(st, key)
    assert saved is not None
    cut = sessions.finish_early(saved, (), (), NOW)
    st.write_json(sessions.save_name(key), cut)
    ctrl2, _ = sessions.open_saved(st, key, cut, ControllerSettings(), lambda: NOW)
    ctrl2.start()
    _drive(ctrl2, stop_at_batch_done=False)
    assert ctrl2.finished == "complete"
    done = sessions.load(st, key)
    assert done is not None and sessions.save_status(done) == "handoff"
    return int(did), scope, done


def test_returned_cards_stay_suspended_and_are_picked_next(col: Collection, tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    did, scope, saved = _cut_and_finished_session(col, st)
    returned = set(saved_returned(saved))
    assert len(returned) == 5
    (kept,) = [s.cid for s in sessions.saved_sources(saved)]
    mate = next(c for c in col.card_ids_of_note(card(col, kept).nid) if c != kept)
    assert mate in returned  # the note is split by the cut
    before = {c: card(col, c) for c in returned}
    state = {c: (k.type, k.queue, k.flags, k.ivl) for c, k in before.items()}
    due_before = {c: k.due for c, k in before.items()}

    plan = plan_handoff(col, saved, B)
    assert plan.drilled_new == (kept,)
    assert plan.siblings == ()  # the returned note-mate isn't a sibling
    assert set(plan.returned) == returned
    assert not returned & set(plan.unsuspend + plan.bury + plan.front)

    # The same session uncut: the note-mate is handed off as a sibling, exactly as before.
    uncut = {**saved, "addon": {k: v for k, v in saved["addon"].items() if k != "cut"}}  # type: ignore[union-attr]
    plain = plan_handoff(col, uncut, B)
    assert plain.siblings == (mate,) and plain.returned == ()
    assert "went back to the pool" not in describe(plain, None, WHEN).plain()
    assert handoff_line(plain, None, NOW)["groups"]["returned"] == []

    apply_handoff(col, plan)
    kept_card = card(col, kept)
    assert kept_card.queue == QUEUE_TYPE_MANUALLY_BURIED and kept_card.type == CARD_TYPE_NEW
    assert TAG_DRILLED in col.get_note(kept_card.nid).tags
    for c, was in state.items():
        k = card(col, c)
        assert (k.type, k.queue, k.flags, k.ivl) == was
        assert k.queue == QUEUE_TYPE_SUSPENDED
    # Anki's reposition shifts the other new cards' positions to make room (it does so
    # for any new card); the returned cards keep their order, so they are picked in it.
    due_after = {c: card(col, c).due for c in returned}
    assert all(
        (due_before[a] < due_before[b]) == (due_after[a] < due_after[b])
        for a in returned
        for b in returned
    )

    line = handoff_line(plan, None, NOW)
    assert sorted(line["groups"]["returned"]) == sorted(returned)
    assert line["groups"]["drilled_new"] == [kept] and line["groups"]["siblings"] == []
    text = describe(plan, None, WHEN).plain()
    assert "5 cards from this session went back to the pool: not handed off" in text
    assert "still suspended." in text

    key = sessions.deck_key(did)
    sessions.complete_handoff(st, key, saved, line)
    options = SelectOptions(
        exclude_handed_off=waiting_for_anki(col, history_store.handed_off_at(st))
    )
    picked = [c.snap.cid for c in select_cards(col, scope, options, MappingTable(col)).picked]
    assert kept not in picked
    assert set(picked) == returned
    dues = [due_after[c] for c in picked]
    assert dues == sorted(dues)  # in the queue order they had
