"""Fewer clicks per trial (2026-10-12): correct cycle and Final-check answers move
on by themselves; the Extra shows the first time and after misses."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from controller_support import Clock, config, make, phase_state, source

from recalldrill import sessions
from recalldrill.controller import (
    CORRECT_DWELL_MS,
    ControllerSettings,
    Persisted,
    SessionComplete,
    StartDwell,
)
from recalldrill.engine.session import select_trial
from recalldrill.engine.types import DeckItem
from recalldrill.sessions import deck_key, open_saved, scope_json, start_drill_again
from recalldrill.storage import Storage

PLAIN: list[DeckItem] = [
    {"front": "heart", "back": "cardi"},
    {"front": "liver", "back": "hepat"},
    {"front": "kidney", "back": "nephr"},
]
EXTRA: list[DeckItem] = [
    {"front": "heart", "back": "cardi", "extra": "as in cardiology"},
    {"front": "liver", "back": "hepat", "extra": "as in hepatitis"},
]


def settings(**changes: Any) -> ControllerSettings:
    return ControllerSettings(deck_name="Test deck", play_audio_on_feedback=False, **changes)


def dwells(effects: list[Any]) -> list[int]:
    return [e.ms for e in effects if isinstance(e, StartDwell)]


def current(h: Any) -> int:
    trial = select_trial(h.ctrl.state)
    assert trial is not None
    return trial["itemId"]


# ---------------------------------------------------------------------------
# Auto-advance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(("typed", "verdict"), [("cardi", "exact"), ("the cardi", "near")])
def test_a_correct_cycle_answer_moves_on_by_itself(typed: str, verdict: str) -> None:
    h = make(state=phase_state(PLAIN, "cycle", cycleOrder="inOrder"), settings=settings())
    h.ctrl.start()
    assert current(h) == 0
    out = h.ctrl.submit(typed)
    assert dwells(out) == [CORRECT_DWELL_MS[verdict]]
    v = h.ctrl.view()
    assert v.processing and not v.buttons.continue_
    assert v.feedback is not None and v.feedback.verdict == verdict
    assert Persisted() in out  # the answer is saved before the dwell
    h.ctrl.dwell_elapsed()
    assert current(h) == 1 and h.ctrl.view().feedback is None
    assert CORRECT_DWELL_MS == {"exact": 600, "near": 1200}


def test_with_auto_advance_off_it_waits_for_enter() -> None:
    h = make(
        state=phase_state(PLAIN, "cycle", cycleOrder="inOrder"),
        settings=settings(auto_advance_correct=False),
    )
    h.ctrl.start()
    assert dwells(h.ctrl.submit("cardi")) == []
    assert h.ctrl.view().buttons.continue_
    h.ctrl.continue_()
    assert current(h) == 1


@pytest.mark.parametrize("action", ["wrong", "reveal"])
def test_wrong_answers_and_reveals_still_wait(action: str) -> None:
    h = make(state=phase_state(PLAIN, "cycle", cycleOrder="inOrder"), settings=settings())
    h.ctrl.start()
    if action == "reveal":
        h.ctrl.reveal()
        out = h.ctrl.submit("cardi")
    else:
        out = h.ctrl.submit("nope")
    assert dwells(out) == [] and h.ctrl.view().buttons.continue_


def test_the_final_check_moves_on_and_completes_by_itself() -> None:
    h = make(state=phase_state(PLAIN[:2], "cycle"), settings=settings())
    h.ctrl.start()
    h.run_until(lambda c: c.state["phase"] == "final")
    assert not h.ctrl.view().buttons.continue_
    first = h.ctrl.submit(h.target())
    assert dwells(first) == [600]
    h.ctrl.dwell_elapsed()
    out = h.ctrl.submit(h.target())
    assert dwells(out) == [600] and SessionComplete() not in out
    done = h.ctrl.dwell_elapsed()
    assert SessionComplete() in done and h.ctrl.finished == "complete"


def test_answer_audio_waits_for_enter() -> None:
    srcs = [source(i, has_audio=True) for i in range(3)]
    h = make(
        state=phase_state(PLAIN, "cycle"),
        sources=srcs,
        settings=ControllerSettings(play_audio_on_feedback=True),
    )
    h.ctrl.start()
    out = h.ctrl.submit(h.target())
    assert dwells(out) == [] and h.ctrl.view().buttons.continue_
    # With feedback audio off, the same card moves on.
    h2 = make(state=phase_state(PLAIN, "cycle"), sources=srcs, settings=settings())
    h2.ctrl.start()
    assert dwells(h2.ctrl.submit(h2.target())) == [600]


def test_count_as_correct_moves_on_by_itself() -> None:
    h = make(state=phase_state(PLAIN, "cycle", cycleOrder="inOrder"), settings=settings())
    h.ctrl.start()
    h.ctrl.submit("nope")
    out = h.ctrl.override()
    assert dwells(out) == [600]
    h.ctrl.dwell_elapsed()
    assert current(h) == 1


def test_a_self_advance_is_not_an_action_for_active_time() -> None:
    clock = Clock()
    h = make(state=phase_state(PLAIN, "cycle"), settings=settings())
    h.ctrl._now_ms = clock  # pyright: ignore[reportPrivateUsage]
    h.ctrl.start()
    h.ctrl.submit(h.target())
    before = h.ctrl.active_ms
    h.ctrl.dwell_elapsed()
    assert h.ctrl.active_ms == before  # the dwell added nothing
    h.ctrl.submit(h.target())
    assert h.ctrl.active_ms > before  # the next answer adds the gap since the last one


# ---------------------------------------------------------------------------
# Extra display
# ---------------------------------------------------------------------------


def _encode_extra(**s: Any) -> Any:
    # encodeReps 2: two full-stage reps per card, so a card's full answer is
    # on screen twice before the cycle.
    h = make(EXTRA, encodeReps=2, settings=settings(**s))
    h.ctrl.start()
    return h


def test_first_and_misses_shows_and_holds_the_first_time_only() -> None:
    h = _encode_extra()
    first = h.ctrl.submit("cardi")
    assert dwells(first) == []  # held by the Extra
    v = h.ctrl.view()
    assert v.extra == "as in cardiology" and v.buttons.continue_
    h.ctrl.continue_()
    assert h.ctrl.extra_seen == frozenset({0})
    # Card 1's first time, then card 0 again: no Extra, no hold.
    h.ctrl.submit("hepat")
    h.ctrl.continue_()
    out = h.ctrl.submit("cardi")
    v = h.ctrl.view()
    assert dwells(out) and v.extra is None and v.extra_html is None
    assert v.buttons.show_extra


@pytest.mark.parametrize("action", ["wrong", "reveal"])
def test_first_and_misses_shows_after_a_miss_or_reveal(action: str) -> None:
    h = _encode_extra()
    h.ctrl.submit("cardi")
    h.ctrl.continue_()
    h.ctrl.submit("hepat")
    h.ctrl.continue_()
    assert current(h) == 0
    if action == "reveal":
        h.ctrl.reveal()
        h.ctrl.submit("cardi")
    else:
        h.ctrl.submit("nope")
    v = h.ctrl.view()
    assert v.extra == "as in cardiology" and v.buttons.continue_


def test_always_shows_and_holds_every_time() -> None:
    h = _encode_extra(extra_display="always")
    for back in ("cardi", "hepat", "cardi"):
        out = h.ctrl.submit(back)
        assert dwells(out) == [] and h.ctrl.view().extra is not None
        h.ctrl.continue_()


def test_an_extra_hold_beats_auto_advance_in_the_cycle() -> None:
    h = make(state=phase_state(EXTRA, "cycle", cycleOrder="inOrder"), settings=settings())
    h.ctrl.start()
    out = h.ctrl.submit("cardi")  # first time on screen: shown and held
    assert dwells(out) == [] and h.ctrl.view().buttons.continue_
    h.ctrl.continue_()
    assert current(h) == 1


def test_show_extra_shows_it_and_turns_a_dwell_into_a_hold() -> None:
    h = _encode_extra()
    h.ctrl.submit("cardi")
    h.ctrl.continue_()
    h.ctrl.submit("hepat")
    h.ctrl.continue_()
    out = h.ctrl.submit("cardi")  # seen: dwelling, Extra hidden
    assert dwells(out) and h.ctrl.view().processing
    assert h.ctrl.show_extra() == []
    v = h.ctrl.view()
    assert v.extra == "as in cardiology" and v.buttons.continue_ and not v.processing
    assert not v.buttons.show_extra
    assert h.ctrl.dwell_elapsed() == []  # the timer firing late changes nothing
    h.ctrl.continue_()
    assert h.ctrl.view().feedback is None


def test_show_extra_is_offered_only_when_there_is_one_to_show() -> None:
    h = make(PLAIN, encodeReps=2, settings=settings())
    h.ctrl.start()
    h.ctrl.submit("cardi")
    assert not h.ctrl.view().buttons.show_extra and h.ctrl.show_extra() == []
    h2 = _encode_extra()
    assert not h2.ctrl.view().buttons.show_extra  # no feedback yet


def test_an_edit_that_changes_the_extra_clears_its_flag() -> None:
    h = _encode_extra()
    h.ctrl.submit("cardi")
    h.ctrl.continue_()
    h.ctrl.submit("hepat")
    h.ctrl.continue_()
    assert h.ctrl.extra_seen == frozenset({0, 1})
    assert h.ctrl.begin_edit() is not None
    h.ctrl.apply_card_edit("heart", "cardi", "as in cardiology")  # unchanged
    assert h.ctrl.extra_seen == frozenset({0, 1})
    assert h.ctrl.begin_edit() is not None
    h.ctrl.apply_card_edit("heart", "cardi", "as in cardiomegaly")
    assert h.ctrl.extra_seen == frozenset({1})
    out = h.ctrl.submit("cardi")
    assert dwells(out) == [] and h.ctrl.view().extra == "as in cardiomegaly"


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _start(st: Storage) -> Any:
    ctrl, store = sessions.start_session(
        st,
        key=deck_key(42),
        deck_items=EXTRA + [{"front": "kidney", "back": "nephr", "extra": "renal"}],
        sources=[source(i) for i in range(3)],
        config=config(encodeReps=1, batchSize=2),
        scope=scope_json(deck_id=42),
        select_options={"enabled": ["new"], "card_ords": {}, "max_cards": None},
        deck_settings={},
        hints=False,
        settings=settings(),
        now_ms=Clock(),
    )
    ctrl.start()
    return ctrl, store


def test_extra_seen_is_saved_resumed_and_cut(tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    ctrl, _ = _start(st)
    ctrl.submit("cardi")
    ctrl.continue_()
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["addon"]["extraSeen"] == [0]
    resumed, _ = open_saved(st, "deck-42", saved, settings(), Clock())
    assert resumed.extra_seen == frozenset({0})
    # The finish-early cut remaps the ids of the kept cards.
    for _ in range(100):
        if ctrl.state["phase"] == "batch-done":
            break
        _step(ctrl)
    ctrl.save_and_stop()
    stopped = sessions.load(st, "deck-42")
    assert stopped is not None and sorted(stopped["addon"]["extraSeen"]) == [0, 1]
    stopped["addon"]["extraSeen"] = [1, 2]
    cut = sessions.finish_early(stopped, missing=(), changed=(), now_ms=0)
    # Cards 0 and 1 are kept (ids 0, 1); card 2 went back to the pool.
    assert cut["addon"]["extraSeen"] == [1]


def current_id(ctrl: Any) -> int:
    trial = select_trial(ctrl.state)
    assert trial is not None
    return trial["itemId"]


def _step(ctrl: Any) -> None:
    if ctrl.state["phase"] == "batch-done":
        ctrl.next_batch()
        return
    if ctrl.view().buttons.continue_:
        ctrl.continue_()
        return
    trial = select_trial(ctrl.state)
    assert trial is not None
    ctrl.submit(trial["target"])
    if ctrl.processing:
        ctrl.dwell_elapsed()


def test_a_new_session_starts_with_nothing_seen(tmp_path: Path) -> None:
    st = Storage(tmp_path / "user_files", "User 1")
    ctrl, store = _start(st)
    for _ in range(300):
        if ctrl.finished:
            break
        if ctrl.state["phase"] == "final" and not ctrl.view().buttons.continue_:
            if current_id(ctrl) == 0 and not ctrl.state["items"][0].get("finalMisses"):
                ctrl.submit("nope")
                continue
        _step(ctrl)
    assert ctrl.finished == "complete" and ctrl.extra_seen
    again, _ = start_drill_again(st, ctrl, store, ctrl.settings, Clock())
    assert again.extra_seen == frozenset()
