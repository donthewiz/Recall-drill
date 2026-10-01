"""The session engine against recorded TS traces.

- Every scripted scenario in ``tests/golden/session_scenarios.json``, replayed
  action by action (``session_runner.Runner``): the result, the full state,
  ``select_trial`` and the metrics after every step.
- The seed-0 run of every scoreboard config in ``session_seed0.json``: the
  trial, answer, result and state hash at every step.
- The pure history / accuracy / progress / estimate cases.

Every engine call deep-copies its inputs first and fails if the call changed
them. A mismatch fails with the step, the action and the first differing key.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

import pytest
import simulate as harness
from engine_test_support import check, fail_on_difference, load_golden
from session_runner import InputMutated, Runner, guarded_call, metrics_of, scenario_estimates

from recalldrill.engine import rand
from recalldrill.engine.estimate import (
    compute_minimum_trials,
    estimate_cold_start_seconds,
    format_cold_start_range,
    pick_cold_start_deck_shape,
)
from recalldrill.engine.history import (
    build_history_card,
    build_history_entry,
    card_trouble_score,
    rank_hardest_cards,
)
from recalldrill.engine.items import build_items
from recalldrill.engine.progress import compute_item_progress, compute_session_progress
from recalldrill.engine.session import (
    DWELL_MS,
    SESSION_COMPLETE_ID,
    apply_answer,
    compute_accuracy_percent,
    edit_current_item,
    order_cycle_queue,
    select_trial,
)

SCENARIOS = load_golden("session_scenarios.json")
SEED0 = load_golden("session_seed0.json")
SIM = load_golden("session_sim.json")
PURE = SCENARIOS["pure"]

STEPS: dict[str, list[dict[str, Any]]] = defaultdict(list)
for _step in SCENARIOS["steps"]:
    STEPS[_step["scenario"]].append(_step)

SEED0_STEPS: dict[str, list[dict[str, Any]]] = defaultdict(list)
for _step in SEED0["steps"]:
    SEED0_STEPS[_step["config"]].append(_step)

LIGHT_METRICS = {"accuracyPercent", "progress", "multiplier"}
FULL_METRICS = LIGHT_METRICS | {"batchSummary", "itemProgress", "remaining"}
RECORD_KEYS = {"scenario", "step", "action"}


def _ids(cases: list[Any], key: str) -> list[str]:
    return [str(c[key]) for c in cases]


@pytest.mark.parametrize("header", SCENARIOS["scenarios"], ids=_ids(SCENARIOS["scenarios"], "name"))
def test_scenario_replays_step_for_step(header: dict[str, Any]) -> None:
    name = header["name"]
    steps = STEPS[name]
    assert len(steps) == header["stepCount"] and steps[0]["action"] == "init"
    fail_on_difference(header["estimates"], scenario_estimates(header), f"{name}: estimates")

    with rand.seeded(header["seed"]):
        runner = Runner(header, SCENARIOS["fixed"])
        for expected in steps:
            action = expected["action"]
            where = f"{name} step {expected['step']} ({action!r})"
            try:
                extra = {} if action == "init" else runner.execute(action)
            except InputMutated as e:
                pytest.fail(f"{where}: {e}", pytrace=False)
            assert set(expected["metrics"]) in (LIGHT_METRICS, FULL_METRICS)
            metrics = metrics_of(runner.state)
            actual = {
                **extra,
                "state": runner.state,
                "trial": guarded_call(select_trial, runner.state),
                "metrics": {k: metrics[k] for k in expected["metrics"]},
            }
            wanted = {k: v for k, v in expected.items() if k not in RECORD_KEYS}
            fail_on_difference(wanted, actual, where)


def test_every_scenario_names_what_it_covers() -> None:
    for header in SCENARIOS["scenarios"]:
        assert header["covers"], header["name"]


@pytest.mark.parametrize("config", list(SEED0_STEPS), ids=list(SEED0_STEPS))
def test_seed0_trace_matches_step_for_step(config: str) -> None:
    deck_name, learner_name = config.split(":")
    expected_steps = SEED0_STEPS[config]
    first = expected_steps[0]
    assert first["step"] == 0
    assert first["seed"] == harness.run_seed(deck_name, learner_name, 0)

    run = harness.run_config(SIM, deck_name, learner_name, 0, record="hash", call=guarded_call)
    hint = (
        f"diff `npx tsx anki-addon/tools/export_golden.ts --full {config}:0` against "
        f"`python anki-addon/tools/simulate.py --full {config}:0`"
    )
    if run.initial_state_hash != first["stateHash"]:
        pytest.fail(f"{config} step 0 (init): state hash differs; {hint}", pytrace=False)
    for expected, actual in zip(expected_steps[1:], run.steps, strict=False):
        where = f"{config} step {expected['step']} (typed {actual['typed']!r})"
        wanted = {k: v for k, v in expected.items() if k != "config"}
        if wanted["stateHash"] != actual["stateHash"] and all(
            k == "stateHash" or wanted[k] == actual[k] for k in wanted
        ):
            pytest.fail(f"{where}: state hash differs; {hint}", pytrace=False)
        fail_on_difference(wanted, actual, where)
    assert len(run.steps) == len(expected_steps) - 1, f"{config}: step count"


# --- Pure functions ---


@pytest.mark.parametrize("case", PURE["historyEntries"])
def test_build_history_entry(case: dict[str, Any]) -> None:
    fail_on_difference(
        case["out"], build_history_entry(case["state"], case["finishedAt"]), "buildHistoryEntry"
    )


@pytest.mark.parametrize("case", PURE["historyCards"])
def test_build_history_card(case: dict[str, Any]) -> None:
    check(build_history_card(case["item"]), case["out"], "buildHistoryCard", item=case["item"])


@pytest.mark.parametrize("case", PURE["rankHardestCards"])
def test_rank_hardest_cards(case: dict[str, Any]) -> None:
    items = case["items"]
    if "trouble" in case:
        check([card_trouble_score(i) for i in items], case["trouble"], "cardTroubleScore")
    for limit_case in case["limits"]:
        ids = [i["id"] for i in rank_hardest_cards(items, limit_case["limit"])]
        check(ids, limit_case["ids"], "rankHardestCards", limit=limit_case["limit"], items=items)


@pytest.mark.parametrize("case", PURE["accuracy"])
def test_compute_accuracy_percent(case: dict[str, Any]) -> None:
    check(compute_accuracy_percent(case["stats"]), case["out"], "computeAccuracyPercent", **case)


@pytest.mark.parametrize("case", PURE["itemProgress"])
def test_compute_item_progress(case: dict[str, Any]) -> None:
    out = [compute_item_progress(case["item"], reps) for reps in (0, 1, 2, 3, 5)]
    check(out, case["out"], "computeItemProgress", item=case["item"])


@pytest.mark.parametrize("case", PURE["sessionProgress"])
def test_compute_session_progress(case: dict[str, Any]) -> None:
    out = [
        compute_session_progress(case["items"], reps)
        if case["batch"] is None
        else compute_session_progress(case["items"], reps, case["batch"])
        for reps in (1, 2, 3)
    ]
    check(out, case["out"], "computeSessionProgress", batch=case["batch"])


def test_format_cold_start_range() -> None:
    for case in PURE["estimates"]["formatColdStartRange"]:
        check(format_cold_start_range(case["lo"], case["hi"]), case["out"], "range", **case)


def test_estimate_cold_start_seconds() -> None:
    for case in PURE["estimates"]["estimateColdStartSeconds"]:
        out = estimate_cold_start_seconds(case["trials"], case["items"])
        check(out, case["out"], "estimateColdStartSeconds", **case)


def test_compute_minimum_trials() -> None:
    for case in PURE["estimates"]["computeMinimumTrials"]:
        items = build_items(SIM["decks"][case["deck"]], 35, case["built"], None, 8, False)
        out = [
            compute_minimum_trials(items, r, case["ladderMode"], case["include"]) for r in (1, 3, 5)
        ]
        check(out, case["out"], "computeMinimumTrials", **{k: case[k] for k in ("deck", "built")})


def test_pick_cold_start_deck_shape() -> None:
    for case in PURE["estimates"]["pickColdStartDeckShape"]:
        check(pick_cold_start_deck_shape(case["deck"]), case["out"], "deckShape", deck=case["deck"])


@pytest.mark.parametrize("case", PURE["orderCycleQueue"])
def test_order_cycle_queue(case: dict[str, Any]) -> None:
    ids = case["ids"]
    with rand.seeded(case["seed"]):
        out = {
            "inOrder": order_cycle_queue(ids, "inOrder"),
            "shuffled": order_cycle_queue(ids, "shuffled"),
            "byDefault": order_cycle_queue(ids),
        }
    check(out, {k: case[k] for k in out}, "orderCycleQueue", ids=ids)
    assert ids == case["ids"]  # input untouched


def test_constants() -> None:
    check(DWELL_MS, PURE["dwellMs"], "DWELL_MS")
    check(SESSION_COMPLETE_ID, PURE["sessionCompleteId"], "SESSION_COMPLETE_ID")


@pytest.mark.parametrize("case", PURE["answerEdges"], ids=_ids(PURE["answerEdges"], "state"))
def test_apply_answer_on_hand_built_states(case: dict[str, Any]) -> None:
    state = PURE["edgeStates"][case["state"]]
    if "error" in case:
        with pytest.raises(RuntimeError) as raised:
            guarded_call(apply_answer, state, case["typed"], revealed=case["revealed"])
        assert str(raised.value) == case["error"]
    else:
        r = guarded_call(apply_answer, state, case["typed"], revealed=case["revealed"])
        fail_on_difference(case["out"], r, f"applyAnswer on {case['state']}")


@pytest.mark.parametrize("case", PURE["editEdges"], ids=_ids(PURE["editEdges"], "state"))
def test_edit_and_select_on_hand_built_states(case: dict[str, Any]) -> None:
    state = PURE["edgeStates"][case["state"]]
    r = guarded_call(edit_current_item, state, {"front": "x", "back": "y"})
    assert (r["state"] is state, r["restarted"]) == (case["unchanged"], case["restarted"])
    check(guarded_call(select_trial, state), case["trial"], "selectTrial", state=case["state"])
