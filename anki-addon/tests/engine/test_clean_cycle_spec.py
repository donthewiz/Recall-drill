"""Port of src/test/cleanCycle.spec.ts (2026-10-12): a clean card masters the cycle
with one correct answer. Plus the add-on's encodeRepsOverride."""

from __future__ import annotations

from typing import Any, cast

import pytest

from recalldrill.engine.items import build_items, cycle_reps_to_master
from recalldrill.engine.progress import compute_item_progress
from recalldrill.engine.session import (
    apply_answer,
    apply_next,
    edit_current_item,
    init_session,
    select_trial,
)
from recalldrill.engine.types import DrillItem, SessionState


def _cycle(encode_reps: int = 1, **patch: Any) -> SessionState:
    items = build_items(
        [{"front": "heart", "back": "cardi"}, {"front": "liver", "back": "hepat"}],
        35,
        "cumulative",
        None,
        8,
        False,
    )
    ready = [
        cast(DrillItem, {**i, "status": "ready", **(patch if i["id"] == 0 else {})})
        for i in items
    ]
    zero = {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0}
    return init_session(
        cast(
            SessionState,
            {
                "items": ready,
                "phase": "cycle",
                "queue": [],
                "stats": dict(zero),
                "currentId": -1,
                "batchIndex": 0,
                "batchStartStats": dict(zero),
                "config": {
                    "encodeReps": encode_reps,
                    "chunkDifficulty": 35,
                    "stemTolerance": True,
                    "ladderMode": "cumulative",
                    "cycleOrder": "inOrder",
                },
            },
        )
    )


def _card0(s: SessionState) -> DrillItem:
    return next(i for i in s["items"] if i["id"] == 0)


def test_cycle_reps_to_master() -> None:
    """TS: is 1 with no miss and no reveal, else 2; near misses do not count"""
    assert cycle_reps_to_master({}) == 1
    assert cycle_reps_to_master({"misses": 0, "reveals": 0, "nearMisses": 3}) == 1
    assert cycle_reps_to_master({"misses": 1}) == 2
    assert cycle_reps_to_master({"reveals": 1}) == 2


@pytest.mark.parametrize("encode_reps", [1, 3])
def test_clean_card_masters_with_one(encode_reps: int) -> None:
    """TS: a clean card is mastered by one correct answer (encodeReps 1 and 3)"""
    r = apply_answer(_cycle(encode_reps), "cardi", revealed=False)
    assert _card0(r["state"])["status"] == "mastered"
    assert r["feedback"]["text"] == "Mastered! Item retired."


@pytest.mark.parametrize("override", [1, 2, 5])
def test_clean_card_masters_with_one_whatever_its_reps_override(override: int) -> None:
    """Add-on: the rule holds with any encodeRepsOverride."""
    r = apply_answer(_cycle(3, encodeRepsOverride=override), "cardi", revealed=False)
    assert _card0(r["state"])["status"] == "mastered"


@pytest.mark.parametrize("patch", [{"misses": 1}, {"reveals": 1}])
def test_unclean_card_needs_two(patch: dict[str, int]) -> None:
    """TS: a card with a miss or a reveal needs 2 in a row, as before"""
    r = apply_answer(_cycle(1, **patch), "cardi", revealed=False)
    assert _card0(r["state"])["status"] == "ready"
    assert _card0(r["state"])["cycleStreak"] == 1


def test_override_keeps_the_card_clean() -> None:
    """TS: "Count as correct" keeps the card clean (its miss is never recorded)"""
    pre = _cycle()
    assert _card0(apply_answer(pre, "zzz", revealed=False)["state"]).get("misses") == 1
    override = apply_answer(pre, "cardi", revealed=False, override=True)
    assert _card0(override["state"]).get("misses") == 0
    assert _card0(override["state"])["status"] == "mastered"


def test_restart_makes_the_card_clean() -> None:
    """TS: an edit that restarts a card resets its counters, so it is clean again"""
    s = _cycle(1, misses=2, reveals=1)
    result = edit_current_item(s, {"front": "heart", "back": "cardio"})
    assert result["restarted"]
    assert cycle_reps_to_master(_card0(result["state"])) == 1


def test_final_check_unchanged() -> None:
    """TS: the Final check is unchanged: one correct answer each"""
    s = _cycle()
    for _ in range(2):
        trial = select_trial(s)
        assert trial is not None
        s = apply_next(apply_answer(s, trial["target"], revealed=False)["state"])
    assert s["phase"] == "final"
    trial = select_trial(s)
    assert trial is not None
    r = apply_answer(s, trial["target"], revealed=False)
    assert r["advance"] == "manual"


def test_progress_counts_the_cycle() -> None:
    """TS: counts a ready card's cycle: 1 needed when clean, 2 otherwise"""
    base = _card0(_cycle())
    assert compute_item_progress({**base, "cycleStreak": 0}, 1) == pytest.approx(0.7)
    unclean: DrillItem = {**base, "cycleStreak": 1, "misses": 1}
    assert compute_item_progress(unclean, 1) == pytest.approx(0.85)
