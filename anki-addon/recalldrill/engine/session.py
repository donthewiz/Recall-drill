"""The pure session state machine: select_trial / apply_answer / apply_next and the
batch / cycle / Final-check transitions. Port of ``src/utils/session.ts``.

The TS module is the reference; this is a copy, not an improvement, including
the behavior its comments call known limitations. Parity is checked against
recorded TS traces in ``tests/golden/session_scenarios.json`` and
``tests/golden/session_sim.json``.

==============================  ================================
TS name                         Python name
==============================  ================================
``SESSION_COMPLETE_ID``         ``SESSION_COMPLETE_ID``
``DWELL_MS``                    ``DWELL_MS``
``orderCycleQueue``             ``order_cycle_queue``
``requeueCycleItem``            ``_requeue_cycle_item``
``requeueMissedCycleItem``      ``_requeue_missed_cycle_item``
``getCurrentBatch``             ``_get_current_batch``
``advanceEncodeState``          ``_advance_encode_state``
``stayOnCurrentItem``           ``_stay_on_current_item``
``advanceBatchState``           ``_advance_batch_state``
``advanceCycleState``           ``_advance_cycle_state``
``advanceToNextBatch``          ``advance_to_next_batch``
``emptyStats``                  ``empty_stats``
``computeAccuracyPercent``      ``compute_accuracy_percent``
``computeBatchSummary``         ``compute_batch_summary``
``initSession``                 ``init_session``
``resumeCurrentEncodeItem``     ``_resume_current_encode_item``
``selectTrial``                 ``select_trial``
``applyAnswer``                 ``apply_answer``
``recordTrialTelemetry``        ``_record_trial_telemetry``
``gradeAndAdvance``             ``_grade_and_advance``
``applyRevealedAnswer``         ``_apply_revealed_answer``
``applyNext``                   ``apply_next``
``editCurrentItem``             ``edit_current_item``
==============================  ================================

Add-on only (docs/DECISIONS.md, "Engine extensions"): every ``encodeReps`` read
for a card goes through :func:`.items.reps_for` (the card's
``encodeRepsOverride``, else the session's), and :func:`edit_current_item`
keeps a card's overrides and chunks with its own threshold. With no overrides
set, this is the TS behavior.

Every ``Math.random()`` in the TS code is a :func:`.rand.random` call here, at
the same point and in the same order (the cycle's ``2 + floor(random * 2)``
gaps, and every ``shuffle``).

No function mutates its input. The TS code mutates local copies (a spread
item, a copied queue); here every list and dict is copied before it's changed,
and a nested list (``remediateStack``, ``remediateQueue``, ``queue``,
``hardSpans``) is copied too, since ``{**d}`` and ``d.copy()`` are shallow.
Unchanged nested values are shared between the input and output states, as in
TS.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Literal, NotRequired, TypedDict

from . import rand
from .grading import exact_match, grade
from .items import (
    MIN_WORDS_TO_CHUNK,
    build_item,
    chunk_text,
    culprit_half,
    find_all_culprit_chunks,
    item_overrides,
    min_words_for,
    partition_into_batches,
    render_first_letter_cue,
    reps_for,
    required_reps_for_window,
    select_next_encode_item,
    shuffle,
    split_in_half,
)
from .jscompat import js_round, js_trim
from .types import (
    Cue,
    CycleOrder,
    DeckItem,
    DrillItem,
    Feedback,
    GradeResult,
    RemediateItem,
    SessionState,
    SessionStats,
    Trial,
    Verdict,
)

# -1 is the sentinel select_trial uses for "session complete" (build_items' ids
# start at 0, so it never collides with a real item).
SESSION_COMPLETE_ID = -1

# One key per feedback dwell. Several are no longer consulted by the web app's
# timers (see the TS comment); the table is kept whole, as in TS.
DWELL_MS: dict[str, int] = {
    "chunks-advance": 700,
    "chunks-cued-advance": 500,
    "chunks-streak-progress": 500,
    "chunks-presented": 500,
    "chunks-miss": 2200,
    "combine-ready": 600,
    "combine-advance": 700,
    "combine-streak-progress": 500,
    "combine-miss-remediate": 2200,
    "combine-miss-retry": 2200,
    "remediate-next-spot": 900,
    "remediate-resume-combine": 700,
    "remediate-expand-parent": 1100,
    "remediate-streak-progress": 500,
    "remediate-miss-split": 2200,
    "remediate-miss-retry": 2200,
    "full-advance": 600,
    "full-streak-progress": 500,
    "full-miss": 2200,
    "revealed-reset": 1200,
    "near-miss": 1200,
}


class ApplyAnswerResult(TypedDict):
    state: SessionState
    verdict: Verdict
    feedback: Feedback
    advance: Literal["auto", "manual"]


class EditResult(TypedDict):
    state: SessionState
    restarted: bool


class ItemEdit(TypedDict):
    front: str
    back: str
    extra: NotRequired[str]


class BatchSummary(TypedDict):
    batchNumber: int
    totalBatches: int
    itemsMastered: int
    batchSize: int
    trialsSpent: int
    accuracyPercent: int


class _AccuracyStats(TypedDict):
    attempts: int
    misses: int
    reveals: NotRequired[int]


def order_cycle_queue(ids: Sequence[int], cycle_order: CycleOrder | None = "shuffled") -> list[int]:
    """One cycle pass over ``ids``: deck order for 'inOrder', otherwise shuffled.

    ``None`` is TS ``undefined``, which takes the 'shuffled' default.
    """
    return sorted(ids) if cycle_order == "inOrder" else shuffle(ids)


def _requeue_cycle_item(
    queue: list[int], item_id: int, gap: int, cycle_order: CycleOrder | None = "shuffled"
) -> None:
    """Reinserts a card ``gap`` places into the current pass ('shuffled'); 'inOrder'
    leaves it for the next pass. Mutates ``queue``, which callers have copied."""
    if cycle_order == "inOrder":
        return
    queue.insert(min(gap, len(queue)), item_id)


def _requeue_missed_cycle_item(
    queue: list[int], item_id: int, cycle_order: CycleOrder | None = "shuffled"
) -> None:
    """A missed or revealed cycle card comes back a random 2-3 cards later ('shuffled').
    'inOrder' reinserts nothing (see :func:`_requeue_cycle_item`), so it draws no random
    number either."""
    if cycle_order == "inOrder":
        return
    _requeue_cycle_item(queue, item_id, 2 + math.floor(rand.random() * 2), cycle_order)


def _batch_size(state: SessionState, items: Sequence[DrillItem]) -> int:
    """TS ``state.config.batchSize ?? items.length``."""
    size = state["config"].get("batchSize")
    return len(items) if size is None else size


def _at[T](seq: Sequence[T], index: int) -> T | None:
    """TS ``seq[index]``: undefined (None) out of range, never Python's negative wrap."""
    return seq[index] if 0 <= index < len(seq) else None


def _get_current_batch(
    items: Sequence[DrillItem], batch_index: int, batch_size: int
) -> list[DrillItem]:
    """This batch's items in their current order (``partitionIntoBatches`` only slices)."""
    batch = _at(partition_into_batches(items, batch_size), batch_index)
    return batch if batch is not None else []


def _find_item(items: Sequence[DrillItem], item_id: int) -> DrillItem | None:
    """TS ``items.find(i => i.id === id)``."""
    return next((i for i in items if i["id"] == item_id), None)


def _advance_encode_state(
    items: list[DrillItem], stats: SessionStats, base: SessionState
) -> SessionState:
    """Rotates to the batch's next unfinished card, or starts its cycle phase once
    every card in the batch is 'ready'."""
    batch = _get_current_batch(items, base["batchIndex"], _batch_size(base, items))
    nxt = select_next_encode_item(batch, base["currentId"])

    if nxt is None:
        # Non-mastered only: after an edit_current_item restart mid-cycle, the
        # batch's already-mastered cards must not be served again.
        batch_queue = order_cycle_queue(
            [i["id"] for i in batch if i["status"] != "mastered"],
            base["config"].get("cycleOrder"),
        )
        return _advance_cycle_state(
            items,
            batch_queue,
            stats,
            {**base, "items": items, "phase": "cycle", "queue": batch_queue, "stats": stats},
        )

    new_items: list[DrillItem] = [
        {**i, "status": "encoding"} if i["id"] == nxt["id"] and i["status"] == "new" else i
        for i in items
    ]
    return {**base, "items": new_items, "phase": "encode", "currentId": nxt["id"], "stats": stats}


def _stay_on_current_item(
    items: list[DrillItem], stats: SessionStats, base: SessionState
) -> SessionState:
    """Chain contiguity: a chunked card stays current while its answer is assembled."""
    return {**base, "items": items, "phase": "encode", "stats": stats}


def _advance_batch_state(
    items: list[DrillItem], stats: SessionStats, base: SessionState
) -> SessionState:
    """After a batch is mastered: the next batch's interstitial ('batch-done'), or the
    Final check after the last batch."""
    total_batches = len(partition_into_batches(items, _batch_size(base, items)))
    if base["batchIndex"] + 1 >= total_batches:
        # Phase 3: one shuffled, cue-free pass over EVERY item, always shuffled.
        queue = shuffle([i["id"] for i in items])
        # An empty deck has no card to test, so the session is already complete.
        return {
            **base,
            "items": items,
            "phase": "final",
            "queue": queue[1:],
            "stats": stats,
            "currentId": queue[0] if queue else SESSION_COMPLETE_ID,
            "finalCheckStartAttempts": stats["attempts"],
        }
    # currentId is deliberately left as-is: more batches remain.
    return {**base, "items": items, "phase": "batch-done", "queue": [], "stats": stats}


def _advance_cycle_state(
    items: list[DrillItem], current_queue: Sequence[int], stats: SessionStats, base: SessionState
) -> SessionState:
    """Serves the next queued card; rebuilds the pass when the queue is empty."""
    q = list(current_queue)
    if not q:
        if base["phase"] == "final":
            # Phase 3: a single pass. The rebuild is only a resume safety net
            # for a card that was mid-trial when the session was saved.
            remaining = [i for i in items if not i.get("finalDone")]
            if not remaining:
                return {
                    **base,
                    "items": items,
                    "phase": "final",
                    "queue": [],
                    "stats": stats,
                    "currentId": SESSION_COMPLETE_ID,
                }
            q = shuffle([i["id"] for i in remaining])
        else:
            # C3: scoped to the current batch.
            batch = _get_current_batch(items, base["batchIndex"], _batch_size(base, items))
            remaining = [i for i in batch if i["status"] != "mastered"]
            if not remaining:
                return _advance_batch_state(items, stats, base)
            q = order_cycle_queue([i["id"] for i in remaining], base["config"].get("cycleOrder"))

    next_id = q.pop(0)
    return {
        **base,
        "items": items,
        "phase": "final" if base["phase"] == "final" else "cycle",
        "queue": q,
        "stats": stats,
        "currentId": next_id,
    }


def advance_to_next_batch(state: SessionState) -> SessionState:
    """"Next batch" on the interstitial: starts the next batch's encode phase."""
    reset_state: SessionState = {
        **state,
        "batchIndex": state["batchIndex"] + 1,
        "batchStartStats": state["stats"].copy(),
        "phase": "encode",
        "currentId": SESSION_COMPLETE_ID,
    }
    return _advance_encode_state(state["items"], state["stats"], reset_state)


def empty_stats() -> SessionStats:
    return {"attempts": 0, "misses": 0, "nearMisses": 0, "overrides": 0, "reveals": 0}


def compute_accuracy_percent(stats: _AccuracyStats | SessionStats) -> int:
    """Share of graded attempts answered correctly without help (reveals excluded)."""
    if stats["attempts"] <= 0:
        return 100
    reveals = stats.get("reveals")
    correct = stats["attempts"] - stats["misses"] - (0 if reveals is None else reveals)
    return max(0, js_round((correct / stats["attempts"]) * 100))


def compute_batch_summary(state: SessionState) -> BatchSummary:
    """The interstitial's summary of the current batch (1-indexed for display)."""
    batches = partition_into_batches(state["items"], _batch_size(state, state["items"]))
    batch = _at(batches, state["batchIndex"]) or []
    stats = state["stats"]
    start = state["batchStartStats"]
    trials_spent = stats["attempts"] - start["attempts"]
    stats_reveals = stats.get("reveals")
    start_reveals = start.get("reveals")
    accuracy_percent = compute_accuracy_percent(
        {
            "attempts": trials_spent,
            "misses": stats["misses"] - start["misses"],
            "reveals": (0 if stats_reveals is None else stats_reveals)
            - (0 if start_reveals is None else start_reveals),
        }
    )
    return {
        "batchNumber": state["batchIndex"] + 1,
        "totalBatches": len(batches),
        "itemsMastered": len([i for i in batch if i["status"] == "mastered"]),
        "batchSize": len(batch),
        "trialsSpent": trials_spent,
        "accuracyPercent": accuracy_percent,
    }


def init_session(state: SessionState) -> SessionState:
    """Picks the first trial of a fresh or resumed session."""
    # C3: a save made at the interstitial resumes straight back into it.
    if state["phase"] == "batch-done":
        return state
    if state["phase"] == "cycle" or state["phase"] == "final":
        return _advance_cycle_state(state["items"], state["queue"], state["stats"], state)
    resumed = _resume_current_encode_item(state)
    if resumed is not None:
        return resumed
    return _advance_encode_state(state["items"], state["stats"], state)


def _resume_current_encode_item(state: SessionState) -> SessionState | None:
    """Resumes on the saved card when it's still unfinished in the current batch."""
    batch = _get_current_batch(
        state["items"], state["batchIndex"], _batch_size(state, state["items"])
    )
    cur = _find_item(batch, state["currentId"])
    if cur is None or cur["status"] == "ready" or cur["status"] == "mastered":
        return None
    items: list[DrillItem] = [
        {**i, "status": "encoding"} if i["id"] == cur["id"] and i["status"] == "new" else i
        for i in state["items"]
    ]
    return {**state, "items": items, "phase": "encode"}


def _cue_for_streak(streak: int, target: str) -> Cue:
    """C5: attempt 0 of a stage-unit gets a firstLetter cue, attempt 1+ is blind."""
    if streak >= 1:
        return {"kind": "none"}
    return {"kind": "firstLetter", "pattern": render_first_letter_cue(target)}


def _word_count_by_space(text: str) -> int:
    """TS ``text.split(' ').length``."""
    return len(text.split(" "))


def _join_window(chunks: Sequence[str], start: int, end: int) -> str:
    """TS ``chunks.slice(start - 1, end).join(' ')`` (start >= 1 in every window)."""
    return " ".join(chunks[start - 1 : end])


def select_trial(state: SessionState) -> Trial | None:
    """The trial to show for ``state``, or None (interstitial, or session complete)."""
    # C3: the interstitial has no trial.
    if state["phase"] == "batch-done":
        return None
    it = _find_item(state["items"], state["currentId"])
    if it is None:
        return None

    if state["phase"] == "cycle":
        return {
            "itemId": it["id"],
            "stage": "cycle",
            "prompt": it["front"],
            "target": it["back"],
            "cue": {"kind": "none"},
            "label": "Spaced Retrieval Cycle",
            "detail": "Spaced Retrieval \u2022 Cycling review",
        }

    if state["phase"] == "final":
        # Excludes `it` itself: a just-answered card may already be finalDone.
        done_count = len([i for i in state["items"] if i.get("finalDone") and i["id"] != it["id"]])
        return {
            "itemId": it["id"],
            "stage": "final",
            "prompt": it["front"],
            "target": it["back"],
            "cue": {"kind": "none"},
            "label": "Final check",
            "detail": f"Final check \u2022 {done_count + 1} of {len(state['items'])}",
        }

    chunks = it["chunks"]
    if it["stage"] == "chunks" and chunks is not None:
        chunk = chunks[it["chunkIndex"]]
        # C8b: attempt 0 is a presentation, attempt 1+ is blind.
        chunk_cue: Cue = {"kind": "present"} if it["chunkStreak"] == 0 else {"kind": "none"}
        part = f"{it['chunkIndex'] + 1}"
        return {
            "itemId": it["id"],
            "stage": "chunks",
            "prompt": it["front"],
            "target": chunk,
            "cue": chunk_cue,
            "label": f"Chunk Practice \u2022 {part}/{len(chunks)}",
            "detail": f"Encoding \u2022 Part {part} of {len(chunks)}",
        }

    combine_seq = it["combineSeq"]
    if it["stage"] == "combine" and chunks is not None and combine_seq is not None:
        seq_item = combine_seq[it["combineSeqIdx"]]
        combined = _join_window(chunks, seq_item["start"], seq_item["end"])
        return {
            "itemId": it["id"],
            "stage": "combine",
            "prompt": it["front"],
            "target": combined,
            "cue": _cue_for_streak(it["combineStreak"], combined),
            "label": "Combination Practice",
            "detail": (
                f"Encoding \u2022 Combining parts {seq_item['start']}-{seq_item['end']}"
                f" ({it['combineSeqIdx'] + 1}/{len(combine_seq)})"
            ),
        }

    if it["stage"] == "remediate":
        stack = it["remediateStack"]
        r_top = stack[-1]
        r_word_count = _word_count_by_space(r_top["text"])
        queue_len = len(it["remediateQueue"])
        queue_suffix = (
            f" ({queue_len} more spot{'s' if queue_len > 1 else ''} after this)"
            if queue_len > 0
            else ""
        )
        levels = len(stack) - 1
        detail = (
            f"Isolating exact spot \u2022 drilled down {levels} level{'s' if levels > 1 else ''}"
            f", now on {r_word_count} word{'' if r_word_count == 1 else 's'}{queue_suffix}"
            if len(stack) > 1
            else f"Reinforcing this {r_word_count}-word part before combining again{queue_suffix}"
        )
        return {
            "itemId": it["id"],
            "stage": "remediate",
            "prompt": it["front"],
            "target": r_top["text"],
            "cue": _cue_for_streak(r_top["streak"], r_top["text"]),
            "label": "Precision Repair",
            "detail": detail,
        }

    # Stage: full (short phrase, or chunkDifficulty >= 100)
    return {
        "itemId": it["id"],
        "stage": "full",
        "prompt": it["front"],
        "target": it["back"],
        "cue": _cue_for_streak(it["encodeStreak"], it["back"]),
        "label": "Full Recall",
        "detail": "Encoding \u2022 Full item",
    }


def apply_answer(
    state: SessionState, typed: str, *, revealed: bool, override: bool | None = None
) -> ApplyAnswerResult:
    """Grades ``typed`` for the current trial and advances. TS ``applyAnswer(state,
    typed, { revealed, override })``; the per-card telemetry is folded in after."""
    result = _grade_and_advance(state, typed, revealed=revealed, override=override)
    return {
        **result,
        "state": _record_trial_telemetry(state, result["state"], result["verdict"]),
    }


def _record_trial_telemetry(
    before: SessionState, after: SessionState, verdict: Verdict
) -> SessionState:
    """Folds one answered trial into stats.reveals and the answered card's counters.

    Looks the card up by the trial's id (``before.currentId``), since ``after``
    may already have rotated to another card.
    """
    if verdict == "presented":
        return after
    prev = _find_item(before["items"], before["currentId"])
    if prev is None:
        return after
    prior_spans = {r["text"] for r in prev["remediateStack"]} | set(prev["remediateQueue"])

    def update(i: DrillItem) -> DrillItem:
        if i["id"] != prev["id"]:
            return i
        hard_spans = list(i.get("hardSpans") or [])
        for text in [r["text"] for r in i["remediateStack"]] + i["remediateQueue"]:
            if text in prior_spans:
                continue
            # Keep the narrowest spots: a span inside a recorded one replaces
            # it, and one containing a recorded narrower span adds nothing.
            if any(h in text for h in hard_spans):
                continue
            hard_spans = [h for h in hard_spans if text not in h] + [text]
        return {
            **i,
            "attempts": i.get("attempts", 0) + 1,
            "misses": i.get("misses", 0) + (1 if verdict == "wrong" else 0),
            "reveals": i.get("reveals", 0) + (1 if verdict == "revealed" else 0),
            "nearMisses": i.get("nearMisses", 0) + (1 if verdict == "near" else 0),
            "hardSpans": hard_spans,
        }

    items = [update(i) for i in after["items"]]
    stats: SessionStats = after["stats"]
    if verdict == "revealed":
        stats = {**after["stats"], "reveals": after["stats"].get("reveals", 0) + 1}
    return {**after, "items": items, "stats": stats}


def _success_feedback(gr: GradeResult, default_feedback: Feedback) -> Feedback:
    """C2: a near-miss always shows the diff with a neutral note."""
    if gr["verdict"] == "near":
        return {
            "text": "Close \u2014 compare the wording:",
            "type": "info",
            "diff": gr["diff"],
            "dwellKey": "near-miss",
        }
    return default_feedback


def _grade_and_advance(
    state: SessionState, typed: str, *, revealed: bool, override: bool | None
) -> ApplyAnswerResult:
    current_item = _find_item(state["items"], state["currentId"])
    if current_item is None:
        raise RuntimeError("applyAnswer called with no current item")

    is_override = override is True
    # C8b: a chunks-stage presentation trial is not an attempt. !is_override
    # guards overriding a wrong blind attempt, whose miss reset chunkStreak.
    is_presentation = (
        not is_override
        and state["phase"] == "encode"
        and current_item["stage"] == "chunks"
        and current_item["chunkStreak"] == 0
    )
    next_stats: SessionStats = {
        **state["stats"],
        "attempts": state["stats"]["attempts"] + (0 if is_override or is_presentation else 1),
        "overrides": state["stats"]["overrides"] + (1 if is_override else 0),
    }
    new_items = list(state["items"])
    it_idx = next(idx for idx, i in enumerate(new_items) if i["id"] == current_item["id"])
    it = new_items[it_idx].copy()
    # base.stats IS next_stats: later in-place increments show through, as in TS.
    base: SessionState = {**state, "stats": next_stats}

    if is_presentation:
        it["chunkStreak"] = 1
        new_items[it_idx] = it
        return {
            "state": {**base, "items": new_items},
            "verdict": "presented",
            "feedback": {
                "text": "Now try it from memory",
                "type": "info",
                "dwellKey": "chunks-presented",
            },
            "advance": "auto",
        }

    # B2 fix: a revealed trial never advances the streak and never counts as a miss.
    if revealed:
        return _apply_revealed_answer(state, it, new_items, it_idx, base)

    stem_tolerance = state["config"].get("stemTolerance")
    strict = state["config"].get("strictPunctuation")
    strict = False if strict is None else strict

    def grade_against(target: str) -> GradeResult:
        return grade(
            typed, target, lenient=True, stem_tolerance=stem_tolerance, strict_punctuation=strict
        )

    # Add-on extension: the card's own encodeReps (the session's when unset).
    encode_reps = reps_for(it, state["config"])

    if state["phase"] == "encode":
        chunks = it["chunks"]
        if it["stage"] == "chunks" and chunks is not None:
            target_chunk = chunks[it["chunkIndex"]]
            gr = grade_against(target_chunk)
            is_ok = gr["verdict"] != "wrong"
            if gr["verdict"] == "near":
                next_stats["nearMisses"] += 1

            if is_ok:
                # C8a/C8b: one blind correct answer advances the chunk.
                it["chunkIndex"] += 1
                it["chunkStreak"] = 0
                if it["chunkIndex"] >= len(chunks):
                    it["stage"] = "combine"
                    it["combineSeqIdx"] = 0
                    it["combineStreak"] = 0
                    feedback = _success_feedback(
                        gr,
                        {
                            "text": "All parts learned \u2014 now combining them",
                            "type": "success",
                            "dwellKey": "chunks-advance",
                        },
                    )
                else:
                    feedback = _success_feedback(
                        gr,
                        {"text": "Part learned!", "type": "success", "dwellKey": "chunks-advance"},
                    )
                new_items[it_idx] = it
                next_state = _stay_on_current_item(new_items, next_stats, base)
                return {
                    "state": next_state,
                    "verdict": gr["verdict"],
                    "feedback": feedback,
                    "advance": "auto",
                }

            next_stats["misses"] += 1
            it["chunkStreak"] = 0
            new_items[it_idx] = it
            # C5: a wrong verdict waits for an explicit advance.
            return {
                "state": {**base, "items": new_items, "stats": next_stats},
                "verdict": "wrong",
                "feedback": {
                    "text": "Streak reset \u2014 compare your answer:",
                    "type": "danger",
                    "diff": gr["diff"],
                    "dwellKey": "chunks-miss",
                },
                "advance": "manual",
            }

        combine_seq = it["combineSeq"]
        if it["stage"] == "combine" and chunks is not None and combine_seq is not None:
            seq_item = combine_seq[it["combineSeqIdx"]]
            combined_target = _join_window(chunks, seq_item["start"], seq_item["end"])
            was_blind = it["combineStreak"] >= 1
            gr = grade_against(combined_target)
            is_ok = gr["verdict"] != "wrong"
            if gr["verdict"] == "near":
                next_stats["nearMisses"] += 1
            # C1: 'exhaustive' keeps encodeReps on every window.
            required_reps = (
                required_reps_for_window(seq_item, len(chunks), encode_reps)
                if state["config"]["ladderMode"] == "cumulative"
                else encode_reps
            )

            if is_ok:
                it["combineStreak"] += 1
                if was_blind:
                    it["combineMissCount"] = 0

                if it["combineStreak"] >= required_reps:
                    it["combineSeqIdx"] += 1
                    it["combineStreak"] = 0
                    if it["combineSeqIdx"] >= len(combine_seq):
                        it["status"] = "ready"
                        feedback = _success_feedback(
                            gr, {"text": "Encoded!", "type": "success", "dwellKey": "combine-ready"}
                        )
                    else:
                        feedback = _success_feedback(
                            gr,
                            {
                                "text": "Combination learned!",
                                "type": "success",
                                "dwellKey": "combine-advance",
                            },
                        )
                    new_items[it_idx] = it
                    # Only the final window's completion ('ready') rotates.
                    next_state = (
                        _advance_encode_state(new_items, next_stats, base)
                        if it["status"] == "ready"
                        else _stay_on_current_item(new_items, next_stats, base)
                    )
                    return {
                        "state": next_state,
                        "verdict": gr["verdict"],
                        "feedback": feedback,
                        "advance": "auto",
                    }
                feedback = _success_feedback(
                    gr,
                    {
                        "text": f"{it['combineStreak']} of {required_reps} streaks",
                        "type": "success",
                        "dwellKey": "combine-streak-progress",
                    },
                )
                new_items[it_idx] = it
                # Phase 2: a short-of-criterion rep on the FINAL window rotates;
                # on an intermediate window the card stays current.
                next_state = (
                    _advance_encode_state(new_items, next_stats, base)
                    if it["combineSeqIdx"] == len(combine_seq) - 1
                    else _stay_on_current_item(new_items, next_stats, base)
                )
                return {
                    "state": next_state,
                    "verdict": gr["verdict"],
                    "feedback": feedback,
                    "advance": "auto",
                }

            next_stats["misses"] += 1
            it["combineStreak"] = 0
            it["combineMissCount"] += 1
            window_chunk_count = seq_item["end"] - seq_item["start"] + 1
            miss_threshold = 1 if window_chunk_count <= 2 else 2

            if it["combineMissCount"] >= miss_threshold:
                culprits = find_all_culprit_chunks(
                    typed, chunks, seq_item["start"] - 1, seq_item["end"] - 1, strict
                )
                it["remediateStack"] = [{"text": chunks[culprits[0]], "streak": 0, "missCount": 0}]
                it["remediateQueue"] = [chunks[idx] for idx in culprits[1:]]
                it["remediateReturnSeqIdx"] = it["combineSeqIdx"]
                it["combineMissCount"] = 0
                it["stage"] = "remediate"

                spot_word = "spots" if len(culprits) > 1 else "part"
                miss_msg = (
                    "Missed it \u2014 isolating "
                    if miss_threshold == 1
                    else "Repeated miss \u2014 isolating "
                )
                feedback: Feedback = {
                    "text": f"{miss_msg} {len(culprits)} trouble {spot_word} to reinforce",
                    "type": "danger",
                    "dwellKey": "combine-miss-remediate",
                }
            else:
                feedback = {
                    "text": "Streak reset \u2014 check the wording:",
                    "type": "danger",
                    "diff": gr["diff"],
                    "dwellKey": "combine-miss-retry",
                }
            new_items[it_idx] = it
            return {
                "state": {**base, "items": new_items, "stats": next_stats},
                "verdict": "wrong",
                "feedback": feedback,
                "advance": "manual",
            }

        if it["stage"] == "remediate":
            # Copy the stack (and its entries) and the queue before changing them.
            stack: list[RemediateItem] = [r.copy() for r in it["remediateStack"]]
            r_queue = list(it["remediateQueue"])
            it["remediateStack"] = stack
            it["remediateQueue"] = r_queue
            r_top = stack[-1]
            gr = grade_against(r_top["text"])
            is_ok = gr["verdict"] != "wrong"
            if gr["verdict"] == "near":
                next_stats["nearMisses"] += 1

            if is_ok:
                r_top["streak"] += 1
                r_top["missCount"] = 0
                if r_top["streak"] >= encode_reps:
                    stack.pop()
                    if not stack:
                        if r_queue:
                            next_piece = r_queue.pop(0)
                            it["remediateStack"] = [
                                {"text": next_piece, "streak": 0, "missCount": 0}
                            ]
                            feedback = _success_feedback(
                                gr,
                                {
                                    "text": "Trouble spot solid! Now checking the next spot",
                                    "type": "success",
                                    "dwellKey": "remediate-next-spot",
                                },
                            )
                            new_items[it_idx] = it
                            next_state = _stay_on_current_item(new_items, next_stats, base)
                            return {
                                "state": next_state,
                                "verdict": gr["verdict"],
                                "feedback": feedback,
                                "advance": "auto",
                            }
                        it["stage"] = "combine"
                        it["combineSeqIdx"] = it["remediateReturnSeqIdx"]
                        it["combineStreak"] = 0
                        feedback = _success_feedback(
                            gr,
                            {
                                "text": "Reinforced! Resuming progressive combining",
                                "type": "success",
                                "dwellKey": "remediate-resume-combine",
                            },
                        )
                        new_items[it_idx] = it
                        next_state = _stay_on_current_item(new_items, next_stats, base)
                        return {
                            "state": next_state,
                            "verdict": gr["verdict"],
                            "feedback": feedback,
                            "advance": "auto",
                        }
                    parent_level = stack[-1]
                    parent_level["streak"] = 0
                    parent_word_count = _word_count_by_space(parent_level["text"])
                    feedback = _success_feedback(
                        gr,
                        {
                            "text": "Isolated piece mastered \u2014 expanding to "
                            f"{parent_word_count}-word parent",
                            "type": "success",
                            "dwellKey": "remediate-expand-parent",
                        },
                    )
                    new_items[it_idx] = it
                    next_state = _stay_on_current_item(new_items, next_stats, base)
                    return {
                        "state": next_state,
                        "verdict": gr["verdict"],
                        "feedback": feedback,
                        "advance": "auto",
                    }
                feedback = _success_feedback(
                    gr,
                    {
                        "text": f"{r_top['streak']} of {encode_reps} streaks",
                        "type": "success",
                        "dwellKey": "remediate-streak-progress",
                    },
                )
                new_items[it_idx] = it
                next_state = _stay_on_current_item(new_items, next_stats, base)
                return {
                    "state": next_state,
                    "verdict": gr["verdict"],
                    "feedback": feedback,
                    "advance": "auto",
                }

            next_stats["misses"] += 1
            r_top["streak"] = 0
            r_top["missCount"] += 1
            r_word_count = _word_count_by_space(r_top["text"])

            if r_top["missCount"] >= 2 and r_word_count > 1:
                left, right = split_in_half(r_top["text"])
                culprit_piece = culprit_half(typed, left, right, strict)
                stack.append({"text": culprit_piece, "streak": 0, "missCount": 0})
                feedback = {
                    "text": "Still struggling \u2014 zooming into smaller sub-phrase",
                    "type": "danger",
                    "dwellKey": "remediate-miss-split",
                }
            else:
                feedback = {
                    "text": "Not quite \u2014 compare with target:",
                    "type": "danger",
                    "diff": gr["diff"],
                    "dwellKey": "remediate-miss-retry",
                }
            new_items[it_idx] = it
            return {
                "state": {**base, "items": new_items, "stats": next_stats},
                "verdict": "wrong",
                "feedback": feedback,
                "advance": "manual",
            }

        # Stage: full (short phrase, or chunkDifficulty >= 100)
        gr = grade_against(it["back"])
        is_ok = gr["verdict"] != "wrong"
        if gr["verdict"] == "near":
            next_stats["nearMisses"] += 1

        if is_ok:
            it["encodeStreak"] += 1
            if it["encodeStreak"] >= encode_reps:
                it["status"] = "ready"
                feedback = _success_feedback(
                    gr, {"text": "Encoded!", "type": "success", "dwellKey": "full-advance"}
                )
                new_items[it_idx] = it
                advanced_state = _advance_encode_state(new_items, next_stats, base)
                return {
                    "state": advanced_state,
                    "verdict": gr["verdict"],
                    "feedback": feedback,
                    "advance": "auto",
                }
            feedback = _success_feedback(
                gr,
                {
                    "text": f"{it['encodeStreak']} of {encode_reps} streaks",
                    "type": "success",
                    "dwellKey": "full-streak-progress",
                },
            )
            new_items[it_idx] = it
            # Phase 2: rotate to another batch card between reps.
            advanced_state = _advance_encode_state(new_items, next_stats, base)
            return {
                "state": advanced_state,
                "verdict": gr["verdict"],
                "feedback": feedback,
                "advance": "auto",
            }

        next_stats["misses"] += 1
        it["encodeStreak"] = 0
        new_items[it_idx] = it
        return {
            "state": {**base, "items": new_items, "stats": next_stats},
            "verdict": "wrong",
            "feedback": {
                "text": "Streak reset \u2014 compare your answer:",
                "type": "danger",
                "diff": gr["diff"],
                "dwellKey": "full-miss",
            },
            "advance": "manual",
        }

    if state["phase"] == "final":
        # Phase 3: grades like the cycle but never touches status/cycleStreak;
        # a miss goes straight to the end of THIS pass's queue.
        gr = grade_against(it["back"])
        is_ok = gr["verdict"] != "wrong"
        if gr["verdict"] == "near":
            next_stats["nearMisses"] += 1
        updated_queue = list(state["queue"])

        if is_ok:
            it["finalDone"] = True
            feedback = _success_feedback(
                gr,
                {
                    "text": "Correct! This card is done.",
                    "type": "success",
                    "dwellKey": "final-correct",
                },
            )
        else:
            next_stats["misses"] += 1
            it["finalMisses"] = it.get("finalMisses", 0) + 1
            feedback = {
                "text": "Missed \u2014 review answer below before continuing:",
                "type": "danger",
                "diff": gr["diff"],
                "dwellKey": "final-miss",
            }
            updated_queue.append(it["id"])

        new_items[it_idx] = it
        return {
            "state": {**base, "items": new_items, "queue": updated_queue, "stats": next_stats},
            "verdict": gr["verdict"],
            "feedback": feedback,
            "advance": "manual",
        }

    # Phase: cycle -- always manual advance; the item switch waits for apply_next.
    gr = grade_against(it["back"])
    is_ok_cycle = gr["verdict"] != "wrong"
    if gr["verdict"] == "near":
        next_stats["nearMisses"] += 1
    updated_queue = list(state["queue"])

    if is_ok_cycle:
        it["cycleStreak"] += 1
        if it["cycleStreak"] >= 2:
            it["status"] = "mastered"
            feedback = _success_feedback(
                gr,
                {
                    "text": "Mastered! Item retired.",
                    "type": "success",
                    "dwellKey": "cycle-mastered",
                },
            )
        else:
            feedback = _success_feedback(
                gr,
                {
                    "text": "Correct \u2014 will test once more later in the session.",
                    "type": "success",
                    "dwellKey": "cycle-correct",
                },
            )
            # A first-correct card goes to the END of the current pass.
            _requeue_cycle_item(
                updated_queue, it["id"], len(updated_queue), state["config"].get("cycleOrder")
            )
    else:
        next_stats["misses"] += 1
        it["cycleStreak"] = 0
        feedback = {
            "text": "Missed \u2014 review answer below before continuing:",
            "type": "danger",
            "diff": gr["diff"],
            "dwellKey": "cycle-miss",
        }
        _requeue_missed_cycle_item(updated_queue, it["id"], state["config"].get("cycleOrder"))

    new_items[it_idx] = it
    return {
        "state": {**base, "items": new_items, "queue": updated_queue, "stats": next_stats},
        "verdict": gr["verdict"],
        "feedback": feedback,
        "advance": "manual",
    }


def _apply_revealed_answer(
    state: SessionState,
    it: DrillItem,
    new_items: list[DrillItem],
    it_idx: int,
    base: SessionState,
) -> ApplyAnswerResult:
    """B2 fix: resets only the current stage's streak and never counts a miss."""
    feedback: Feedback = {
        "text": "Revealed \u2014 streak reset for this part.",
        "type": "danger",
        "dwellKey": "revealed-reset",
    }

    if state["phase"] == "cycle":
        it["cycleStreak"] = 0
        updated_queue = list(state["queue"])
        _requeue_missed_cycle_item(updated_queue, it["id"], state["config"].get("cycleOrder"))
        new_items[it_idx] = it
        return {
            "state": {**base, "items": new_items, "queue": updated_queue},
            "verdict": "revealed",
            "feedback": feedback,
            "advance": "manual",
        }

    if state["phase"] == "final":
        # Not a miss, but it counts in finalMisses and goes to the end of the queue.
        it["finalMisses"] = it.get("finalMisses", 0) + 1
        new_items[it_idx] = it
        return {
            "state": {**base, "items": new_items, "queue": [*state["queue"], it["id"]]},
            "verdict": "revealed",
            "feedback": {
                "text": "Revealed \u2014 this card comes back later in the final check.",
                "type": "danger",
                "dwellKey": "final-revealed",
            },
            "advance": "manual",
        }

    if it["stage"] == "chunks":
        it["chunkStreak"] = 0
    elif it["stage"] == "combine":
        it["combineStreak"] = 0
    elif it["stage"] == "remediate":
        stack = [r.copy() for r in it["remediateStack"]]
        it["remediateStack"] = stack
        if stack:
            stack[-1]["streak"] = 0
    else:
        it["encodeStreak"] = 0

    new_items[it_idx] = it
    return {
        "state": {**base, "items": new_items},
        "verdict": "revealed",
        "feedback": feedback,
        "advance": "auto",
    }


def apply_next(state: SessionState) -> SessionState:
    """SessionView's handleNext -> advanceCycle (cycle and Final-check phases only)."""
    return _advance_cycle_state(state["items"], state["queue"], state["stats"], state)


def edit_current_item(state: SessionState, edit: ItemEdit) -> EditResult:
    """Mid-session edit of the current card.

    No-op (the same state object) outside 'encode'/'cycle', or on an empty
    field after trimming. An answer that didn't really change (``exactMatch``
    under the deck's punctuation mode) keeps progress when the chunk count is
    the same and the card isn't in 'remediate'; anything else restarts the
    card at its id, and from 'cycle' drops back to 'encode' with an empty queue.
    Stats are never touched.
    """
    unchanged: EditResult = {"state": state, "restarted": False}
    if state["phase"] != "encode" and state["phase"] != "cycle":
        return unchanged
    old = _find_item(state["items"], state["currentId"])
    if old is None:
        return unchanged
    front = js_trim(edit["front"])
    back = js_trim(edit["back"])
    if not front or not back:
        return unchanged
    # Display-only: never enters answer_changed. TS `edit.extra?.trim() || undefined`.
    extra_raw = edit.get("extra")
    extra = js_trim(extra_raw) if extra_raw is not None else ""

    def replace_item(item: DrillItem) -> list[DrillItem]:
        return [item if i["id"] == item["id"] else i for i in state["items"]]

    def with_extra(item: DrillItem) -> DrillItem:
        if extra:
            item["extra"] = extra
        else:
            item.pop("extra", None)  # `extra: undefined` drops the key
        return item

    strict = state["config"].get("strictPunctuation")
    # Add-on extensions: the card's own threshold, else the session's, else
    # (both absent) the TS constant.
    min_words = min_words_for(old, state["config"].get("minWordsToChunk", MIN_WORDS_TO_CHUNK))
    answer_changed = not exact_match(old["back"], back, False if strict is None else strict)
    if not answer_changed:
        # An untouched back keeps its stored chunks as-is.
        if back == old["back"]:
            return {
                "state": {**state, "items": replace_item(with_extra({**old, "front": front}))},
                "restarted": False,
            }
        chunks = chunk_text(back, state["config"]["chunkDifficulty"], min_words)
        old_chunks = old["chunks"]
        same_chunk_count = (None if chunks is None else len(chunks)) == (
            None if old_chunks is None else len(old_chunks)
        )
        if same_chunk_count and old["stage"] != "remediate":
            kept: DrillItem = {**old, "front": front, "back": back, "chunks": chunks}
            return {
                "state": {**state, "items": replace_item(with_extra(kept))},
                "restarted": False,
            }

    card: DeckItem = {"front": front, "back": back}
    if extra:
        card["extra"] = extra
    rebuilt: DrillItem = {
        **build_item(
            card,
            old["id"],
            state["config"]["chunkDifficulty"],
            state["config"]["ladderMode"],
            min_words,
            # A rebuilt card is the same Anki card: it keeps its overrides.
            item_overrides(old),
        ),
        "status": "encoding",
    }
    restarted_state: SessionState = {**state, "items": replace_item(rebuilt)}
    if state["phase"] == "cycle":
        restarted_state["phase"] = "encode"
        restarted_state["queue"] = []
    return {"state": restarted_state, "restarted": True}
