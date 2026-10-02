"""Handed-off cards wait for Anki (config ``exclude_handed_off_new``): after a
handoff B, the drilled cards and their siblings stay new at the front of the new
queue, and the next selection leaves them out until Anki has rated them. Per
card: a note's other cards that were never handed off stay selectable."""

from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Any

from anki.collection import Collection
from anki_fixtures import AMC, add_amc_models, add_bqe_model, add_bqe_note, add_note, deck

from recalldrill import history_store, sessions
from recalldrill.addon_config import DEFAULT_CONFIG, AddonConfig
from recalldrill.anki_io.build import build_session
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.handoff import (
    HARD_SEARCH,
    HandoffSettings,
    apply_handoff,
    handoff_line,
    plan_handoff,
)
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.panel import PanelData, handed_off_exclusions, options_for, read_panel
from recalldrill.anki_io.select import (
    Scope,
    SelectOptions,
    options_from_json,
    options_to_json,
    select_cards,
)
from recalldrill.controller import ControllerSettings, DrillController
from recalldrill.engine.session import select_trial
from recalldrill.storage import Storage

B = HandoffSettings(mode="B")
NOW = 1_790_000_000_000


def _drill(
    col: Collection, st: Storage, scope: Scope, options: SelectOptions, miss_one: bool = False
) -> tuple[DrillController, Any, list[int]]:
    """A session over ``select_cards(scope, options)``, answered to the end."""
    table = MappingTable(col)
    sel = select_cards(col, scope, options, table)
    res = build_session(col, sel, None, table, {})
    key = sessions.scope_key(sessions.scope_json(deck_id=scope.deck_id, search=scope.search))
    ctrl, store = sessions.start_session(
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
            "batchSize": 0,
        },
        scope=sessions.scope_json(deck_id=scope.deck_id, search=scope.search),
        select_options=options_to_json(options),
        deck_settings={},
        hints=False,
        settings=ControllerSettings(),
        now_ms=lambda: NOW,
    )
    ctrl.start()
    missed = not miss_one
    for _ in range(500):
        if ctrl.finished:
            break
        if ctrl.view().buttons.continue_:
            ctrl.continue_()
            continue
        trial = select_trial(ctrl.state)
        assert trial is not None
        typed = trial["target"]
        if ctrl.view().label == "Final check" and not missed:
            typed, missed = "nope", True
        ctrl.submit(typed)
        if ctrl.processing:
            ctrl.dwell_elapsed()
    assert ctrl.finished == "complete"
    return ctrl, store, [s.cid for s in res.sources]


def _hand_off(col: Collection, st: Storage, store: Any) -> Any:
    saved = sessions.load(st, store.meta.key)
    assert saved is not None
    plan = plan_handoff(col, saved, B)
    apply_handoff(col, plan)
    sessions.complete_handoff(st, store.meta.key, saved, handoff_line(plan, None, NOW + 1))
    # The next day: the handoff's burial is over.
    col.sched.unbury_cards(col.find_cards("is:buried"))
    return plan


def _panel(
    col: Collection, st: Storage, scope: Scope, cfg: AddonConfig = DEFAULT_CONFIG
) -> PanelData:
    options = options_for(
        {}, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )
    return read_panel(col, st, scope, options, {}, scope.deck_id, cfg)


def _picked(p: PanelData) -> set[int]:
    return {c.snap.cid for c in p.selection.picked}


def _bqe(col: Collection, tmp_path: Path) -> tuple[Storage, int, int, list[int]]:
    add_bqe_model(col)
    did = int(deck(col, "Med Term::Ch 3"))
    notes = [add_bqe_note(col, did, f"term{i}", f"meaning {i}") for i in range(4)]  # type: ignore[arg-type]
    col.sched.suspend_cards(col.find_cards('deck:"Med Term"'))
    st = Storage(tmp_path / "user_files", "User 1")
    return st, did, notes[0].mid, [n.id for n in notes]


def test_b_handoff_cards_and_siblings_wait_for_anki(col: Collection, tmp_path: Path) -> None:
    st, did, ntid, _ = _bqe(col, tmp_path)
    scope = Scope(deck_id=did)
    # Reverse cards of the first 3 notes (deck order), as the panel would pick them.
    reverse = SelectOptions(card_ords={ntid: frozenset({1})}, max_cards=3, order="deck_order")
    _, store, drilled = _drill(col, st, scope, reverse)
    plan = _hand_off(col, st, store)
    assert plan.drilled_new == tuple(drilled) and len(plan.siblings) == 3
    handed = set(plan.drilled_new + plan.siblings)
    assert all(col.get_card(c).type == 0 and col.get_card(c).queue == 0 for c in handed)  # type: ignore[arg-type]
    assert history_store.handed_off_cids(st) == frozenset(handed)

    p = _panel(col, st, scope)
    assert _picked(p).isdisjoint(handed)
    assert len(p.selection.picked) == 2  # the 4th note's two cards
    assert p.selection.handed_off == 6
    # Pacing counts what selection counts.
    sel = p.selection
    assert sel.pace_remaining == sel.eligible_counts["new"] + sel.eligible_counts["suspended_new"]
    assert sel.pace_remaining == 2

    # The setting off: they're back (and pacing counts them too).
    off = _panel(col, st, scope, replace(DEFAULT_CONFIG, exclude_handed_off_new=False))
    assert handed <= _picked(off) and off.selection.handed_off == 0
    assert off.selection.pace_remaining == 8

    # Once Anki has rated a card it's an ordinary review card again: selectable.
    reviewed = plan.drilled_new[0]
    col.sched.set_due_date([reviewed], "0")  # type: ignore[list-item]
    p = _panel(col, st, scope)
    assert reviewed in _picked(p) and p.selection.handed_off == 5
    assert next(c for c in p.selection.picked if c.snap.cid == reviewed).card_class == "young"


def test_a_cloze_sibling_never_handed_off_stays(col: Collection, tmp_path: Path) -> None:
    add_amc_models(col)
    psych = deck(col, "Psych")
    did = int(psych)
    note = add_note(col, AMC, psych, {"Text": "{{c1::Freud}} founded {{c2::psychoanalysis}}."})
    c1, c2 = sorted(note.cards(), key=lambda c: c.ord)
    st = Storage(tmp_path / "user_files", "User 1")
    # Drill c1 only; c2 is new and not suspended, so the handoff leaves it alone.
    _, store, drilled = _drill(col, st, Scope(search='deck:"Psych" card:1'), SelectOptions())
    assert drilled == [c1.id]
    plan = _hand_off(col, st, store)
    assert plan.drilled_new == (c1.id,) and plan.siblings == ()
    assert col.find_notes("tag:rd::drilled") == [note.id]  # the note carries the tag

    p = _panel(col, st, Scope(deck_id=did))
    assert _picked(p) == {c2.id}  # per card, not per note
    assert p.selection.handed_off == 1
    assert p.selection.pace_remaining == 1


def test_rd_hard_scope_and_searches(col: Collection, tmp_path: Path) -> None:
    st, did, ntid, _ = _bqe(col, tmp_path)
    reverse = SelectOptions(card_ords={ntid: frozenset({1})}, max_cards=3, order="deck_order")
    _, store, _ = _drill(col, st, Scope(deck_id=did), reverse)
    plan = _hand_off(col, st, store)
    handed = frozenset(plan.drilled_new + plan.siblings)
    assert handed_off_exclusions(st, Scope(search=HARD_SEARCH), DEFAULT_CONFIG) == frozenset()
    assert (
        handed_off_exclusions(st, Scope(search=f" {HARD_SEARCH} "), DEFAULT_CONFIG) == frozenset()
    )
    assert handed_off_exclusions(st, Scope(search='deck:"Med Term"'), DEFAULT_CONFIG) == handed
    off = replace(DEFAULT_CONFIG, exclude_handed_off_new=False)
    assert handed_off_exclusions(st, Scope(deck_id=did), off) == frozenset()
    # A search scope leaves them out too.
    p = _panel(col, st, Scope(search='deck:"Med Term"'))
    assert _picked(p).isdisjoint(handed) and p.selection.handed_off == 6


def test_drill_again_is_unaffected(col: Collection, tmp_path: Path) -> None:
    """Drill-again never selects: it drills the parent's Final-check misses, even
    once they're handed off."""
    st, did, ntid, _ = _bqe(col, tmp_path)
    reverse = SelectOptions(card_ords={ntid: frozenset({1})}, max_cards=3, order="deck_order")
    ctrl, store, _ = _drill(col, st, Scope(deck_id=did), reverse, miss_one=True)
    plan = _hand_off(col, st, store)
    again, _ = sessions.start_drill_again(st, ctrl, store, ctrl.settings, lambda: NOW)
    (src,) = again.sources
    assert src.cid in plan.drilled_new and src.cid in history_store.handed_off_cids(st)


def test_options_round_trip_the_exclusion() -> None:
    o = SelectOptions(exclude_handed_off=frozenset({5, 3}))
    assert options_to_json(o)["exclude_handed_off"] == [3, 5]
    assert options_from_json(options_to_json(o)) == o
    assert options_from_json({}).exclude_handed_off == frozenset()
