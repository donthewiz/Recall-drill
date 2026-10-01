"""Replays a scripted scenario from ``tests/golden/session_scenarios.json``.

The Python twin of ``Driver`` in ``tools/export_golden.ts``: the same actions,
mirroring SessionView and App.tsx (see the action list there). Every engine call
goes through :meth:`Runner.call`, which deep-copies the input states first and
fails if the call changed any of them (the engine must never mutate its input).
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from typing import Any, cast

from engine_test_support import first_difference

from recalldrill.engine import rand
from recalldrill.engine.estimate import (
    compute_cold_start_estimate,
    compute_cumulative_cold_start_multiplier,
    compute_remaining_cold_start_range,
    format_cold_start_range,
    pick_cold_start_deck_shape,
)
from recalldrill.engine.history import build_history_entry, card_trouble_score, rank_hardest_cards
from recalldrill.engine.items import (
    build_items,
    normalize_item,
    partition_into_batches,
    resolve_batch_config,
)
from recalldrill.engine.jscompat import truthy
from recalldrill.engine.progress import compute_item_progress, compute_session_progress
from recalldrill.engine.session import (
    SESSION_COMPLETE_ID,
    ItemEdit,
    advance_to_next_batch,
    apply_answer,
    apply_next,
    compute_accuracy_percent,
    compute_batch_summary,
    edit_current_item,
    empty_stats,
    init_session,
    select_trial,
)
from recalldrill.engine.types import DrillItem, SessionState, SessionStats

EXPOSURES: list[Any] = ["fresh", "once", "familiar", 1, 2.37]


class InputMutated(Exception):
    """An engine call changed one of its arguments."""


def guarded_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    """Calls an engine function; raises InputMutated if it changed any argument."""
    before = copy.deepcopy([list(args), kwargs])
    result = fn(*args, **kwargs)
    found = first_difference(before, [list(args), kwargs])
    if found is not None:
        path, was, now = found
        raise InputMutated(
            f"{fn.__name__} mutated its input at args{path.removeprefix('[0]')}: "
            f"{json.dumps(was)} -> {json.dumps(now)}"
        )
    return result


def current_batch_items(state: SessionState) -> list[DrillItem]:
    size = state["config"].get("batchSize")
    batches = partition_into_batches(state["items"], len(state["items"]) if size is None else size)
    idx = state["batchIndex"]
    return batches[idx] if 0 <= idx < len(batches) else []


def metrics_of(state: SessionState) -> dict[str, Any]:
    """Every metric the TS side may record; tests compare the keys it did record."""
    multiplier = guarded_call(compute_cumulative_cold_start_multiplier, state)
    reps = state["config"]["encodeReps"]
    return {
        "accuracyPercent": guarded_call(compute_accuracy_percent, state["stats"]),
        "progress": guarded_call(
            compute_session_progress, state["items"], reps, current_batch_items(state)
        ),
        "multiplier": multiplier,
        "batchSummary": guarded_call(compute_batch_summary, state),
        "itemProgress": [guarded_call(compute_item_progress, i, reps) for i in state["items"]],
        "remaining": guarded_call(
            compute_remaining_cold_start_range, state, 1.8 if multiplier is None else multiplier
        ),
    }


def scenario_estimates(header: Mapping[str, Any]) -> dict[str, Any]:
    """The header's cold-start estimates, on the same separate seed as TS."""
    deck = header["deck"]
    config = header["initial"]["config"]
    with rand.seeded(rand.hash_seed(f"golden:estimate:{header['name']}")):
        by_exposure: list[dict[str, Any]] = []
        for m in EXPOSURES:
            e = compute_cold_start_estimate(
                deck, config["encodeReps"], config["chunkDifficulty"], config["ladderMode"], m
            )
            by_exposure.append(
                {
                    "multiplier": m,
                    "estimate": e,
                    "range": format_cold_start_range(e["floorSeconds"], e["ceilingSeconds"]),
                }
            )
        return {"deckShape": pick_cold_start_deck_shape(deck), "byExposure": by_exposure}


def persist_shape(state: SessionState, fixed: Mapping[str, Any]) -> dict[str, Any]:
    """SessionView's persistState after a JSON round trip (undefined fields dropped)."""
    config = state["config"]
    saved: dict[str, Any] = {
        "deckName": "golden",
        "phase": state["phase"],
        "queue": state["queue"],
        "stats": state["stats"],
        "items": state["items"],
        "encodeReps": config["encodeReps"],
        "chunkDifficulty": config.get("chunkDifficulty"),
        "stemTolerance": config.get("stemTolerance"),
        "ladderMode": config.get("ladderMode"),
        "strictPunctuation": config.get("strictPunctuation"),
        "cycleOrder": config.get("cycleOrder"),
        "batchIndex": state["batchIndex"],
        "batchSize": config.get("batchSize"),
        "batchStartStats": state["batchStartStats"],
        "finalCheckStartAttempts": state.get("finalCheckStartAttempts"),
        "currentId": state.get("currentId"),
        "sourceDeckEditable": True,
        "timestamp": fixed["saveTimestamp"],
    }
    return json.loads(json.dumps({k: v for k, v in saved.items() if v is not None}))


def apply_save_edits(saved: dict[str, Any], edits: Mapping[str, Any]) -> None:
    for k in edits.get("drop", []):
        saved.pop(k, None)
    for it in saved["items"]:
        for k in edits.get("dropItemKeys", []):
            it.pop(k, None)
    for k in edits.get("dropStatsKeys", []):
        saved["stats"].pop(k, None)
        if saved.get("batchStartStats"):
            saved["batchStartStats"].pop(k, None)
    saved.update(edits.get("set", {}))
    for patch in edits.get("patchItems", []):
        next(i for i in saved["items"] if i["id"] == patch["id"]).update(patch)


def _nullish(value: Any, default: Any) -> Any:
    return default if value is None else value


def resume_saved(saved: Mapping[str, Any], fixed: Mapping[str, Any]) -> SessionState:
    """App.handleResumeSession, then SessionView's initial initSession."""
    defaults = fixed["appDefaults"]
    mode = _nullish(saved.get("ladderMode"), defaults["ladderMode"])
    items = [guarded_call(normalize_item, it, mode) for it in saved["items"]]
    batch = guarded_call(resolve_batch_config, saved, items)
    stats = cast(SessionStats, {**empty_stats(), **saved["stats"]})
    start = saved.get("batchStartStats")
    batch_start = cast(
        SessionStats, {**empty_stats(), **(saved["stats"] if start is None else start)}
    )
    state: dict[str, Any] = {
        "items": items,
        "phase": saved["phase"],
        "queue": saved.get("queue") or [],
        "stats": stats,
        "currentId": _nullish(saved.get("currentId"), SESSION_COMPLETE_ID),
        "batchIndex": batch["batchIndex"],
        "batchStartStats": batch_start,
        "config": {
            "encodeReps": saved["encodeReps"] if truthy(saved.get("encodeReps")) else 3,
            "chunkDifficulty": _nullish(saved.get("chunkDifficulty"), defaults["chunkDifficulty"]),
            "stemTolerance": _nullish(saved.get("stemTolerance"), defaults["stemTolerance"]),
            "ladderMode": _nullish(saved.get("ladderMode"), defaults["ladderMode"]),
            "strictPunctuation": _nullish(saved.get("strictPunctuation"), False),
            "batchSize": batch["batchSize"],
            "cycleOrder": _nullish(saved.get("cycleOrder"), "shuffled"),
        },
    }
    if saved.get("finalCheckStartAttempts") is not None:
        state["finalCheckStartAttempts"] = saved["finalCheckStartAttempts"]
    return guarded_call(init_session, cast(SessionState, state))


class Runner:
    """One scenario's session plus SessionView's pending-override and Continue state."""

    def __init__(self, header: Mapping[str, Any], fixed: Mapping[str, Any]) -> None:
        self.fixed = fixed
        build = header["build"]
        initial = header["initial"]
        items = guarded_call(
            build_items,
            header["deck"],
            build["chunkPercent"],
            build["ladderMode"],
            build["batchSize"],
            build["minWordsToChunk"],
            build["shuffleWithinBatch"],
        )
        if build["allReady"]:
            items = [cast(DrillItem, {**it, "status": "ready"}) for it in items]
        start: dict[str, Any] = {
            "items": items,
            "phase": initial["phase"],
            "queue": [],
            "stats": copy.deepcopy(initial["stats"]),
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": copy.deepcopy(initial["batchStartStats"]),
            "config": copy.deepcopy(initial["config"]),
        }
        self.state: SessionState = guarded_call(init_session, cast(SessionState, start))
        self.pre_wrong: SessionState | None = None
        self.needs_next = False

    def _target(self) -> str:
        trial = select_trial(self.state)
        assert trial is not None, "no trial to answer"
        return trial["target"]

    def _commit(self, result: Mapping[str, Any], pre_wrong: SessionState | None) -> dict[str, Any]:
        self.state = result["state"]
        self.pre_wrong = pre_wrong
        self.needs_next = result["advance"] == "manual"
        return {
            "result": {
                "verdict": result["verdict"],
                "feedback": result["feedback"],
                "advance": result["advance"],
            }
        }

    def _answer(self, typed: str, revealed: bool) -> dict[str, Any]:
        pre = self.state
        result = guarded_call(apply_answer, pre, typed, revealed=revealed)
        return self._commit(result, pre if result["verdict"] == "wrong" else None)

    def execute(self, action: str) -> dict[str, Any]:
        """Runs one action; returns the step's extra fields (result, edit, saved, probe)."""
        verb, sep, arg = action.partition(":")
        if not sep:
            arg = None
        if verb == "correct":
            return self._answer(self._target(), False)
        if verb in ("wrong", "near", "type"):
            return self._answer(arg or "", False)
        if verb == "reveal":
            return self._answer(self._target() if arg is None else arg, True)
        if verb == "override":
            pre = self.pre_wrong
            assert pre is not None, "override with no pending wrong answer"
            trial = select_trial(pre)
            assert trial is not None
            result = guarded_call(apply_answer, pre, trial["target"], revealed=False, override=True)
            return self._commit(result, None)
        if verb == "override-now":
            result = guarded_call(
                apply_answer, self.state, self._target(), revealed=False, override=True
            )
            return self._commit(result, None)
        if verb == "edit":
            assert arg is not None
            edit = cast(ItemEdit, json.loads(arg))
            before = self.state
            out = guarded_call(edit_current_item, before, edit)
            self.state = out["state"]
            if self.pre_wrong is not None:
                self.pre_wrong = (
                    None
                    if out["restarted"]
                    else guarded_call(edit_current_item, self.pre_wrong, edit)["state"]
                )
            if out["restarted"]:
                self.needs_next = False
            return {"edit": {"restarted": out["restarted"], "unchanged": out["state"] is before}}
        if verb == "next":
            if self.state["phase"] == "batch-done":
                self.state = guarded_call(advance_to_next_batch, self.state)
            elif self.state["phase"] in ("cycle", "final"):
                self.state = guarded_call(apply_next, self.state)
            self.pre_wrong = None
            self.needs_next = False
            return {}
        if verb == "save-resume":
            saved = persist_shape(self.state, self.fixed)
            apply_save_edits(saved, json.loads(arg) if arg else {})
            self.state = resume_saved(json.loads(json.dumps(saved)), self.fixed)
            self.pre_wrong = None
            self.needs_next = False
            return {"saved": saved}
        if verb == "probe":
            items = self.state["items"]
            return {
                "probe": {
                    "history": guarded_call(
                        build_history_entry, self.state, self.fixed["finishedAt"]
                    ),
                    "hardest": [i["id"] for i in guarded_call(rank_hardest_cards, items)],
                    "hardestTop2": [i["id"] for i in guarded_call(rank_hardest_cards, items, 2)],
                    "trouble": [guarded_call(card_trouble_score, i) for i in items],
                }
            }
        raise AssertionError(f"unknown action {action!r}")
