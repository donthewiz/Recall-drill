// Cold-start time estimate shown before a session and recalibrated at each
// batch interstitial.

import {
  DeckItem,
  DrillItem,
  SessionState,
  LadderMode,
} from '../types';
import { MIN_WORDS_TO_CHUNK, partitionIntoBatches, buildItems } from './items';
import { lsGet, lsSet } from './storage';

// ---------------------------------------------------------------------------
// Cold-start time estimate: a floor/ceiling range shown on the setup screen
// before a session starts, then recalibrated from the learner's own
// measured pace at every batch interstitial. Every function below is called
// from SetupView (setup screen) or SessionView's batch interstitial only --
// never from selectTrial/applyAnswer -- so none of this touches the
// per-trial hot path.
//
// Precedence for which multiplier feeds the range: a fresh in-session
// recalibration (computeCumulativeColdStartMultiplier) beats this deck's
// saved personal history (getColdStartHistory), which beats the
// exposure-level self-rating seed (COLD_START_MULTIPLIERS). The three tiers
// are consumed at different times -- before a session starts vs.
// mid-session -- so nothing here enforces the ordering centrally; SetupView
// and SessionView each apply it at their own call site.
// ---------------------------------------------------------------------------

export type ExposureLevel = 'fresh' | 'once' | 'familiar';
export type ColdStartDeckShape = 'chunked' | 'full';

// Seed multipliers: ceiling = floor (perfect-run trial count) x this value.
// Derived from docs/BASELINE.md's Part 4 harness table (test/simulate.ts,
// test/simulate.report.ts -- 50 seeded runs per (deck, learner) config):
//
//   chunked deck -- proseDeck (12 prose cards, chunkDifficulty 35%, avg 3
//   chunks/card), perfect-learner floor 144.0 trials:
//     fresh = struggling/perfect = 762.7 / 144.0 = 5.30
//     once  = realistic/perfect  = 257.9 / 144.0 = 1.79 -> 1.8
//
//   full-stage deck -- shortDeck + mediumDeck averaged (both unchunked,
//   backs <= MIN_WORDS_TO_CHUNK words), perfect-learner floor 60.0 trials
//   each:
//     fresh = struggling/perfect = ((147.7 + 149.4) / 2) / 60.0 = 2.48 -> 2.5
//     once  = realistic/perfect  = (( 91.6 +  92.0) / 2) / 60.0 = 1.53 -> 1.5
//
// The harness models only three learner tiers (perfect/realistic/
// struggling) -- there's no fourth "practiced but not yet perfect" tier to
// measure `familiar` from directly, so it's set as the midpoint between
// `once` and the perfect learner's own ratio of 1.0
// (1 + (once - 1) / 2, rounded to 1 decimal): 1.4 and 1.2 respectively. If
// the harness ever grows a fourth tier, re-derive `familiar` from it
// directly instead of this interpolation.
export const COLD_START_MULTIPLIERS: Record<ColdStartDeckShape, Record<ExposureLevel, number>> = {
  chunked: { fresh: 5.3, once: 1.8, familiar: 1.4 },
  full: { fresh: 2.5, once: 1.5, familiar: 1.2 },
};

// Picks the multiplier row by the deck's actual composition -- share of
// cards whose back exceeds MIN_WORDS_TO_CHUNK -- never by a user setting
// like chunkDifficulty (a deck's shape doesn't change just because the
// difficulty slider moved).
export function pickColdStartDeckShape(items: DeckItem[]): ColdStartDeckShape {
  if (!items.length) return 'full';
  const chunkableCount = items.filter(
    it => it.back.trim().split(/\s+/).filter(Boolean).length > MIN_WORDS_TO_CHUNK
  ).length;
  return chunkableCount / items.length > 0.5 ? 'chunked' : 'full';
}

// Floor of the estimate: the minimum possible value of state.stats.attempts
// (the same counter SessionView's status bar shows as "Attempts") assuming
// a perfect learner (every graded attempt correct first try). Deliberately
// NOT the same as test/simulate.ts's `totalTrials` -- that harness counter
// also counts a chunks-stage presentation (C8b: cue 'present', attempt 0 of
// a chunk) as a trial, but applyAnswer's isPresentation branch skips
// incrementing `attempts` for it (nothing was graded), so it must be
// excluded here too for computeCumulativeColdStartMultiplier's actual/floor
// ratio to land on 1.0 for a perfect learner. Cross-checked against
// docs/BASELINE.md's perfect-learner rows once that gap is accounted for:
// shortDeck/mediumDeck's floor (72, post-Phase-3) matches BASELINE.md's
// total trials exactly (they have no presentations to subtract); proseDeck's
// floor is 120, i.e. BASELINE.md's 156 minus one presentation per chunk (3
// chunks/card x 12 cards = 36, never repeated for a perfect learner since
// presentations only recur after a miss).
//
// Every item needs exactly 2 cycle-phase trials to reach `mastered`
// (cycleStreak >= 2, and a perfect learner's streak only ever goes up), plus
// (Phase 3) exactly 1 Final-check trial; chunked items additionally need
// exactly 1 graded (blind) trial per chunk (C8a's cued attempt 0 is the
// presentation excluded above) plus the combine ladder's cost (see
// requiredRepsForWindow); unchunked items just need `encodeReps` on their
// single ladder rung.
//
// includeFinalCheck defaults to true for every forward-looking caller
// (computeColdStartEstimate, computeRemainingColdStartRange, tests) --
// every session eventually runs exactly one Final-check trial per item, so
// the floor should always reflect that total. computeCumulativeColdStartMultiplier
// is the one caller that passes false, deliberately: see its own doc comment
// for why the Final check's cost can't be credited to the floor before it
// has actually run.
export function computeMinimumTrials(
  items: DrillItem[],
  encodeReps: number,
  ladderMode: LadderMode = 'cumulative',
  includeFinalCheck: boolean = true
): number {
  let total = 0;
  for (const item of items) {
    if (item.chunks && item.combineSeq) {
      total += item.chunks.length;
      if (ladderMode === 'cumulative') {
        total += Math.max(0, item.combineSeq.length - 1) + encodeReps;
      } else {
        total += item.combineSeq.length * encodeReps;
      }
    } else {
      total += encodeReps;
    }
    total += 2; // cycle: exactly 2 corrects to reach mastered
    if (includeFinalCheck) total += 1; // Phase 3: one Final-check answer
  }
  return total;
}

// Tunables mirroring test/simulate.ts's wallClockEstimate constants,
// duplicated here (not imported) since that module is test-only -- not
// worth promoting the whole harness into production code for two numbers.
const COLD_START_TYPING_CPS = 4.5;
const COLD_START_PER_TRIAL_OVERHEAD_SEC = 1.5;

export function estimateColdStartSeconds(trials: number, items: { back: string }[]): number {
  const avgChars = items.length
    ? items.reduce((sum, it) => sum + it.back.length, 0) / items.length
    : 20;
  return trials * (avgChars / COLD_START_TYPING_CPS + COLD_START_PER_TRIAL_OVERHEAD_SEC);
}

function formatColdStartMinutes(seconds: number): string {
  const mins = seconds / 60;
  if (mins < 1) return '<1';
  return String(Math.round(mins));
}

// Shared by SetupView's estimate and SessionView's recalibrated interstitial
// range -- collapses the two degenerate cases a plain "~{floor}-{ceiling}
// min" template mishandles: both ends under a minute (was rendering the
// useless "~<1-<1 min") and ends that round to the same minute value, e.g.
// a multiplier of 1 (was rendering the equally useless "~12-12 min").
export function formatColdStartRange(floorSeconds: number, ceilingSeconds: number): string {
  const low = formatColdStartMinutes(floorSeconds);
  const high = formatColdStartMinutes(ceilingSeconds);
  if (low === '<1' && high === '<1') return 'under a minute';
  if (low === high) return `~${low} min`;
  return `~${low}–${high} min`;
}

export interface ColdStartEstimate {
  floorTrials: number;
  ceilingTrials: number;
  floorSeconds: number;
  ceilingSeconds: number;
  multiplier: number;
  deckShape: ColdStartDeckShape;
}

// Setup-screen estimate: floor from perfect-run math, ceiling = floor x the
// resolved multiplier (a personal-history override when one exists,
// otherwise the exposure-level seed row -- see COLD_START_MULTIPLIERS and
// getColdStartHistory below).
export function computeColdStartEstimate(
  deckItems: DeckItem[],
  encodeReps: number,
  chunkDifficulty: number,
  ladderMode: LadderMode,
  multiplierOverride: number | ExposureLevel
): ColdStartEstimate {
  const deckShape = pickColdStartDeckShape(deckItems);
  const built = buildItems(deckItems, chunkDifficulty, ladderMode);
  const floorTrials = computeMinimumTrials(built, encodeReps, ladderMode);
  const multiplier =
    typeof multiplierOverride === 'number'
      ? multiplierOverride
      : COLD_START_MULTIPLIERS[deckShape][multiplierOverride];
  const ceilingTrials = Math.round(floorTrials * multiplier);
  return {
    floorTrials,
    ceilingTrials,
    floorSeconds: estimateColdStartSeconds(floorTrials, deckItems),
    ceilingSeconds: estimateColdStartSeconds(ceilingTrials, deckItems),
    multiplier,
    deckShape,
  };
}

// Personal history: the multiplier measured from this deck's most recent
// session (see computeCumulativeColdStartMultiplier), one entry per deck
// slug. Read by SetupView the next time this deck is set up, in place of
// the exposure-picker seed -- see the module-level precedence note above.
export interface ColdStartHistory {
  multiplier: number;
  deckShape: ColdStartDeckShape;
  measuredAt: string;
}

export function getColdStartHistory(slug: string): ColdStartHistory | null {
  if (!slug) return null;
  return lsGet<ColdStartHistory>(`cold-start-history:${slug}`);
}

export function saveColdStartHistory(slug: string, history: ColdStartHistory): boolean {
  if (!slug) return false;
  return lsSet(`cold-start-history:${slug}`, history);
}

// In-session recalibration: this deck's actual trials / perfect-run minimum
// trials, summed across every batch FULLY completed so far this session --
// not just the batch most recently finished. A batch only ever completes in
// order (batchIndex only advances once every item in it is 'mastered'), so
// "completed" is exactly batches[0..batchIndex] when the batch AT
// batchIndex is itself fully mastered (true at the batch-done interstitial,
// and true of every batch once the whole session finishes, even though the
// last batch skips the interstitial -- see advanceBatchState), and
// batches[0..batchIndex-1] otherwise (mid-batch, e.g. the learner hits "End
// session" partway through). state.batchStartStats.attempts -- the
// attempts total as of the current batch's own start -- gives the attempts
// spent on those prior batches in the mid-batch case, since nothing else
// has touched `attempts` since; state.stats.attempts (the live running
// total) is only correct once the current batch is itself done, because at
// that instant no later batch has started consuming attempts yet.
//
// Returns null when no batch has been completed yet (nothing measured),
// rather than defaulting to a placeholder multiplier that would silently
// look like a real measurement to a caller that doesn't check for it.
//
// Called at every batch interstitial (SessionView renders the remaining
// range from this) and once more whenever a session ends (SessionView
// persists the result via saveColdStartHistory for future setup screens) --
// never mid-trial, so it stays out of the per-trial hot path either way.
//
// Phase 3: the Final check is a whole-session pass (one trial per item,
// entered only after the LAST batch's own cycle finishes -- see
// advanceBatchState), not a per-batch cost, so computeMinimumTrials'
// +1-per-item floor for it must not be credited here until the Final check
// has actually finished for every item -- crediting it any earlier would
// inflate the denominator (floor) against a numerator (completedAttempts)
// that hasn't spent those trials yet, understating the multiplier. The
// numerator needs the matching exclusion: while phase is 'final' but
// finalCheckDone is still false, completedAttempts must leave OUT whatever
// Final-check attempts have already been spent so far (state.stats.attempts
// keeps growing with every Final-check trial, correct or not), or the
// numerator would count trials the denominator doesn't -- state was
// snapshotted into finalCheckStartAttempts at the exact instant the Final
// check began (see advanceBatchState) for exactly this. Once every item is
// finalDone, `completedItems` is necessarily the WHOLE deck (the Final
// check can't start before the last batch does), so
// state.stats.attempts / includeFinalCheck: true both correctly cover
// every trial, Final check included.
export function computeCumulativeColdStartMultiplier(state: SessionState): number | null {
  const effectiveBatchSize = state.config.batchSize ?? state.items.length;
  const batches = partitionIntoBatches(state.items, effectiveBatchSize);
  const currentBatch = batches[state.batchIndex] ?? [];
  const currentBatchDone = currentBatch.length > 0 && currentBatch.every(it => it.status === 'mastered');
  const completedThroughIdx = currentBatchDone ? state.batchIndex : state.batchIndex - 1;
  if (completedThroughIdx < 0) return null;

  const completedItems = batches.slice(0, completedThroughIdx + 1).flat();
  const finalCheckDone = state.items.length > 0 && state.items.every(it => it.finalDone);
  const minTrials = computeMinimumTrials(
    completedItems,
    state.config.encodeReps,
    state.config.ladderMode,
    finalCheckDone
  );
  const completedAttempts =
    state.phase === 'final'
      ? finalCheckDone
        ? state.stats.attempts
        : state.finalCheckStartAttempts ?? state.stats.attempts
      : currentBatchDone
      ? state.stats.attempts
      : state.batchStartStats.attempts;
  return minTrials > 0 ? completedAttempts / minTrials : null;
}

// Recomputes the floor/ceiling range for whatever batches remain after the
// one currently shown on the interstitial, using a caller-supplied
// multiplier (the recalibrated one, once available).
export function computeRemainingColdStartRange(
  state: SessionState,
  multiplier: number
): { floorTrials: number; ceilingTrials: number; floorSeconds: number; ceilingSeconds: number } {
  const effectiveBatchSize = state.config.batchSize ?? state.items.length;
  const batches = partitionIntoBatches(state.items, effectiveBatchSize);
  const remainingItems = batches.slice(state.batchIndex + 1).flat();
  const floorTrials = computeMinimumTrials(remainingItems, state.config.encodeReps, state.config.ladderMode);
  const ceilingTrials = Math.round(floorTrials * multiplier);
  return {
    floorTrials,
    ceilingTrials,
    floorSeconds: estimateColdStartSeconds(floorTrials, remainingItems),
    ceilingSeconds: estimateColdStartSeconds(ceilingTrials, remainingItems),
  };
}
