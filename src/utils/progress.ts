// C4: per-item and per-session progress for the session progress bars.

import {
  DrillItem,
} from '../types';

function clamp01(n: number): number {
  return Math.max(0, Math.min(1, n));
}

// C4: 0..1 encoding progress for a single item, weighted per the doc: 'new'
// is 0, 'ready' is 0.7, 'mastered' is 1.0, and 'encoding' is the fraction of
// the item's own ladder completed, scaled into the 0-0.7 band (so crossing
// into 'ready' is always a visible jump, and 'mastered' always reads as
// "done", not just "encoded"). Deliberately approximate about the exact
// per-window rep requirement under the cumulative ladder (C1) -- this is a
// progress *estimate* for a UI bar, not a trial-count calculation; see
// requiredRepsForWindow's doc comment for why encodeReps is still the right
// denominator in the cases where a combine window's streak is ever actually
// observed above 0 (the final window, and every window under 'exhaustive').
export function computeItemProgress(item: DrillItem, encodeReps: number): number {
  if (item.status === 'mastered') return 1;
  if (item.status === 'ready') return 0.7;
  if (item.status === 'new') return 0;

  // status === 'encoding'
  if (!item.chunks) {
    // Unchunked ('full' stage, <=3 words or chunkDifficulty 100%): a single
    // ladder rung needing encodeReps.
    const frac = encodeReps > 0 ? clamp01(item.encodeStreak / encodeReps) : 0;
    return frac * 0.7;
  }

  const totalChunks = item.chunks.length;
  const totalWindows = item.combineSeq ? item.combineSeq.length : 0;
  const totalUnits = totalChunks + totalWindows;
  if (totalUnits === 0) return 0;

  let completedUnits: number;
  if (item.stage === 'chunks') {
    // C8a: a chunk always needs exactly 1 cued + 1 blind correct answer
    // (chunkStreak only ever holds 0 or 1), independent of encodeReps --
    // so unlike combine/full below, this fraction's denominator is a fixed
    // 2, not encodeReps.
    const streakFrac = clamp01(item.chunkStreak / 2);
    completedUnits = item.chunkIndex + streakFrac;
  } else if (item.stage === 'combine') {
    const streakFrac = encodeReps > 0 ? clamp01(item.combineStreak / encodeReps) : 0;
    completedUnits = totalChunks + item.combineSeqIdx + streakFrac;
  } else {
    // 'remediate': a detour off the combine ladder to isolate a culprit
    // chunk -- combineSeqIdx doesn't move until it resolves, so progress
    // holds at the same window boundary it was at going in (never dips: a
    // combine miss already reset combineStreak to 0 before this stage was
    // entered, so completedUnits here exactly matches what it was the
    // instant before the miss).
    completedUnits = totalChunks + item.combineSeqIdx;
  }

  return clamp01(completedUnits / totalUnits) * 0.7;
}

// C4: deck-wide and batch-scoped progress in one call. `batch` defaults to
// `items` (matching the doc's 2-arg signature exactly -- "whole deck" is
// just the batchSize>=length degenerate case elsewhere in this file too),
// but SessionView passes the actual current batch's items as a 3rd arg so
// `batchFraction` reflects just that batch, not the whole deck.
export function computeSessionProgress(
  items: DrillItem[],
  encodeReps: number,
  batch: DrillItem[] = items
): {
  deckFraction: number;
  batchFraction: number;
  masteredCount: number;
  readyCount: number;
} {
  const average = (list: DrillItem[]): number =>
    list.length ? list.reduce((sum, it) => sum + computeItemProgress(it, encodeReps), 0) / list.length : 0;

  return {
    deckFraction: average(items),
    batchFraction: average(batch),
    masteredCount: items.filter(it => it.status === 'mastered').length,
    readyCount: items.filter(it => it.status === 'ready').length,
  };
}
