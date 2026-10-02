"""The trial-count simulation harness and its "Current engine" scoreboard, in Python.

Port of ``test/simulate.ts`` (``simulate`` and the three learner models),
``test/simulate.stats.ts`` (``runSeeded``, ``fmt``) and the first section of
``test/simulate.report.ts``. The decks and config come from
``tests/golden/session_sim.json``, which ``tools/export_golden.ts`` writes from
the TS fixtures, so both sides run the same inputs.

Run from the repo root::

    anki-addon/.venv/bin/python anki-addon/tools/simulate.py

It prints the same text, byte for byte, as the "Current engine" section of
``npm run simulate`` (the Phase 0 legacy sections are not ported).

``--difficulty-overrides`` prints, after that section, a **Python-only** one
(no TS counterpart, so it is not part of the parity check): the same decks and
learners with the FSRS difficulty pattern of :data:`OVERRIDE_PATTERN` stored on
the items (docs/DECISIONS.md, "Engine extensions"). Without the flag the output
is unchanged.

``--full <deck>:<learner>[:<run>]`` writes that seeded run's full state after
every step to ``tests/golden/_debug/<deck>.<learner>.<run>.py.jsonl``, in the
same format as ``export_golden.ts --full`` writes the TS side, for diffing.
"""

from __future__ import annotations

import copy
import hashlib
import io
import json
import math
import sys
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

ADDON_ROOT = Path(__file__).resolve().parent.parent
if str(ADDON_ROOT) not in sys.path:
    sys.path.insert(0, str(ADDON_ROOT))

from recalldrill.difficulty import easy_reps, hard_threshold  # noqa: E402
from recalldrill.engine import rand  # noqa: E402
from recalldrill.engine.items import MIN_WORDS_TO_CHUNK, build_items  # noqa: E402
from recalldrill.engine.jscompat import js_sum, js_to_fixed, utf16_len  # noqa: E402
from recalldrill.engine.session import (  # noqa: E402
    SESSION_COMPLETE_ID,
    apply_answer,
    apply_next,
    init_session,
    select_trial,
)
from recalldrill.engine.types import (  # noqa: E402
    Cue,
    DeckItem,
    ItemOverrides,
    SessionConfig,
    SessionState,
)

GOLDEN_SIM = ADDON_ROOT / "tests" / "golden" / "session_sim.json"
DEBUG_DIR = ADDON_ROOT / "tests" / "golden" / "_debug"

# test/simulate.ts's tunables.
TYPING_CPS = 4.5
PER_TRIAL_OVERHEAD_SEC = 1.5
MAX_TRIALS = 20000

RUNS_PER_CONFIG = 50
PLUS_MINUS = "\u00b1"

# pCorrect(attemptIdx, cue, priorExposures)
LearnerModel = Callable[[int, Cue, int], float]


def perfect_learner(attempt_idx: int, cue: Cue, prior_exposures: int) -> float:
    return 1


def realistic_learner(attempt_idx: int, cue: Cue, prior_exposures: int) -> float:
    if cue["kind"] == "firstLetter":
        return min(0.97, 0.75 + 0.1 * prior_exposures)
    return min(0.95, 0.55 + 0.12 * prior_exposures)


def struggling_learner(attempt_idx: int, cue: Cue, prior_exposures: int) -> float:
    if cue["kind"] == "firstLetter":
        return min(0.95, 0.5 + 0.08 * prior_exposures)
    return min(0.95, 0.3 + 0.08 * prior_exposures)


LEARNERS: dict[str, LearnerModel] = {
    "perfect": perfect_learner,
    "realistic": realistic_learner,
    "struggling": struggling_learner,
}


def canonical_json(value: object) -> str:
    """Sorted keys, no whitespace, non-ASCII unescaped: what the TS side hashes."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _assert_integer_json(value: object, path: str) -> None:
    if isinstance(value, float):
        raise TypeError(f"float in SessionState at {path}: {value!r}")
    if isinstance(value, list):
        for i, v in enumerate(value):
            _assert_integer_json(v, f"{path}[{i}]")
    elif isinstance(value, dict):
        for k, v in value.items():
            _assert_integer_json(v, f"{path}.{k}")


def state_hash(state: SessionState) -> str:
    """SHA-256 of the state's canonical JSON. Refuses floats, as the TS side does."""
    _assert_integer_json(state, "state")
    return hashlib.sha256(canonical_json(state).encode("utf-8")).hexdigest()


# An engine call: guard(fn, *args, **kwargs). Tests pass one that checks the
# engine never mutates its inputs.
EngineCall = Callable[..., Any]


def _plain_call(fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
    return fn(*args, **kwargs)


@dataclass
class SimRun:
    total_trials: int
    # Insertion order, which the report's tie-break on equal counts depends on.
    trials_by_stage: dict[str, int]
    keystrokes: int
    wall_clock_estimate: float
    attempts: int
    trace_hash: str
    initial_state_hash: str
    initial_state: SessionState | None = None
    steps: list[dict[str, Any]] = field(default_factory=lambda: [])

    def numbers(self) -> dict[str, Any]:
        """The golden's per-run record (camelCase, stage counts as ordered pairs)."""
        return {
            "totalTrials": self.total_trials,
            "trialsByStage": [[stage, n] for stage, n in self.trials_by_stage.items()],
            "keystrokes": self.keystrokes,
            "attempts": self.attempts,
            "wallClockEstimate": self.wall_clock_estimate,
            "traceHash": self.trace_hash,
        }


def simulate(
    deck: Sequence[DeckItem],
    config: SessionConfig,
    learner: LearnerModel,
    min_words_to_chunk: int = MIN_WORDS_TO_CHUNK,
    *,
    record: Literal["none", "hash", "full"] = "none",
    call: EngineCall = _plain_call,
    overrides: Sequence[ItemOverrides | None] | None = None,
) -> SimRun:
    """Port of ``simulate()``: drives the engine with a synthetic learner.

    Draws from :mod:`recalldrill.engine.rand` exactly where the TS harness calls
    ``Math.random()``, so inside ``rand.seeded(seed)`` it reproduces the TS run
    under ``withSeededRandom(seed)``. ``trace_hash`` is SHA-256 over one line
    per trial, ``itemId|stage|cue.kind|target|typed|verdict|advance|dwellKey``,
    each ending in a newline. ``record`` also keeps each step (with the state's
    hash, or the full state). ``overrides`` (Python-only, per card) is stored on
    the items; None is the TS run.
    """
    items = build_items(
        deck,
        config["chunkDifficulty"],
        config["ladderMode"],
        None,
        min_words_to_chunk,
        overrides=overrides,
    )
    state: SessionState = call(
        init_session,
        {
            "items": items,
            "phase": "encode",
            "queue": [],
            "stats": {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0},
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0},
            "config": config,
        },
    )
    initial_state = state
    initial_state_hash = state_hash(state)
    exposure_counts: dict[str, int] = {}
    trials_by_stage: dict[str, int] = {}
    lines: list[str] = []
    steps: list[dict[str, Any]] = []
    total_trials = 0
    keystrokes = 0

    while total_trials < MAX_TRIALS:
        trial = call(select_trial, state)
        if trial is None:
            break

        key = f"{trial['itemId']}:{trial['stage']}:{trial['target']}"
        prior_exposures = exposure_counts.get(key, 0)
        exposure_counts[key] = prior_exposures + 1

        p = learner(prior_exposures, trial["cue"], prior_exposures)
        correct = rand.random() < p
        typed = trial["target"] if correct else ""

        result = call(apply_answer, state, typed, revealed=False)
        total_trials += 1
        trials_by_stage[trial["stage"]] = trials_by_stage.get(trial["stage"], 0) + 1
        keystrokes += 0 if trial["cue"]["kind"] == "present" else utf16_len(trial["target"])

        state = result["state"]
        if result["advance"] == "manual" and state["phase"] in ("cycle", "final"):
            state = call(apply_next, state)

        lines.append(
            "|".join(
                [
                    str(trial["itemId"]),
                    trial["stage"],
                    trial["cue"]["kind"],
                    trial["target"],
                    typed,
                    result["verdict"],
                    result["advance"],
                    result["feedback"]["dwellKey"],
                ]
            )
        )
        if record != "none":
            step: dict[str, Any] = {
                "step": total_trials,
                "trial": trial,
                "typed": typed,
                "verdict": result["verdict"],
                "feedback": result["feedback"],
                "advance": result["advance"],
                "stateHash": state_hash(state),
            }
            if record == "full":
                step["state"] = copy.deepcopy(state)
            steps.append(step)

    if total_trials >= MAX_TRIALS:
        raise RuntimeError(f"simulate(): exceeded MAX_TRIALS ({MAX_TRIALS}) without finishing")

    return SimRun(
        total_trials=total_trials,
        trials_by_stage=trials_by_stage,
        keystrokes=keystrokes,
        wall_clock_estimate=keystrokes / TYPING_CPS + total_trials * PER_TRIAL_OVERHEAD_SEC,
        attempts=state["stats"]["attempts"],
        trace_hash=hashlib.sha256("".join(f"{line}\n" for line in lines).encode()).hexdigest(),
        initial_state_hash=initial_state_hash,
        initial_state=copy.deepcopy(initial_state) if record == "full" else None,
        steps=steps,
    )


@dataclass
class RunStats:
    mean: float
    sd: float


def mean_sd(values: Sequence[float]) -> RunStats:
    """``simulate.stats.ts``'s meanSd: left-to-right sums, sample SD (n - 1)."""
    mean = js_sum(values) / len(values)
    if len(values) < 2:
        return RunStats(mean, 0)
    # JS `(v - mean) ** 2` is the plain product (fdlibm pow returns x*x for y == 2).
    variance = js_sum((v - mean) * (v - mean) for v in values) / (len(values) - 1)
    return RunStats(mean, math.sqrt(variance))


def fmt(stats: RunStats, decimals: int = 1) -> str:
    return f"{js_to_fixed(stats.mean, decimals)} {PLUS_MINUS} {js_to_fixed(stats.sd, decimals)}"


def format_stage_breakdown(by_stage: dict[str, int]) -> str:
    """Stages by count, descending; ties keep first-seen order (JS sort is stable)."""
    ordered = sorted(by_stage.items(), key=lambda kv: -kv[1])
    return " ".join(f"{stage}:{count}" for stage, count in ordered)


def load_sim_golden() -> dict[str, Any]:
    return json.loads(GOLDEN_SIM.read_text(encoding="utf-8"))


def run_seed(deck_name: str, learner_name: str, run: int) -> int:
    """``hashSeed('current:<deck>:<learner>') + run`` (may pass 2**32; mulberry32 wraps it)."""
    return rand.hash_seed(f"current:{deck_name}:{learner_name}") + run


def run_config(
    sim: dict[str, Any], deck_name: str, learner_name: str, run: int, **kwargs: Any
) -> SimRun:
    """One seeded run of the scoreboard, exactly as ``runSeeded`` makes it."""
    with rand.seeded(run_seed(deck_name, learner_name, run)):
        return simulate(sim["decks"][deck_name], sim["config"], LEARNERS[learner_name], **kwargs)


def current_engine_report(sim: dict[str, Any], runs: dict[tuple[str, str], list[SimRun]]) -> str:
    """The "Current engine" section of ``npm run simulate``, as it prints."""
    rows = [
        "| Deck | Learner | Total trials | Keystrokes | Wall clock (est, s) "
        "| Trials by stage (last run) |",
        "|---|---|---|---|---|---|",
    ]
    for deck_name in sim["deckOrder"]:
        for learner_name in sim["learnerOrder"]:
            results = runs[(deck_name, learner_name)]
            total = mean_sd([r.total_trials for r in results])
            keys = mean_sd([r.keystrokes for r in results])
            wall = mean_sd([r.wall_clock_estimate for r in results])
            rows.append(
                f"| {deck_name} | {learner_name} | {fmt(total)} | {fmt(keys)} | {fmt(wall)} "
                f"| {format_stage_breakdown(results[-1].trials_by_stage)} |"
            )
    runs_per_config = sim["runsPerConfig"]
    header = f"\n=== Current engine, {runs_per_config} seeded runs per config (mean +/- SD) ===\n"
    return header + "\n" + "\n".join(rows) + "\n"


def all_runs(sim: dict[str, Any]) -> dict[tuple[str, str], list[SimRun]]:
    return {
        (deck_name, learner_name): [
            run_config(sim, deck_name, learner_name, i) for i in range(sim["runsPerConfig"])
        ]
        for deck_name in sim["deckOrder"]
        for learner_name in sim["learnerOrder"]
    }


# ---------------------------------------------------------------------------
# Python-only: difficulty overrides (no TS counterpart)
# ---------------------------------------------------------------------------

OVERRIDE_PATTERN: tuple[int, ...] = (1,) * 4 + (0,) * 4 + (-1,) * 4
"""Per card index: cards 0-3 hard (+1), 4-7 unchanged, 8-11 easy (-1)."""


def pattern_overrides(
    n: int, encode_reps: int, min_words_to_chunk: int = MIN_WORDS_TO_CHUNK
) -> list[ItemOverrides]:
    """:data:`OVERRIDE_PATTERN` as ``difficulty.adjust_card`` makes it, with the
    config defaults: +1 is one more rep and a chunk threshold 2 lower (never under
    4); -1 is one fewer rep (never under 2, or the deck's own if lower)."""
    out: list[ItemOverrides] = []
    for i in range(n):
        step = OVERRIDE_PATTERN[i] if i < len(OVERRIDE_PATTERN) else 0
        o: ItemOverrides = {}
        if step > 0:
            o["encodeRepsOverride"] = encode_reps + 1
            t = hard_threshold(min_words_to_chunk, 2)
            if t != min_words_to_chunk:
                o["minWordsToChunkOverride"] = t
        elif step < 0:
            reps = easy_reps(encode_reps, 2)
            if reps != encode_reps:
                o["encodeRepsOverride"] = reps
        out.append(o)
    return out


def override_runs(sim: dict[str, Any]) -> dict[tuple[str, str], list[SimRun]]:
    """The scoreboard's seeded runs again, with :func:`pattern_overrides` on the items."""
    reps = sim["config"]["encodeReps"]
    return {
        (deck_name, learner_name): [
            run_config(
                sim,
                deck_name,
                learner_name,
                i,
                overrides=pattern_overrides(len(sim["decks"][deck_name]), reps),
            )
            for i in range(sim["runsPerConfig"])
        ]
        for deck_name in sim["deckOrder"]
        for learner_name in sim["learnerOrder"]
    }


def override_report(sim: dict[str, Any], runs: dict[tuple[str, str], list[SimRun]]) -> str:
    """The Python-only section: the same table, with the override pattern."""
    table = current_engine_report(sim, runs).split("\n", 2)[2]
    header = (
        "\n=== Python-only: difficulty overrides, "
        f"{sim['runsPerConfig']} seeded runs per config (mean +/- SD) ===\n"
        "Cards 0-3 +1 rep and chunk threshold T-2, 4-7 unchanged, 8-11 -1 rep. "
        "No TS counterpart: not a parity check.\n"
    )
    return header + table


def _compact(value: object) -> str:
    """export_golden.ts's compact(): sorted keys, ASCII only."""
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def write_full_debug(sim: dict[str, Any], arg: str) -> Path:
    deck_name, _, rest = arg.partition(":")
    learner_name, _, run_text = rest.partition(":")
    run = int(run_text) if run_text else 0
    if deck_name not in sim["deckOrder"] or learner_name not in LEARNERS:
        raise SystemExit(
            f"--full takes <deck>:<learner>[:<run>], e.g. proseDeck:realistic:7 (got {arg!r})"
        )
    result = run_config(sim, deck_name, learner_name, run, record="full")
    first = {
        "step": 0,
        "seed": run_seed(deck_name, learner_name, run),
        "stateHash": result.initial_state_hash,
        "state": result.initial_state,
    }
    DEBUG_DIR.mkdir(parents=True, exist_ok=True)
    path = DEBUG_DIR / f"{deck_name}.{learner_name}.{run}.py.jsonl"
    lines = [_compact(first), *(_compact(step) for step in result.steps)]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    return path


def main(argv: Sequence[str]) -> int:
    sim = load_sim_golden()
    if "--full" in argv:
        idx = list(argv).index("--full")
        path = write_full_debug(sim, argv[idx + 1] if idx + 1 < len(argv) else "")
        print(f"wrote {path}")
        return 0
    # Byte-identical to Node's output on every platform: UTF-8, LF.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(encoding="utf-8", newline="\n")
    sys.stdout.write(current_engine_report(sim, all_runs(sim)))
    if "--difficulty-overrides" in argv:
        sys.stdout.write(override_report(sim, override_runs(sim)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
