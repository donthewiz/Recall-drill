"""Builders and drivers for the controller tests."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from recalldrill.controller import (
    ControllerSettings,
    DrillController,
    Effect,
    StartDwell,
)
from recalldrill.engine.items import build_items
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    empty_stats,
    init_session,
    select_trial,
)
from recalldrill.engine.types import DeckItem, SessionPhase, SessionState
from recalldrill.sessions import NewSessionConfig, new_session_state
from recalldrill.sources import SourceRef

START_MS = 1_790_000_000_000

# Short answers: with chunkDifficulty 100 every card is drilled whole ('full').
SHORT: list[DeckItem] = [
    {"front": "heart", "back": "cardi"},
    {"front": "liver", "back": "hepat"},
    {"front": "kidney", "back": "nephr"},
]
# Long enough to chunk at chunkDifficulty 35.
LONG: list[DeckItem] = [
    {
        "front": "Hyperthyroidism",
        "back": "too much thyroid hormone speeds up the whole body metabolism a lot",
    },
]


def source(i: int, **changes: Any) -> SourceRef:
    base: dict[str, Any] = {
        "cid": 1000 + i,
        "nid": 2000 + i,
        "ord": 0,
        "did": 1,
        "ntid": 3,
        "card_class": "new",
        "flags": 0,
        "front_html": f"<b>front {i}</b>",
        "extra_html": "",
        "answer_hash": f"hash{i}",
        "has_audio": False,
        "answer_html": f"answer {i}",
        "css": ".card {}",
        "image_front": False,
    }
    base.update(changes)
    return SourceRef(**base)


def config(**changes: Any) -> NewSessionConfig:
    c: dict[str, Any] = {
        "encodeReps": 2,
        "chunkDifficulty": 100,
        "stemTolerance": True,
        "ladderMode": "cumulative",
        "strictPunctuation": False,
        "batchSize": 0,
        "cycleOrder": "inOrder",
    }
    c.update(changes)
    return cast(NewSessionConfig, c)


@dataclass
class Harness:
    ctrl: DrillController
    saves: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    finishes: list[bool] = field(default_factory=list[bool])
    effects: list[Effect] = field(default_factory=list[Effect])
    """Every effect returned so far, in order."""

    def do(self, effects: list[Effect]) -> list[Effect]:
        self.effects.extend(effects)
        return effects

    def target(self) -> str:
        trial = select_trial(self.ctrl.state)
        assert trial is not None, "no trial"
        return trial["target"]

    def submit(self, typed: str | None = None, *, dwell: bool = True) -> list[Effect]:
        out = self.do(self.ctrl.submit(self.target() if typed is None else typed))
        if dwell and any(isinstance(e, StartDwell) for e in out):
            out = out + self.do(self.ctrl.dwell_elapsed())
        return out

    def step(self) -> None:
        """One correct answer, then whatever the UI needs to reach the next trial."""
        if self.ctrl.state["phase"] == "batch-done":
            self.do(self.ctrl.next_batch())
            return
        if self.ctrl.view().buttons.continue_:
            self.do(self.ctrl.continue_())
            return
        self.submit()

    def run_until(self, done: Callable[[DrillController], bool], limit: int = 2000) -> None:
        for _ in range(limit):
            if done(self.ctrl):
                return
            self.step()
        raise AssertionError("limit reached")


class Clock:
    def __init__(self) -> None:
        self.ms = START_MS

    def __call__(self) -> int:
        self.ms += 1000
        return self.ms


def make(
    deck: Sequence[DeckItem] = SHORT,
    *,
    sources: Sequence[SourceRef] | None = None,
    settings: ControllerSettings | None = None,
    state: SessionState | None = None,
    persist: Callable[[dict[str, Any]], None] | None = None,
    **cfg: Any,
) -> Harness:
    clock = Clock()
    s = state if state is not None else new_session_state(deck, config(**cfg), START_MS)
    srcs = list(sources) if sources is not None else [source(i) for i in range(len(s["items"]))]
    h_saves: list[dict[str, Any]] = []
    finishes: list[bool] = []
    ctrl = DrillController(
        s,
        srcs,
        settings or ControllerSettings(deck_name="Test deck"),
        persist if persist is not None else h_saves.append,
        clock,
        on_finish=lambda c, complete: finishes.append(complete),
    )
    return Harness(ctrl, h_saves, finishes)


def phase_state(deck: Sequence[DeckItem], phase: SessionPhase, **cfg: Any) -> SessionState:
    """Every card 'ready', starting in ``phase`` ('cycle'), as the golden driver's allReady."""
    c = config(**cfg)
    items = [
        {**it, "status": "ready"}
        for it in build_items(deck, c["chunkDifficulty"], c["ladderMode"], c["batchSize"], 8, False)
    ]
    return init_session(
        cast(
            SessionState,
            {
                "items": items,
                "phase": phase,
                "queue": [],
                "stats": empty_stats(),
                "currentId": SESSION_COMPLETE_ID,
                "batchIndex": 0,
                "batchStartStats": empty_stats(),
                "config": dict(c),
            },
        )
    )
