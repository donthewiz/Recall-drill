// The pure session state machine: selectTrial / applyAnswer / applyNext and
// the batch / cycle / Final-check transitions.

import {
  Cue,
  DrillItem,
  SessionState,
  SessionStats,
  Trial,
  Feedback,
  Verdict,
  CycleOrder,
} from '../types';
import { exactMatch, GradeResult, grade } from './grading';
import { MIN_WORDS_TO_CHUNK, chunkText, renderFirstLetterCue, requiredRepsForWindow, splitInHalf, culpritHalf, findAllCulpritChunks, shuffle, selectNextEncodeItem, partitionIntoBatches, buildItem } from './items';

// ---------------------------------------------------------------------------
// Phase 0 extraction: pure session state machine (selectTrial / applyAnswer /
// applyNext / initSession). Transcribed verbatim from src/components/
// SessionView.tsx's handleCheck/advanceEncode/advanceCycle. The extraction
// itself changed no behavior and kept known bugs B1 (findAllCulpritChunks
// positional misfire) and B2 (a revealed answer was never read by grading);
// both were fixed afterwards, in Phase 1.
//
// currentId: -1 is the sentinel selectTrial uses to signal "session complete"
// (buildItems' ids start at 0, so -1 never collides with a real item).
// ---------------------------------------------------------------------------

export const SESSION_COMPLETE_ID = -1;

// One key per distinct setTimeout call site in the original handleCheck (17
// total: 3 chunks + 5 combine + 6 remediate + 3 full; cycle phase never uses
// a timeout -- it always waits for an explicit "Continue"/Enter action).
// 'revealed-reset' is new in Phase 1 (B2 fix): not pinned by the handoff doc,
// chosen to sit between the 500ms streak-progress dwell and the miss dwells
// since it's informational, not punitive.
// 'near-miss' is new in Phase 2 (C2): the doc pins this at ~1200ms.
// The six wrong-verdict dwells (*-miss, *-miss-retry, *-miss-split,
// combine-miss-remediate) were extended from their Phase 0 values (1600-1800)
// to 2200ms in Phase 2 (C2) so the "Count as correct" override had a window
// to be clickable in. Phase 4 (C5) made every wrong-verdict return
// `advance: 'manual'` instead, so these six keys are no longer consulted by
// any setTimeout -- the shell just waits for Enter/Next now, and the override
// stays reachable indefinitely rather than only within a dwell window. Left
// in the table rather than deleted: still meaningful as "how long this
// feedback would have shown" documentation, and DWELL_MS is a plain lookup
// table, not something worth special-casing per advance mode.
// 'chunks-cued-advance' was added in C8a (Phase 8) for the cued (attempt 0)
// success's "moved to blind, not advanced yet" feedback, then went dead one
// phase later in C8b (Phase 9): attempt 0 became an ungraded presentation
// (see 'chunks-presented' below), so there's no longer a *graded* cued
// success to show it for. 'chunks-streak-progress' has been dead since C8a
// for the same reason B2's six keys are dead -- chunks no longer has a
// "still accumulating, not there yet" state to show it in (chunkStreak only
// ever holds 0 or 1). Both left in the table for the same documentation
// reason as those six.
// 'chunks-presented' is new in C8b: the dwell for acknowledging a
// presentation trial (verdict 'presented') before the first blind attempt
// -- short, since there's no diff or streak-progress to read, just a
// transition.
export const DWELL_MS: Record<string, number> = {
  'chunks-advance': 700,
  'chunks-cued-advance': 500,
  'chunks-streak-progress': 500,
  'chunks-presented': 500,
  'chunks-miss': 2200,
  'combine-ready': 600,
  'combine-advance': 700,
  'combine-streak-progress': 500,
  'combine-miss-remediate': 2200,
  'combine-miss-retry': 2200,
  'remediate-next-spot': 900,
  'remediate-resume-combine': 700,
  'remediate-expand-parent': 1100,
  'remediate-streak-progress': 500,
  'remediate-miss-split': 2200,
  'remediate-miss-retry': 2200,
  'full-advance': 600,
  'full-streak-progress': 500,
  'full-miss': 2200,
  'revealed-reset': 1200,
  'near-miss': 1200,
};

// Builds one cycle-phase pass over `ids`. 'shuffled' (default) is the
// original random order; 'inOrder' is deck order -- DrillItem.id is the
// card's index in the deck as written (see buildItems), so sorting by id
// undoes buildItems' within-batch shuffle for the cycle phase only.
export function orderCycleQueue(ids: number[], cycleOrder: CycleOrder = 'shuffled'): number[] {
  return cycleOrder === 'inOrder' ? [...ids].sort((a, b) => a - b) : shuffle(ids);
}

// Reinserts a not-yet-mastered card into the current cycle pass `gap` cards
// ahead ('shuffled' mode). In 'inOrder' mode it does nothing: the card is
// still not mastered, so advanceCycleState picks it up again when it builds
// the next pass, and the current pass keeps its deck order intact.
function requeueCycleItem(queue: number[], id: number, gap: number, cycleOrder: CycleOrder = 'shuffled'): void {
  if (cycleOrder === 'inOrder') return;
  queue.splice(Math.min(gap, queue.length), 0, id);
}

// A missed or revealed cycle card comes back a random 2-3 cards later
// ('shuffled'). 'inOrder' reinserts nothing (see requeueCycleItem), so it
// draws no random number either.
function requeueMissedCycleItem(queue: number[], id: number, cycleOrder: CycleOrder = 'shuffled'): void {
  if (cycleOrder === 'inOrder') return;
  requeueCycleItem(queue, id, 2 + Math.floor(Math.random() * 2), cycleOrder);
}

// C3: this batch's items, in whatever order buildItems' one-time
// shuffleWithinBatches call left them in (see that function's comment) --
// partitionIntoBatches only slices, it never reorders.
function getCurrentBatch(items: DrillItem[], batchIndex: number, batchSize: number): DrillItem[] {
  return partitionIntoBatches(items, batchSize)[batchIndex] ?? [];
}

// C3: called at session/batch start and after every correct answer that
// isn't part of assembling a chunked card's answer -- every full-stage rep,
// and on a chunked card every final (whole-answer) combine-window rep,
// including the one that makes it 'ready' (chain contiguity, 2026-09-26: the
// chunk, intermediate-window and remediation successes before that use
// stayOnCurrentItem instead -- see applyAnswer's call sites). Rotates within
// the current batch via selectNextEncodeItem instead of the old "always the
// first new/encoding item in deck order" (which was fully massed: item 0 to
// completion before item 1 was ever touched). Once every item in the batch
// is 'ready', starts that batch's cycle phase, scoped to just its items.
function advanceEncodeState(
  items: DrillItem[],
  stats: SessionStats,
  base: SessionState
): SessionState {
  const batch = getCurrentBatch(items, base.batchIndex, base.config.batchSize ?? items.length);
  const next = selectNextEncodeItem(batch, base.currentId);

  if (!next) {
    // Non-mastered only: after an editCurrentItem restart mid-cycle, the
    // batch's already-mastered cards must not be served again. On the normal
    // path nothing in the batch is mastered yet, so this is every item.
    const batchQueue = orderCycleQueue(
      batch.filter(i => i.status !== 'mastered').map(i => i.id),
      base.config.cycleOrder
    );
    return advanceCycleState(items, batchQueue, stats, {
      ...base,
      items,
      phase: 'cycle',
      queue: batchQueue,
      stats,
    });
  }

  const newItems = items.map(i =>
    i.id === next.id && i.status === 'new' ? { ...i, status: 'encoding' as const } : i
  );
  return { ...base, items: newItems, phase: 'encode', currentId: next.id, stats };
}

// Chain contiguity (2026-09-26): a chunked card stays current while its
// answer is being assembled -- chunks, intermediate combine windows, and
// remediation -- because forward chaining depends on contiguity, and each
// step there has a different target, so there are no same-target reps to
// space out. Rotation resumes on the final (whole-answer) window's reps.
function stayOnCurrentItem(items: DrillItem[], stats: SessionStats, base: SessionState): SessionState {
  return { ...base, items, phase: 'encode', stats };
}

// C3: once every item in the CURRENT batch is mastered, either moves to the
// next batch's interstitial (phase 'batch-done' -- SessionView shows the
// summary and waits for "Next batch"/"Save and stop"; see advanceToNextBatch)
// or, if this was the last batch, enters the Final check (Phase 3) instead
// of ending the session there.
function advanceBatchState(items: DrillItem[], stats: SessionStats, base: SessionState): SessionState {
  const totalBatches = partitionIntoBatches(items, base.config.batchSize ?? items.length).length;
  if (base.batchIndex + 1 >= totalBatches) {
    // Phase 3: one shuffled, cue-free pass over EVERY item in the session
    // (not just this batch) -- always shuffled regardless of cycleOrder,
    // since its job is an Anki-shaped final test, not another review cycle.
    // This also covers the last-remaining-card-at-lag-0 case the cycle
    // phase can otherwise leave behind (see the Known limitations note this
    // phase retires in docs/V2-HANDOFF.md).
    const queue = shuffle(items.map(i => i.id));
    // An empty deck has no card to test, so the session is already complete.
    const nextId = queue.shift() ?? SESSION_COMPLETE_ID;
    // Phase 3: records the attempts total as of this exact instant, so
    // computeCumulativeColdStartMultiplier can exclude in-progress
    // Final-check attempts from its numerator until the Final check is
    // actually done (see that function's doc comment).
    return { ...base, items, phase: 'final', queue, stats, currentId: nextId, finalCheckStartAttempts: stats.attempts };
  }
  // currentId is deliberately left as-is (not SESSION_COMPLETE_ID): that
  // sentinel means "the whole session is done" to SessionView's finishing
  // effect, and more batches remain here. selectTrial short-circuits on
  // phase 'batch-done' before ever looking currentId up.
  return { ...base, items, phase: 'batch-done', queue: [], stats };
}

function advanceCycleState(
  items: DrillItem[],
  currentQueue: number[],
  stats: SessionStats,
  base: SessionState
): SessionState {
  let q = [...currentQueue];
  if (!q.length) {
    if (base.phase === 'final') {
      // Phase 3: a single continuous pass over the whole deck, not a
      // repeating cycle -- a correct answer marks the card finalDone and
      // never re-adds it, while a miss/reveal pushes it to the end of THIS
      // SAME queue (see applyAnswer/applyRevealedAnswer), so in the normal
      // (uninterrupted) case the queue only ever empties once every item is
      // finalDone. The `remaining.length` rebuild below is purely a resume
      // safety net: a card that was mid-trial (already popped, not yet
      // answered) when the session was saved is excluded from the
      // persisted queue, same as any in-flight cycle-phase card -- without
      // this, that one card could be silently dropped from the pass instead
      // of self-healing on the next queue-empty check the way a cycle pass
      // rebuild already does for 'mastered'.
      const remaining = items.filter(i => !i.finalDone);
      if (!remaining.length) {
        return { ...base, items, phase: 'final', queue: [], stats, currentId: SESSION_COMPLETE_ID };
      }
      q = shuffle(remaining.map(i => i.id));
    } else {
      // C3: scoped to the current batch, not the whole deck -- each batch
      // runs its own cycle phase to mastery before the next batch's encode
      // phase starts. A non-batched (whole-deck) session is just the
      // batchSize>=items.length degenerate case of the same code path.
      const batch = getCurrentBatch(items, base.batchIndex, base.config.batchSize ?? items.length);
      const remaining = batch.filter(i => i.status !== 'mastered');
      if (!remaining.length) {
        return advanceBatchState(items, stats, base);
      }
      q = orderCycleQueue(remaining.map(i => i.id), base.config.cycleOrder);
    }
  }

  const nextId = q.shift()!;
  return { ...base, items, phase: base.phase === 'final' ? 'final' : 'cycle', queue: q, stats, currentId: nextId };
}

// C3: advances batchIndex and starts the new batch's encode phase. Called
// when the learner clicks "Next batch" on the interstitial (phase
// 'batch-done'). currentId is reset to SESSION_COMPLETE_ID first purely as
// "no previous item" input to selectNextEncodeItem's round-robin (the new
// batch's items never contain that id, so it falls through to "start from
// the front" the same as any id from a different batch would).
export function advanceToNextBatch(state: SessionState): SessionState {
  const resetState: SessionState = {
    ...state,
    batchIndex: state.batchIndex + 1,
    batchStartStats: { ...state.stats },
    phase: 'encode',
    currentId: SESSION_COMPLETE_ID,
  };
  return advanceEncodeState(state.items, state.stats, resetState);
}

export function emptyStats(): SessionStats {
  return { attempts: 0, misses: 0, nearMisses: 0, overrides: 0, reveals: 0 };
}

// Share of graded attempts answered correctly without help: a revealed
// trial counts as an attempt but never as a miss (B2), so it's subtracted
// here explicitly -- otherwise peeking at the answer raised accuracy.
export function computeAccuracyPercent(stats: Pick<SessionStats, 'attempts' | 'misses' | 'reveals'>): number {
  if (stats.attempts <= 0) return 100;
  const correct = stats.attempts - stats.misses - (stats.reveals ?? 0);
  return Math.max(0, Math.round((correct / stats.attempts) * 100));
}

// C3: batch-level summary for the interstitial (items mastered, trials
// spent, accuracy) -- diffs `stats` against the snapshot captured when this
// batch began (batchStartStats) rather than tracking a second running
// total. batchNumber/totalBatches are 1-indexed for display.
export function computeBatchSummary(state: SessionState): {
  batchNumber: number;
  totalBatches: number;
  itemsMastered: number;
  batchSize: number;
  trialsSpent: number;
  accuracyPercent: number;
} {
  const effectiveBatchSize = state.config.batchSize ?? state.items.length;
  const batches = partitionIntoBatches(state.items, effectiveBatchSize);
  const batch = batches[state.batchIndex] ?? [];
  const trialsSpent = state.stats.attempts - state.batchStartStats.attempts;
  const accuracyPercent = computeAccuracyPercent({
    attempts: trialsSpent,
    misses: state.stats.misses - state.batchStartStats.misses,
    reveals: (state.stats.reveals ?? 0) - (state.batchStartStats.reveals ?? 0),
  });

  return {
    batchNumber: state.batchIndex + 1,
    totalBatches: batches.length,
    itemsMastered: batch.filter(i => i.status === 'mastered').length,
    batchSize: batch.length,
    trialsSpent,
    accuracyPercent,
  };
}

// Equivalent of SessionView's mount useEffect: picks the first trial of a
// fresh or resumed session before any answer has been submitted.
export function initSession(state: SessionState): SessionState {
  // C3: a save made exactly at the interstitial ("Save and stop" on
  // 'batch-done') resumes straight back into it -- nothing to select.
  if (state.phase === 'batch-done') return state;
  // Phase 3: resumes into the Final check the same way 'cycle' resumes into
  // its pass -- advanceCycleState's queue-empty branch already handles
  // 'final' (see its own comment for the resume safety net).
  if (state.phase === 'cycle' || state.phase === 'final') {
    return advanceCycleState(state.items, state.queue, state.stats, state);
  }
  return resumeCurrentEncodeItem(state) ?? advanceEncodeState(state.items, state.stats, state);
}

// Resume position: a save now records currentId, so a resumed encode phase
// picks up on the card that was on screen instead of the batch's first
// unfinished card. Without this, leaving mid-build (End session, reload,
// closing the app) served the other cards first and then dropped back into
// a bare chunk/window/remediation piece -- the fragmentation chain
// contiguity removed. Returns null (caller falls back to advanceEncodeState)
// for a fresh start (SESSION_COMPLETE_ID), an old save without currentId,
// or a saved card that is no longer unfinished in the current batch.
function resumeCurrentEncodeItem(state: SessionState): SessionState | null {
  const batch = getCurrentBatch(state.items, state.batchIndex, state.config.batchSize ?? state.items.length);
  const cur = batch.find(i => i.id === state.currentId);
  if (!cur || cur.status === 'ready' || cur.status === 'mastered') return null;
  const items = state.items.map(i =>
    i.id === cur.id && i.status === 'new' ? { ...i, status: 'encoding' as const } : i
  );
  return { ...state, items, phase: 'encode' };
}

export function selectTrial(state: SessionState): Trial | null {
  // C3: the interstitial has no trial -- SessionView renders the batch
  // summary instead of the card.
  if (state.phase === 'batch-done') return null;
  const it = state.items.find(i => i.id === state.currentId);
  if (!it) return null;

  // C5: attempt 0 of a stage-unit (streak 0) gets a firstLetter cue; attempt
  // 1+ (streak >= 1) is fully blind. The cycle phase never had a copy-typing
  // attempt to remove, so it stays fully blind unconditionally, as before.
  const cueForStreak = (streak: number, target: string): Cue =>
    streak >= 1 ? { kind: 'none' } : { kind: 'firstLetter', pattern: renderFirstLetterCue(target) };

  if (state.phase === 'cycle') {
    return {
      itemId: it.id,
      stage: 'cycle',
      prompt: it.front,
      target: it.back,
      cue: { kind: 'none' },
      label: 'Spaced Retrieval Cycle',
      detail: 'Spaced Retrieval • Cycling review',
    };
  }

  if (state.phase === 'final') {
    // Phase 3: one shuffled, cue-free pass over every item -- k is "how many
    // OTHER cards have already finished the Final check, plus this one", so
    // the counter reads 1-of-N on the very first card and N-of-N on the
    // last. Excludes `it` itself deliberately: SessionView commits a
    // manual-advance result to state immediately on Check (not just on
    // Continue -- see handleCheck), so by the time this trial's own
    // feedback is showing, `it.finalDone` may already be true in `state`
    // for a just-answered-correctly card; counting it here would double
    // count it (e.g. "5 of 4" on the last card) until Continue moves on.
    const doneCount = state.items.filter(i => i.finalDone && i.id !== it.id).length;
    return {
      itemId: it.id,
      stage: 'final',
      prompt: it.front,
      target: it.back,
      cue: { kind: 'none' },
      label: 'Final check',
      detail: `Final check • ${doneCount + 1} of ${state.items.length}`,
    };
  }

  if (it.stage === 'chunks' && it.chunks) {
    const chunk = it.chunks[it.chunkIndex];
    // C8b: attempt 0 (chunkStreak 0) is a presentation, not a graded cued
    // typing attempt -- the chunk's full text is shown (via Trial.target,
    // same as every other cue), ungraded, and acknowledged with Enter/
    // Continue. Attempt 1+ is unchanged: fully blind.
    const chunkCue: Cue = it.chunkStreak === 0 ? { kind: 'present' } : { kind: 'none' };
    return {
      itemId: it.id,
      stage: 'chunks',
      prompt: it.front,
      target: chunk,
      cue: chunkCue,
      label: `Chunk Practice • ${it.chunkIndex + 1}/${it.chunks.length}`,
      detail: `Encoding • Part ${it.chunkIndex + 1} of ${it.chunks.length}`,
    };
  }

  if (it.stage === 'combine' && it.chunks && it.combineSeq) {
    const seqItem = it.combineSeq[it.combineSeqIdx];
    const combined = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
    return {
      itemId: it.id,
      stage: 'combine',
      prompt: it.front,
      target: combined,
      cue: cueForStreak(it.combineStreak, combined),
      label: 'Combination Practice',
      detail: `Encoding • Combining parts ${seqItem.start}-${seqItem.end} (${it.combineSeqIdx + 1}/${it.combineSeq.length})`,
    };
  }

  if (it.stage === 'remediate') {
    const rTop = it.remediateStack[it.remediateStack.length - 1];
    const rWordCount = rTop.text.split(' ').length;
    const queueSuffix =
      it.remediateQueue.length > 0
        ? ` (${it.remediateQueue.length} more spot${it.remediateQueue.length > 1 ? 's' : ''} after this)`
        : '';
    const detail =
      it.remediateStack.length > 1
        ? `Isolating exact spot • drilled down ${it.remediateStack.length - 1} level${
            it.remediateStack.length - 1 > 1 ? 's' : ''
          }, now on ${rWordCount} word${rWordCount === 1 ? '' : 's'}${queueSuffix}`
        : `Reinforcing this ${rWordCount}-word part before combining again${queueSuffix}`;
    return {
      itemId: it.id,
      stage: 'remediate',
      prompt: it.front,
      target: rTop.text,
      cue: cueForStreak(rTop.streak, rTop.text),
      label: 'Precision Repair',
      detail,
    };
  }

  // Stage: full (short phrase <= 3 words, or chunkDifficulty >= 100)
  return {
    itemId: it.id,
    stage: 'full',
    prompt: it.front,
    target: it.back,
    cue: cueForStreak(it.encodeStreak, it.back),
    label: 'Full Recall',
    detail: 'Encoding • Full item',
  };
}

export interface ApplyAnswerResult {
  state: SessionState;
  verdict: Verdict;
  feedback: Feedback;
  advance: 'auto' | 'manual';
}

export function applyAnswer(
  state: SessionState,
  typed: string,
  opts: { revealed: boolean; override?: boolean }
): ApplyAnswerResult {
  const result = gradeAndAdvance(state, typed, opts);
  return {
    ...result,
    state: recordTrialTelemetry(state, result.state, result.verdict),
  };
}

// Folds one answered trial into stats.reveals and the answered card's own
// counters. Runs after the grading/transition logic so none of its many
// branches has to do this bookkeeping itself. Looks the card up by the
// trial's id (before.currentId), since `after` may already have rotated to
// another card. A "Count as correct" override counts as the card's attempt,
// so the card ends up exactly as a typed correct answer would leave it.
function recordTrialTelemetry(
  before: SessionState,
  after: SessionState,
  verdict: Verdict
): SessionState {
  if (verdict === 'presented') return after;
  const prev = before.items.find(i => i.id === before.currentId);
  if (!prev) return after;
  const priorSpans = new Set([...prev.remediateStack.map(r => r.text), ...prev.remediateQueue]);
  const items = after.items.map(i => {
    if (i.id !== prev.id) return i;
    let hardSpans = [...(i.hardSpans ?? [])];
    for (const text of [...i.remediateStack.map(r => r.text), ...i.remediateQueue]) {
      if (priorSpans.has(text)) continue;
      // Keep the narrowest spots: remediation halves a failing chunk, so a
      // new span inside a recorded one replaces it, and one that contains
      // an already-recorded narrower span adds nothing.
      if (hardSpans.some(h => text.includes(h))) continue;
      hardSpans = [...hardSpans.filter(h => !h.includes(text)), text];
    }
    return {
      ...i,
      attempts: (i.attempts ?? 0) + 1,
      misses: (i.misses ?? 0) + (verdict === 'wrong' ? 1 : 0),
      reveals: (i.reveals ?? 0) + (verdict === 'revealed' ? 1 : 0),
      nearMisses: (i.nearMisses ?? 0) + (verdict === 'near' ? 1 : 0),
      hardSpans,
    };
  });
  const stats =
    verdict === 'revealed' ? { ...after.stats, reveals: (after.stats.reveals ?? 0) + 1 } : after.stats;
  return { ...after, items, stats };
}

function gradeAndAdvance(
  state: SessionState,
  typed: string,
  // override (C2): retroactively counts a still-pending wrong verdict as
  // exact. The shell implements this by re-calling applyAnswer with the
  // trial's own target text as `typed` (which always grades 'exact') and
  // override: true -- override only changes stats accounting below (no new
  // attempt, +1 to overrides instead), not the grading itself.
  opts: { revealed: boolean; override?: boolean }
): ApplyAnswerResult {
  const currentItem = state.items.find(i => i.id === state.currentId);
  if (!currentItem) {
    throw new Error('applyAnswer called with no current item');
  }

  const isOverride = opts.override === true;
  // C8b: a chunks-stage presentation trial (chunkStreak 0, cue 'present') --
  // nothing was graded, so it must not count as an attempt. !isOverride
  // guards the one case where chunkStreak legitimately reads 0 here despite
  // a real graded answer having just happened: overriding a wrong blind
  // attempt, whose miss already reset chunkStreak to 0 before the override
  // call -- that's a real (retroactively-exact) answer, not a presentation.
  const isPresentation =
    !isOverride &&
    state.phase === 'encode' &&
    currentItem.stage === 'chunks' &&
    currentItem.chunkStreak === 0;
  const nextStats: SessionStats = {
    ...state.stats,
    attempts: state.stats.attempts + (isOverride || isPresentation ? 0 : 1),
    overrides: state.stats.overrides + (isOverride ? 1 : 0),
  };
  const newItems = [...state.items];
  const itIdx = newItems.findIndex(i => i.id === currentItem.id);
  const it = { ...newItems[itIdx] };
  const base: SessionState = { ...state, stats: nextStats };

  if (isPresentation) {
    it.chunkStreak = 1;
    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems },
      verdict: 'presented',
      feedback: { text: 'Now try it from memory', type: 'info', dwellKey: 'chunks-presented' },
      advance: 'auto',
    };
  }

  // B2 fix: a revealed trial must not advance the streak and must not count
  // as a miss, regardless of what was typed (including typing the now-visible
  // answer correctly). Resets the current stage's streak to 0 and stays on
  // the same trial -- it never reaches the per-stage grading below.
  if (opts.revealed) {
    return applyRevealedAnswer(state, it, newItems, itIdx, base);
  }

  const gradeOpts = {
    lenient: true,
    stemTolerance: state.config.stemTolerance,
    strictPunctuation: state.config.strictPunctuation ?? false,
  };

  // C2: a near-miss verdict always shows the diff with a neutral note and the
  // 1200ms dwell, overriding whatever stage-specific success feedback/dwell
  // an exact match would have used -- the doc treats every near-miss
  // uniformly regardless of which transition it triggered.
  const successFeedback = (gr: GradeResult, defaultFeedback: Feedback): Feedback => {
    if (gr.verdict === 'near') {
      return { text: 'Close — compare the wording:', type: 'info', diff: gr.diff, dwellKey: 'near-miss' };
    }
    return defaultFeedback;
  };

  if (state.phase === 'encode') {
    if (it.stage === 'chunks' && it.chunks) {
      const targetChunk = it.chunks[it.chunkIndex];
      const gr = grade(typed, targetChunk, gradeOpts);
      const isOk = gr.verdict !== 'wrong';
      if (gr.verdict === 'near') nextStats.nearMisses++;

      if (isOk) {
        // C8a/C8b: the chunks stage's advance criterion is "one correct
        // answer at cue level 'none'" -- encodeReps no longer paces it
        // (unlike combine's final window and the full stage, which still
        // use it). By the time grading is reached here, chunkStreak is
        // always 1: the presentation short-circuit above (C8b) intercepts
        // every chunkStreak-0 attempt before grading, so any correct answer
        // that reaches this branch is necessarily the single blind attempt
        // (or an override retroactively counting one as correct) and
        // advances the chunk immediately, every time.
        it.chunkIndex++;
        it.chunkStreak = 0;
        let feedback: Feedback;
        if (it.chunkIndex >= it.chunks.length) {
          it.stage = 'combine';
          it.combineSeqIdx = 0;
          it.combineStreak = 0;
          feedback = successFeedback(gr, {
            text: 'All parts learned — now combining them',
            type: 'success',
            dwellKey: 'chunks-advance',
          });
        } else {
          feedback = successFeedback(gr, {
            text: 'Part learned!',
            type: 'success',
            dwellKey: 'chunks-advance',
          });
        }
        newItems[itIdx] = it;
        // Chain contiguity: stay on this card through its chunks and
        // combine ladder (see stayOnCurrentItem).
        const nextState = stayOnCurrentItem(newItems, nextStats, base);
        return { state: nextState, verdict: gr.verdict, feedback, advance: 'auto' };
      }

      nextStats.misses++;
      it.chunkStreak = 0;
      const feedback: Feedback = {
        text: 'Streak reset — compare your answer:',
        type: 'danger',
        diff: gr.diff,
        dwellKey: 'chunks-miss',
      };
      newItems[itIdx] = it;
      // C5: a wrong verdict now waits for an explicit advance (Enter/Next)
      // instead of an auto-advance timer, so the diff is actually read and
      // C2's "Count as correct" override stays reachable indefinitely rather
      // than only within a dwell window.
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'manual',
      };
    }

    if (it.stage === 'combine' && it.chunks && it.combineSeq) {
      const seqItem = it.combineSeq[it.combineSeqIdx];
      const combinedTarget = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
      const wasBlind = it.combineStreak >= 1;
      const gr = grade(typed, combinedTarget, gradeOpts);
      const isOk = gr.verdict !== 'wrong';
      if (gr.verdict === 'near') nextStats.nearMisses++;
      // C1: 'exhaustive' keeps the original uniform encodeReps-per-window
      // requirement (so the ladder-mode trial-count comparison stays
      // apples-to-apples); 'cumulative' needs only 1 on every window except
      // the final (whole-answer) one.
      const requiredReps =
        state.config.ladderMode === 'cumulative'
          ? requiredRepsForWindow(seqItem, it.chunks.length, state.config.encodeReps)
          : state.config.encodeReps;

      if (isOk) {
        it.combineStreak++;
        if (wasBlind) it.combineMissCount = 0;

        if (it.combineStreak >= requiredReps) {
          it.combineSeqIdx++;
          it.combineStreak = 0;
          let feedback: Feedback;
          if (it.combineSeqIdx >= it.combineSeq.length) {
            it.status = 'ready';
            feedback = successFeedback(gr, { text: 'Encoded!', type: 'success', dwellKey: 'combine-ready' });
          } else {
            feedback = successFeedback(gr, {
              text: 'Combination learned!',
              type: 'success',
              dwellKey: 'combine-advance',
            });
          }
          newItems[itIdx] = it;
          // Chain contiguity: only the final window's completion ('ready')
          // rotates; clearing an intermediate window stays on this card.
          const nextState =
            it.status === 'ready'
              ? advanceEncodeState(newItems, nextStats, base)
              : stayOnCurrentItem(newItems, nextStats, base);
          return { state: nextState, verdict: gr.verdict, feedback, advance: 'auto' };
        }
        const feedback = successFeedback(gr, {
          text: `${it.combineStreak} of ${requiredReps} streaks`,
          type: 'success',
          dwellKey: 'combine-streak-progress',
        });
        newItems[itIdx] = it;
        // Phase 2 (within-session spacing): a correct rep still short of
        // criterion on the FINAL (whole-answer) window rotates to another
        // batch card, so repeated reps of the same target are spread out
        // across the batch instead of running back to back. On an
        // intermediate window (short-of-criterion reps there only happen in
        // 'exhaustive' ladder mode) the card stays current instead -- chain
        // contiguity, see stayOnCurrentItem. (Presentation beats are
        // chunks-stage only, cue 'present' -- combine windows use the
        // ordinary firstLetter-then-blind cue ladder via cueForStreak, so
        // there's no presentation/blind pair here that rotation could split
        // apart.)
        const nextState =
          it.combineSeqIdx === it.combineSeq.length - 1
            ? advanceEncodeState(newItems, nextStats, base)
            : stayOnCurrentItem(newItems, nextStats, base);
        return { state: nextState, verdict: gr.verdict, feedback, advance: 'auto' };
      }

      nextStats.misses++;
      it.combineStreak = 0;
      it.combineMissCount++;
      const windowChunkCount = seqItem.end - seqItem.start + 1;
      const missThreshold = windowChunkCount <= 2 ? 1 : 2;

      let feedback: Feedback;
      if (it.combineMissCount >= missThreshold) {
        const culprits = findAllCulpritChunks(
          typed,
          it.chunks,
          seqItem.start - 1,
          seqItem.end - 1,
          gradeOpts.strictPunctuation
        );
        it.remediateStack = [{ text: it.chunks[culprits[0]], streak: 0, missCount: 0 }];
        it.remediateQueue = culprits.slice(1).map(idx => it.chunks![idx]);
        it.remediateReturnSeqIdx = it.combineSeqIdx;
        it.combineMissCount = 0;
        it.stage = 'remediate';

        const spotWord = culprits.length > 1 ? 'spots' : 'part';
        const missMsg = missThreshold === 1 ? 'Missed it — isolating ' : 'Repeated miss — isolating ';
        feedback = {
          text: `${missMsg} ${culprits.length} trouble ${spotWord} to reinforce`,
          type: 'danger',
          dwellKey: 'combine-miss-remediate',
        };
      } else {
        feedback = {
          text: 'Streak reset — check the wording:',
          type: 'danger',
          diff: gr.diff,
          dwellKey: 'combine-miss-retry',
        };
      }
      newItems[itIdx] = it;
      // C5: manual advance on a wrong verdict (see the chunks-miss branch above).
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'manual',
      };
    }

    if (it.stage === 'remediate') {
      // Clone remediateStack/remediateQueue (and the RemediateItem objects
      // within) before mutating -- they're shared array/object references
      // with the input state's item until cloned, and applyAnswer must never
      // mutate its input.
      it.remediateStack = it.remediateStack.map(r => ({ ...r }));
      it.remediateQueue = [...it.remediateQueue];
      const rTop = it.remediateStack[it.remediateStack.length - 1];
      const gr = grade(typed, rTop.text, gradeOpts);
      const isOk = gr.verdict !== 'wrong';
      if (gr.verdict === 'near') nextStats.nearMisses++;

      if (isOk) {
        rTop.streak++;
        rTop.missCount = 0;
        if (rTop.streak >= state.config.encodeReps) {
          it.remediateStack.pop();
          if (it.remediateStack.length === 0) {
            if (it.remediateQueue.length > 0) {
              const nextPiece = it.remediateQueue.shift()!;
              it.remediateStack = [{ text: nextPiece, streak: 0, missCount: 0 }];
              const feedback = successFeedback(gr, {
                text: 'Trouble spot solid! Now checking the next spot',
                type: 'success',
                dwellKey: 'remediate-next-spot',
              });
              newItems[itIdx] = it;
              // Chain contiguity: remediation is error correction inside the
              // chain, like a wrong-answer retry -- every success return in
              // this branch stays on the card (see stayOnCurrentItem). Once
              // it hands back to the final window, those reps rotate.
              const nextState = stayOnCurrentItem(newItems, nextStats, base);
              return {
                state: nextState,
                verdict: gr.verdict,
                feedback,
                advance: 'auto',
              };
            }
            it.stage = 'combine';
            it.combineSeqIdx = it.remediateReturnSeqIdx;
            it.combineStreak = 0;
            const feedback = successFeedback(gr, {
              text: 'Reinforced! Resuming progressive combining',
              type: 'success',
              dwellKey: 'remediate-resume-combine',
            });
            newItems[itIdx] = it;
            const nextState = stayOnCurrentItem(newItems, nextStats, base);
            return { state: nextState, verdict: gr.verdict, feedback, advance: 'auto' };
          }
          const parentLevel = it.remediateStack[it.remediateStack.length - 1];
          parentLevel.streak = 0;
          const parentWordCount = parentLevel.text.split(' ').length;
          const feedback = successFeedback(gr, {
            text: `Isolated piece mastered — expanding to ${parentWordCount}-word parent`,
            type: 'success',
            dwellKey: 'remediate-expand-parent',
          });
          newItems[itIdx] = it;
          // Chain contiguity: stays on the card, same as the "next queued
          // spot" branch above.
          const nextState = stayOnCurrentItem(newItems, nextStats, base);
          return { state: nextState, verdict: gr.verdict, feedback, advance: 'auto' };
        }
        const feedback = successFeedback(gr, {
          text: `${rTop.streak} of ${state.config.encodeReps} streaks`,
          type: 'success',
          dwellKey: 'remediate-streak-progress',
        });
        newItems[itIdx] = it;
        // Chain contiguity: reps within a remediation span stay on the card
        // too (this was Phase 2's rotate-between-reps until 2026-09-26).
        const nextState = stayOnCurrentItem(newItems, nextStats, base);
        return { state: nextState, verdict: gr.verdict, feedback, advance: 'auto' };
      }

      nextStats.misses++;
      rTop.streak = 0;
      rTop.missCount++;
      const rWordCount = rTop.text.split(' ').length;

      let feedback: Feedback;
      if (rTop.missCount >= 2 && rWordCount > 1) {
        const halves = splitInHalf(rTop.text);
        const culpritPiece = culpritHalf(typed, halves[0], halves[1], gradeOpts.strictPunctuation);
        it.remediateStack.push({ text: culpritPiece, streak: 0, missCount: 0 });
        feedback = {
          text: 'Still struggling — zooming into smaller sub-phrase',
          type: 'danger',
          dwellKey: 'remediate-miss-split',
        };
      } else {
        feedback = {
          text: 'Not quite — compare with target:',
          type: 'danger',
          diff: gr.diff,
          dwellKey: 'remediate-miss-retry',
        };
      }
      newItems[itIdx] = it;
      // C5: manual advance on a wrong verdict (see the chunks-miss branch above).
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'manual',
      };
    }

    // Stage: full (short phrase <= 3 words, or chunkDifficulty >= 100)
    const gr = grade(typed, it.back, gradeOpts);
    const isOk = gr.verdict !== 'wrong';
    if (gr.verdict === 'near') nextStats.nearMisses++;

    if (isOk) {
      it.encodeStreak++;
      if (it.encodeStreak >= state.config.encodeReps) {
        it.status = 'ready';
        const feedback = successFeedback(gr, { text: 'Encoded!', type: 'success', dwellKey: 'full-advance' });
        newItems[itIdx] = it;
        const advancedState = advanceEncodeState(newItems, nextStats, base);
        return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
      }
      const feedback = successFeedback(gr, {
        text: `${it.encodeStreak} of ${state.config.encodeReps} streaks`,
        type: 'success',
        dwellKey: 'full-streak-progress',
      });
      newItems[itIdx] = it;
      // Phase 2 (within-session spacing): rotate to another batch card
      // between reps here too -- see the combine branch's comment above.
      const advancedState = advanceEncodeState(newItems, nextStats, base);
      return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
    }

    nextStats.misses++;
    it.encodeStreak = 0;
    const feedback: Feedback = {
      text: 'Streak reset — compare your answer:',
      type: 'danger',
      diff: gr.diff,
      dwellKey: 'full-miss',
    };
    newItems[itIdx] = it;
    // C5: manual advance on a wrong verdict (see the chunks-miss branch above).
    return {
      state: { ...base, items: newItems, stats: nextStats },
      verdict: 'wrong',
      feedback,
      advance: 'manual',
    };
  }

  if (state.phase === 'final') {
    // Phase 3: one shuffled, cue-free pass over every item. Grades like the
    // cycle, but never touches status/cycleStreak -- the card's cycle
    // mastery already stands -- and a miss/reveal doesn't use the cycle's
    // random 2-3-card gap, it goes straight to the end of THIS pass's
    // queue (see advanceCycleState's comment on why that queue only ever
    // empties once every item is finalDone).
    const gr = grade(typed, it.back, gradeOpts);
    const isOk = gr.verdict !== 'wrong';
    if (gr.verdict === 'near') nextStats.nearMisses++;
    const updatedQueue = [...state.queue];
    let feedback: Feedback;

    if (isOk) {
      it.finalDone = true;
      feedback = successFeedback(gr, {
        text: 'Correct! This card is done.',
        type: 'success',
        dwellKey: 'final-correct',
      });
    } else {
      nextStats.misses++;
      it.finalMisses = (it.finalMisses ?? 0) + 1;
      feedback = {
        text: 'Missed — review answer below before continuing:',
        type: 'danger',
        diff: gr.diff,
        dwellKey: 'final-miss',
      };
      updatedQueue.push(it.id);
    }

    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems, queue: updatedQueue, stats: nextStats },
      verdict: gr.verdict,
      feedback,
      advance: 'manual',
    };
  }

  // Phase: cycle (spaced retrieval interleaving) -- always manual advance;
  // grading updates items/queue/stats immediately but the item switch itself
  // waits for an explicit applyNext() call (mirrors handleNext/advanceCycle).
  const gr = grade(typed, it.back, gradeOpts);
  const isOkCycle = gr.verdict !== 'wrong';
  if (gr.verdict === 'near') nextStats.nearMisses++;
  const updatedQueue = [...state.queue];
  let feedback: Feedback;

  if (isOkCycle) {
    it.cycleStreak++;
    if (it.cycleStreak >= 2) {
      it.status = 'mastered';
      feedback = successFeedback(gr, {
        text: 'Mastered! Item retired.',
        type: 'success',
        dwellKey: 'cycle-mastered',
      });
    } else {
      feedback = successFeedback(gr, {
        text: 'Correct — will test once more later in the session.',
        type: 'success',
        dwellKey: 'cycle-correct',
      });
      // Within-session spacing (2026-09-24): a first-correct card goes to the
      // END of the current pass, not a fixed gap -- maximizes the trials
      // separating it from its mastering answer. Only the last remaining
      // card in a pass is exempt (queue is empty, so this is a no-op and it
      // repeats at lag 0) until the Final check covers that case instead.
      requeueCycleItem(updatedQueue, it.id, updatedQueue.length, state.config.cycleOrder);
    }
  } else {
    nextStats.misses++;
    it.cycleStreak = 0;
    feedback = {
      text: 'Missed — review answer below before continuing:',
      type: 'danger',
      diff: gr.diff,
      dwellKey: 'cycle-miss',
    };
    requeueMissedCycleItem(updatedQueue, it.id, state.config.cycleOrder);
  }

  newItems[itIdx] = it;
  return {
    state: { ...base, items: newItems, queue: updatedQueue, stats: nextStats },
    verdict: gr.verdict,
    feedback,
    advance: 'manual',
  };
}

// B2 fix: handles a revealed trial uniformly across every stage/phase. Resets
// only the current stage's own streak field to 0 -- never touches status,
// combineMissCount, remediateStack/Queue contents, or the cycle queue's
// contents beyond the same reinsertion a miss would need (the item still has
// to be retested) -- and never increments stats.misses.
function applyRevealedAnswer(
  state: SessionState,
  it: DrillItem,
  newItems: DrillItem[],
  itIdx: number,
  base: SessionState
): ApplyAnswerResult {
  const feedback: Feedback = {
    text: 'Revealed — streak reset for this part.',
    type: 'danger',
    dwellKey: 'revealed-reset',
  };

  if (state.phase === 'cycle') {
    it.cycleStreak = 0;
    const updatedQueue = [...state.queue];
    requeueMissedCycleItem(updatedQueue, it.id, state.config.cycleOrder);
    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems, queue: updatedQueue },
      verdict: 'revealed',
      feedback,
      advance: 'manual',
    };
  }

  if (state.phase === 'final') {
    // Phase 3: per B2, not a miss -- but it still counts in finalMisses, and
    // the card goes straight to the end of the queue (not the cycle's
    // random 2-3-card gap; see applyAnswer's 'final' branch for why).
    // status/cycleStreak are untouched, same as every other reveal.
    it.finalMisses = (it.finalMisses ?? 0) + 1;
    const updatedQueue = [...state.queue, it.id];
    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems, queue: updatedQueue },
      verdict: 'revealed',
      feedback: {
        text: 'Revealed — this card comes back later in the final check.',
        type: 'danger',
        dwellKey: 'final-revealed',
      },
      advance: 'manual',
    };
  }

  if (it.stage === 'chunks') {
    it.chunkStreak = 0;
  } else if (it.stage === 'combine') {
    it.combineStreak = 0;
  } else if (it.stage === 'remediate') {
    it.remediateStack = it.remediateStack.map(r => ({ ...r }));
    const rTop = it.remediateStack[it.remediateStack.length - 1];
    if (rTop) rTop.streak = 0;
  } else {
    it.encodeStreak = 0;
  }

  newItems[itIdx] = it;
  return {
    state: { ...base, items: newItems },
    verdict: 'revealed',
    feedback,
    advance: 'auto',
  };
}

// Equivalent of SessionView's handleNext -> advanceCycle. The re-entrancy
// guard for a manual advance (B5) is shell-level UI state (isProcessing),
// not part of SessionState, so it belongs in SessionView, not here.
export function applyNext(state: SessionState): SessionState {
  return advanceCycleState(state.items, state.queue, state.stats, state);
}

// Mid-session edit of the card currently being drilled (state.currentId).
// Only valid in 'encode' or 'cycle'; anything else -- including 'final'
// (Phase 3: editing the card under test mid-Final-check would let a fix
// retroactively change what "correct" means for an answer already in
// flight) -- or an empty field after trimming, returns the state unchanged.
// Stats are never touched.
//
// If the answer didn't really change -- exactMatch under the deck's own
// punctuation mode, so 'pre op' -> 'pre-op' keeps progress on a normal deck
// but not a strict one -- progress is kept and only the text (and chunk
// texts) are swapped. That needs the chunk count to stay the same and the
// item not to be in 'remediate' (whose stack holds old chunk text);
// presentation beats and cues show chunk text, so chunks can't go stale.
// Otherwise the card restarts from scratch, rebuilt exactly as buildItems
// would, at its existing id, and is served again right away -- which from
// 'cycle' means dropping back to 'encode' with an empty queue. Other items
// keep their status and cycleStreak; once the restarted card is encoded,
// advanceEncodeState rebuilds the cycle queue from the batch's non-mastered
// cards.
export function editCurrentItem(
  state: SessionState,
  edit: { front: string; back: string; extra?: string }
): { state: SessionState; restarted: boolean } {
  const unchanged = { state, restarted: false };
  if (state.phase !== 'encode' && state.phase !== 'cycle') return unchanged;
  const old = state.items.find(i => i.id === state.currentId);
  if (!old) return unchanged;
  const front = edit.front.trim();
  const back = edit.back.trim();
  if (!front || !back) return unchanged;
  // Display-only: never enters answerChanged, never affects the branch below.
  const extra = edit.extra?.trim() || undefined;

  const replaceItem = (item: DrillItem) => state.items.map(i => (i.id === item.id ? item : i));

  const answerChanged = !exactMatch(old.back, back, state.config.strictPunctuation ?? false);
  if (!answerChanged) {
    // An untouched back keeps its stored chunks as-is: recomputing could
    // disagree with how an older session chunked it (e.g. one saved before
    // MIN_WORDS_TO_CHUNK changed), and a prompt-only edit must never restart.
    if (back === old.back) {
      return { state: { ...state, items: replaceItem({ ...old, front, extra }) }, restarted: false };
    }
    const chunks = chunkText(back, state.config.chunkDifficulty, MIN_WORDS_TO_CHUNK);
    const sameChunkCount = (chunks?.length ?? null) === (old.chunks?.length ?? null);
    if (sameChunkCount && old.stage !== 'remediate') {
      return { state: { ...state, items: replaceItem({ ...old, front, back, chunks, extra }) }, restarted: false };
    }
  }

  const rebuilt: DrillItem = {
    ...buildItem({ front, back, extra }, old.id, state.config.chunkDifficulty, state.config.ladderMode, MIN_WORDS_TO_CHUNK),
    status: 'encoding',
  };
  return {
    state: {
      ...state,
      items: replaceItem(rebuilt),
      ...(state.phase === 'cycle' ? { phase: 'encode' as const, queue: [] } : {}),
    },
    restarted: true,
  };
}
