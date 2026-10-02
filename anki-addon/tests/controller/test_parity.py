"""The controller adds nothing beyond SessionView: golden-trace parity.

Every scripted scenario in ``tests/golden/session_scenarios.json`` (the Phase 1b
traces, recorded from the TS engine by a driver that mirrors SessionView) is
replayed through :class:`DrillController`'s actions instead of raw engine
calls, and the engine state after every step must equal the recorded one.

Action -> controller:

- ``correct`` / ``wrong:x`` / ``near:x`` / ``type:x``: ``submit``;
- ``reveal[:x]``: ``reveal`` then ``submit``;
- ``override``: ``override``;
- ``edit:{...}``: ``begin_edit`` then ``apply_card_edit``;
- ``next``: ``continue_``, or ``next_batch`` on the interstitial;
- ``save-resume[:edits]``: ``saved_dict`` (with the scenario's edits, which fake
  an older app's save) -> ``sessions.resume`` -> a new controller;
- ``probe``: nothing (it changes no state).

A ``StartDwell`` is run out at once (``dwell_elapsed``), and an Extra pause is
released (``continue_``) before the next answer, as the learner would. The state
compared is the one the controller has committed or holds for Continue.

One SessionView behavior the golden driver doesn't model: opening the card
editor on an attempt still pending shows the learner the full answer, so on
close (without a restart) the attempt counts as revealed (``editRevealsOnClose``).
From such an edit on, the scenario's next answer grades differently on purpose;
it is compared up to and including the edit, and
``test_controller.py::test_edit_on_a_pending_attempt_reveals_it`` pins the rest.
"""

from __future__ import annotations

import json
from collections import defaultdict
from typing import Any, cast

import pytest
from engine_test_support import fail_on_difference, load_golden
from session_runner import Runner, apply_save_edits

from recalldrill.controller import ControllerSettings, DrillController, StartDwell
from recalldrill.engine import rand
from recalldrill.engine.session import select_trial
from recalldrill.engine.types import SessionState
from recalldrill.sessions import resume
from recalldrill.sources import SourceRef

SCENARIOS = load_golden("session_scenarios.json")
STEPS: dict[str, list[dict[str, Any]]] = defaultdict(list)
for _step in SCENARIOS["steps"]:
    STEPS[_step["scenario"]].append(_step)

# Scenarios with a step SessionView offers no control for. They are compared up
# to that step, which must be the one named here.
CUT_SHORT = {
    "resume-mid-cycle": 14,  # answers again while Continue is showing (no 'next')
}


class Unreachable(Exception):
    """The script takes an action the UI doesn't offer at this point."""


# Scripted actions SessionView has no control for, so the controller can't take.
UNREACHABLE = {
    # Overrides with no wrong verdict showing (an engine-level probe of the
    # override flag on a post-miss state).
    "override-now",
}


def _source(i: int) -> SourceRef:
    return SourceRef(
        cid=1000 + i,
        nid=2000 + i,
        ord=0,
        did=1,
        ntid=3,
        card_class="new",
        flags=0,
        front_html=f"front {i}",
        extra_html="",
        answer_hash="",
        has_audio=False,
        answer_html="",
        css="",
        image_front=False,
    )


def _replayable(name: str) -> bool:
    return all(s["action"].split(":")[0] not in UNREACHABLE for s in STEPS[name])


def _controller(state: SessionState, collisions: int = 0) -> DrillController:
    return DrillController(
        state,
        [_source(i) for i in range(len(state["items"]))],
        ControllerSettings(deck_name="golden", play_audio_on_feedback=False),
        lambda saved: None,
        lambda: 0,
        collisions=collisions,
    )


class ControllerDriver:
    def __init__(self, header: dict[str, Any]) -> None:
        # The Runner builds the scenario's initial state exactly as the TS driver.
        self.ctrl = _controller(Runner(header, SCENARIOS["fixed"]).state)
        self.revealed_by_edit = False

    def state(self) -> SessionState:
        return self.ctrl.pending_advance_state or self.ctrl.state

    def _run(self, effects: list[Any]) -> None:
        if any(isinstance(e, StartDwell) for e in effects):
            assert self.ctrl.processing
            self.ctrl.dwell_elapsed()

    def _release_pause(self) -> None:
        if self.ctrl.pending_advance_state is not None:
            self.ctrl.continue_()

    def _target(self) -> str:
        trial = select_trial(self.ctrl.state)
        assert trial is not None, "no trial to answer"
        return trial["target"]

    def _submit(self, typed: str | None) -> None:
        self._release_pause()
        if not self.ctrl.view().buttons.check:
            raise Unreachable("submit with no Check button")
        before = self.ctrl.state
        effects = self.ctrl.submit(self._target() if typed is None else typed)
        assert effects, "submit was ignored"
        assert self.ctrl.state is before or not self.ctrl.processing
        self._run(effects)

    def execute(self, action: str) -> None:
        verb, sep, arg = action.partition(":")
        if not sep:
            arg = None
        if verb == "correct":
            self._submit(None)
        elif verb in ("wrong", "near", "type"):
            self._submit(arg or "")
        elif verb == "reveal":
            self._release_pause()
            # Esc does nothing on a presentation beat; the engine grades it
            # 'presented' either way.
            presentation = self.ctrl.view().input_read_only
            self.ctrl.reveal()
            assert self.ctrl.view().revealed != presentation
            self._submit(arg)
        elif verb == "override":
            assert self.ctrl.view().buttons.override
            self._run(self.ctrl.override())
        elif verb == "edit":
            assert arg is not None
            edit = json.loads(arg)
            if self.ctrl.begin_edit() is not None:
                self._run(
                    self.ctrl.apply_card_edit(edit["front"], edit["back"], edit.get("extra", ""))
                )
                self.revealed_by_edit = self.ctrl.view().revealed
        elif verb == "next":
            if self.ctrl.state["phase"] == "batch-done":
                self.ctrl.next_batch()
            else:
                self.ctrl.continue_()
        elif verb == "save-resume":
            self._release_pause()
            saved = self.ctrl.saved_dict()
            apply_save_edits(saved, json.loads(arg) if arg else {})
            self.ctrl = _controller(resume(saved), self.ctrl.collisions)
        elif verb == "probe":
            pass
        else:  # pragma: no cover - a new golden action needs a mapping here
            raise AssertionError(f"unknown action {action!r}")


PARITY = [h for h in SCENARIOS["scenarios"] if _replayable(h["name"])]


def test_only_unreachable_scenarios_are_left_out() -> None:
    left_out = sorted(h["name"] for h in SCENARIOS["scenarios"] if h not in PARITY)
    assert left_out == ["c2-override-final-rep", "override-now-post-miss-chunk"]


@pytest.mark.parametrize("header", PARITY, ids=[h["name"] for h in PARITY])
def test_controller_replays_golden_scenario(header: dict[str, Any]) -> None:
    name = header["name"]
    with rand.seeded(header["seed"]):
        if not header["deck"]:
            # The engine's empty-deck path never completes; the controller refuses it.
            with pytest.raises(ValueError, match="at least one card"):
                ControllerDriver(header)
            return
        driver = ControllerDriver(header)
        for expected in STEPS[name]:
            action = expected["action"]
            where = f"{name} step {expected['step']} ({action!r})"
            if action != "init":
                try:
                    driver.execute(action)
                except Unreachable:
                    assert CUT_SHORT.get(name) == expected["step"], where
                    return
            fail_on_difference(expected["state"], cast(Any, driver.state()), where)
            if driver.revealed_by_edit:
                break  # editRevealsOnClose: see the module docstring
        assert name not in CUT_SHORT, f"{name} replayed in full: drop it from CUT_SHORT"
