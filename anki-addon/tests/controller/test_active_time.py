"""Active drill time (Phase 6): the gaps between actions, each capped, never
across Save and stop or a closed window; saved, resumed and written to history."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from controller_support import SHORT, START_MS, config, source

from recalldrill import history_store, sessions
from recalldrill.controller import ControllerSettings, DrillController
from recalldrill.engine.session import select_trial
from recalldrill.sessions import new_session_state, open_saved, scope_json, start_session
from recalldrill.storage import Storage

CAP = 120_000


class ManualClock:
    """Time moves only when the test says so."""

    def __init__(self) -> None:
        self.ms = START_MS

    def __call__(self) -> int:
        return self.ms

    def wait(self, seconds: float) -> None:
        self.ms += int(seconds * 1000)


def make(clock: ManualClock, **cfg: Any) -> DrillController:
    state = new_session_state(SHORT, config(**cfg), START_MS)
    return DrillController(
        state,
        [source(i) for i in range(len(SHORT))],
        ControllerSettings(idle_cap_ms=CAP),
        lambda saved: None,
        clock,
    )


def target(ctrl: DrillController) -> str:
    trial = select_trial(ctrl.state)
    assert trial is not None
    return trial["target"]


def current(ctrl: DrillController) -> int:
    trial = select_trial(ctrl.state)
    assert trial is not None
    return trial["itemId"]


def answer(ctrl: DrillController, typed: str | None = None) -> None:
    ctrl.submit(target(ctrl) if typed is None else typed)
    if ctrl.processing:
        ctrl.dwell_elapsed()


def test_gaps_between_actions_add_up_per_card() -> None:
    clock = ManualClock()
    ctrl = make(clock)
    ctrl.start()
    first = current(ctrl)
    clock.wait(5)
    answer(ctrl)  # 5 s on the first card
    second = current(ctrl)
    clock.wait(3)
    ctrl.reveal()  # 3 s on the second card
    clock.wait(2)
    answer(ctrl)  # 2 s more on it
    assert ctrl.active_ms == 10_000
    assert ctrl.active_ms_by_item == {first: 5000, second: 5000}


def test_no_clock_before_start() -> None:
    clock = ManualClock()
    ctrl = make(clock)
    clock.wait(30)
    answer(ctrl)  # the window wasn't up: nothing to measure from
    assert ctrl.active_ms == 0


def test_each_gap_is_capped() -> None:
    clock = ManualClock()
    ctrl = make(clock)
    ctrl.start()
    clock.wait(600)  # a ten-minute break
    answer(ctrl)
    assert ctrl.active_ms == CAP
    clock.wait(4)
    answer(ctrl)
    assert ctrl.active_ms == CAP + 4000


def test_rejected_actions_and_dwells_dont_count() -> None:
    clock = ManualClock()
    ctrl = make(clock)
    ctrl.start()
    clock.wait(2)
    ctrl.continue_()  # nothing to continue: no action
    assert ctrl.active_ms == 0
    clock.wait(3)
    answer(ctrl)
    assert ctrl.active_ms == 5000  # one gap since start, through the ignored press


def test_wrong_then_continue_and_override_count() -> None:
    clock = ManualClock()
    ctrl = make(clock)
    ctrl.start()
    card = current(ctrl)
    clock.wait(4)
    ctrl.submit("nope")  # wrong: waits for Continue or Count as correct
    clock.wait(6)
    ctrl.override()
    if ctrl.processing:
        ctrl.dwell_elapsed()
    assert ctrl.active_ms == 10_000 and ctrl.active_ms_by_item == {card: 10_000}


def test_next_batch_counts_for_the_session_only() -> None:
    clock = ManualClock()
    ctrl = make(clock, encodeReps=1, batchSize=1)
    ctrl.start()
    for _ in range(50):
        if ctrl.state["phase"] == "batch-done":
            break
        clock.wait(1)
        if ctrl.view().buttons.continue_:
            ctrl.continue_()
        else:
            answer(ctrl)
    assert ctrl.state["phase"] == "batch-done"
    before, per_card = ctrl.active_ms, ctrl.active_ms_by_item
    clock.wait(7)
    ctrl.next_batch()
    assert ctrl.active_ms == before + 7000 and ctrl.active_ms_by_item == per_card
    assert ctrl.view().mode == "trial"


def test_nothing_counts_across_save_and_stop_or_a_closed_window(tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    clock = ManualClock()
    ctrl, store = start_session(
        st,
        key=sessions.deck_key(42),
        deck_items=SHORT,
        sources=[source(i) for i in range(len(SHORT))],
        config=config(),
        scope=scope_json(deck_id=42),
        select_options={},
        deck_settings={},
        hints=False,
        settings=ControllerSettings(idle_cap_ms=CAP),
        now_ms=clock,
    )
    ctrl.start()
    card = current(ctrl)
    clock.wait(5)
    answer(ctrl)
    ctrl.save_and_stop()
    saved = sessions.load(st, store.meta.key)
    assert saved is not None
    assert saved["addon"]["activeMs"] == 5000
    assert saved["addon"]["activeMsByItem"] == {str(card): 5000}

    clock.wait(3600)  # an hour later, from the panel
    again, _ = open_saved(st, store.meta.key, saved, ControllerSettings(idle_cap_ms=CAP), clock)
    assert again.active_ms == 5000 and again.active_ms_by_item == {card: 5000}
    again.start()
    clock.wait(2)
    answer(again)
    assert again.active_ms == 7000


def test_completed_session_writes_active_time_to_history(tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    clock = ManualClock()
    ctrl, _store = start_session(
        st,
        key=sessions.deck_key(42),
        deck_items=SHORT,
        sources=[source(i) for i in range(len(SHORT))],
        config=config(encodeReps=1),
        scope=scope_json(deck_id=42),
        select_options={},
        deck_settings={},
        hints=False,
        settings=ControllerSettings(idle_cap_ms=CAP),
        now_ms=clock,
    )
    ctrl.start()
    for _ in range(200):
        if ctrl.finished:
            break
        clock.wait(2)
        if ctrl.view().buttons.continue_:
            ctrl.continue_()
        else:
            answer(ctrl)
    assert ctrl.finished == "complete"
    (line,) = history_store.read_all(st, "42")
    assert line["activeMs"] == ctrl.active_ms > 0
    shares = [a["activeMs"] for a in line["anki"]]
    assert all(s > 0 for s in shares) and sum(shares) == line["activeMs"]
