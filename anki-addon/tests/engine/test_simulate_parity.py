"""The Python simulate() harness against the TS scoreboard, run for run.

``tests/golden/session_sim.json`` holds all 450 seeded runs behind
``npm run simulate``'s "Current engine" table (3 decks x 3 learners x 50
seeds). Since the PRNG and every draw match, each Python run must equal its TS
twin exactly: every number and the trace hash, not just the mean within an SD.
The printed table must then be byte-identical too.

The extra runs are seeded twins of the ``simulate()`` calls in
``test/simulate.spec.ts``, ``test/coldStartEstimate.consistency.spec.ts`` and
``c8b.spec.ts``, with those specs' own assertions.
"""

from __future__ import annotations

import difflib
import functools
from typing import Any

import pytest
import simulate as harness
from engine_test_support import check, load_golden

from recalldrill.engine import rand
from recalldrill.engine.estimate import compute_minimum_trials
from recalldrill.engine.items import build_items

SIM = load_golden("session_sim.json")
NUMBER_KEYS = (
    "totalTrials",
    "trialsByStage",
    "keystrokes",
    "attempts",
    "wallClockEstimate",
    "traceHash",
)
VALID_STAGES = {"chunks", "combine", "remediate", "full", "cycle", "final"}


@functools.cache
def python_run(deck: str, learner: str, run: int) -> harness.SimRun:
    return harness.run_config(SIM, deck, learner, run)


def _run_id(r: dict[str, Any]) -> str:
    return f"{r['deck']}-{r['learner']}-{r['run']:02d}"


def test_golden_has_every_run() -> None:
    assert len(SIM["runs"]) == len(SIM["deckOrder"]) * len(SIM["learnerOrder"]) * 50 == 450


@pytest.mark.parametrize("expected", SIM["runs"], ids=[_run_id(r) for r in SIM["runs"]])
def test_seeded_run_matches_ts_exactly(expected: dict[str, Any]) -> None:
    deck, learner, run = expected["deck"], expected["learner"], expected["run"]
    assert harness.run_seed(deck, learner, run) == expected["seed"]
    actual = python_run(deck, learner, run).numbers()
    check(actual, {k: expected[k] for k in NUMBER_KEYS}, "simulate()", run=_run_id(expected))


def test_scoreboard_is_byte_identical_to_npm_run_simulate() -> None:
    runs = {
        (deck, learner): [python_run(deck, learner, i) for i in range(SIM["runsPerConfig"])]
        for deck in SIM["deckOrder"]
        for learner in SIM["learnerOrder"]
    }
    report = harness.current_engine_report(SIM, runs)
    if report != SIM["report"]:
        diff = "\n".join(
            difflib.unified_diff(
                SIM["report"].splitlines(), report.splitlines(), "TS", "Python", lineterm=""
            )
        )
        pytest.fail(f"scoreboard differs from npm run simulate:\n{diff}", pytrace=False)


@pytest.mark.parametrize(
    "row",
    [
        "| shortDeck | perfect | 72.0 \u00b1 0.0 |",
        "| proseDeck | perfect | 156.0 \u00b1 0.0 |",
        "| mediumDeck | perfect | 72.0 \u00b1 0.0 |",
    ],
)
def test_perfect_learner_rows(row: str) -> None:
    """The scoreboard's fixed points: a perfect learner's trial count has no spread."""
    assert row in SIM["report"]


def _extra_run(spec: dict[str, Any]) -> harness.SimRun:
    with rand.seeded(spec["seed"]):
        return harness.simulate(
            SIM["decks"][spec["deck"]],
            spec["config"],
            harness.LEARNERS[spec["learner"]],
            spec["minWordsToChunk"],
        )


EXTRA = {spec["label"]: spec for spec in SIM["extraRuns"]}


@pytest.mark.parametrize("spec", SIM["extraRuns"], ids=list(EXTRA))
def test_extra_run_matches_ts_exactly(spec: dict[str, Any]) -> None:
    run = _extra_run(spec)
    check(run.numbers(), {k: spec[k] for k in NUMBER_KEYS}, "simulate()", label=spec["label"])
    assert run.total_trials > 0 and run.keystrokes > 0 and run.wall_clock_estimate > 0
    assert set(run.trials_by_stage) <= VALID_STAGES


CONSISTENCY = [s for s in SIM["extraRuns"] if s["spec"] == "coldStartEstimate.consistency.spec.ts"]


@pytest.mark.parametrize("spec", CONSISTENCY, ids=[s["label"] for s in CONSISTENCY])
def test_minimum_trials_matches_a_perfect_session(spec: dict[str, Any]) -> None:
    """TS: computeMinimumTrials matches a real perfect-learner session exactly (and with
    cycleOrder: inOrder)."""
    config = spec["config"]
    with rand.seeded(spec["seed"] + 1):
        items = build_items(
            SIM["decks"][spec["deck"]],
            config["chunkDifficulty"],
            config["ladderMode"],
            None,
            spec["minWordsToChunk"],
        )
    floor = compute_minimum_trials(items, config["encodeReps"], config["ladderMode"])
    assert floor == spec["predictedFloor"]
    assert _extra_run(spec).attempts == floor


def test_struggling_never_needs_fewer_trials_than_perfect() -> None:
    """TS: simulate > a struggling learner never needs fewer trials than a perfect one on
    the same deck"""
    for deck in ("shortDeck", "proseDeck"):
        perfect = _extra_run(EXTRA[f"simulate:{deck}:perfect"])
        struggling = _extra_run(EXTRA[f"simulate:{deck}:struggling"])
        assert struggling.total_trials >= perfect.total_trials


def test_cumulative_ladder_cuts_trials_by_40_percent() -> None:
    """TS: simulate > cumulative ladder gives >=40% trial-count reduction vs exhaustive once
    cards average >=4 chunks (perfect learner)"""
    exhaustive = _extra_run(EXTRA["simulate-ladder:exhaustive"])
    cumulative = _extra_run(EXTRA["simulate-ladder:cumulative"])
    assert 1 - cumulative.total_trials / exhaustive.total_trials >= 0.4


def test_presentations_count_as_trials_but_not_keystrokes() -> None:
    """TS: c8b > trialsByStage.chunks counts both the presentation and the blind attempt
    for each chunk; simulate()'s total keystrokes exactly match a hand-walked session that
    skips presentation trials"""
    run = _extra_run(EXTRA["c8b:twoChunk"])
    assert run.trials_by_stage["chunks"] == 4
    golden = load_golden("session_scenarios.json")
    walked = [s for s in golden["steps"] if s["scenario"] == "c5-no-graded-full-cue"]
    # Same deck and config, perfect answers: each answer step answered the trial
    # shown before it. Sum the graded (non-presentation) targets' lengths.
    typed = sum(
        len(prev["trial"]["target"])
        for prev, step in zip(walked, walked[1:], strict=False)
        if step["action"] == "correct" and prev["trial"]["cue"]["kind"] != "present"
    )
    assert run.keystrokes == typed > 0
