"""A stopped six-card session for the finish-early tests (Phase 8)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from controller_support import Clock, config, source

from recalldrill import sessions
from recalldrill.controller import ControllerSettings, DrillController
from recalldrill.engine.session import select_trial
from recalldrill.engine.types import DeckItem
from recalldrill.sessions import SessionStore, deck_key, scope_json, start_session
from recalldrill.storage import Storage

DECK: list[DeckItem] = [
    {"front": f"front{i}", "back": word}
    for i, word in enumerate(["cardi", "hepat", "nephr", "gastr", "pulmo", "derma"])
]
KEY = deck_key(42)
OPTIONS = {"enabled": ["new"], "card_ords": {}, "max_cards": None, "order": "priority_first"}


def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def start(
    st: Storage, deck: list[DeckItem] = DECK, **cfg: Any
) -> tuple[DrillController, SessionStore]:
    ctrl, store = start_session(
        st,
        key=KEY,
        deck_items=deck,
        sources=[source(i, nid=2000 + i // 2, ord=i % 2) for i in range(len(deck))],
        config=config(batchSize=2, **cfg),
        scope=scope_json(deck_id=42),
        select_options=OPTIONS,
        deck_settings={"strictPunctuation": False},
        hints=False,
        settings=ControllerSettings(deck_name="Med Term"),
        now_ms=Clock(),
        holdout=[{"cid": 9000, "nid": 9000, "ord": 0, "did": 1, "card_class": "new"}],
    )
    ctrl.start()
    return ctrl, store


def step(ctrl: DrillController) -> None:
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


def run_until(ctrl: DrillController, done: Any, limit: int = 2000) -> None:
    for _ in range(limit):
        if done(ctrl):
            return
        step(ctrl)
    raise AssertionError("limit reached")


def statuses(ctrl: DrillController) -> list[str]:
    return [i["status"] for i in ctrl.state["items"]]


def stopped_mid_batch(st: Storage) -> tuple[DrillController, SessionStore, dict[str, Any]]:
    """Batch 0 (cards 0, 1) done and card 2 mastered, 3 part-way, 4 and 5 untouched; stopped."""
    ctrl, store = start(st)
    run_until(
        ctrl,
        lambda c: (
            c.state["batchIndex"] == 1
            and c.state["phase"] == "cycle"
            and statuses(c)[2] == "mastered"
        ),
    )
    assert statuses(ctrl)[3] != "mastered"
    ctrl.save_and_stop()
    saved = sessions.load(st, KEY)
    assert saved is not None
    return ctrl, store, saved
