// True Phase 0 baseline simulation: drives src/test/reference/legacyEngine.ts
// (a frozen pre-Phase-1 snapshot of the original state machine) instead of
// the current drillEngine.ts, using the exact original (isBlind-based)
// learner models from the very first version of this harness (see
// `git show ccc4514:test/simulate.ts`). This exists so "Phase 0 baseline vs
// final" comparisons run through the SAME seeded/N-run statistical
// machinery on both sides, instead of comparing a live mean/SD against a
// single old unseeded sample frozen in docs/BASELINE.md's git history.
//
// LegacyEngine predates the Cue model (C5), batching (C3), and everything
// else -- its own DriverTrial only ever carries isBlind, never a Cue, so
// this file's LearnerModel is intentionally the old isBlind-shaped one, not
// the Cue-shaped one in simulate.ts. Harness-only; not used by simulate.ts,
// not shipped app code, and LegacyEngine itself must stay untouched (see
// its own file header).
//
// IMPORTANT CAVEAT, found while building this: LegacyEngine is only frozen
// in its OWN hand-transcribed logic (answer/advanceEncode/advanceCycle) --
// it imports low-level helpers (buildItems, chunkText transitively, norm,
// computeWordDiff, findAllCulpritChunks, splitInHalf, culpritHalf, shuffle)
// LIVE from the current drillEngine.ts (deliberately, so B1's fix -- which
// lives in findAllCulpritChunks -- is picked up automatically; see that
// file's own comments). This means a "Phase 0 baseline" run here is NOT
// insulated from changes to those specific shared helpers: a change to
// chunkText's chunking threshold (for example) changes what LegacyEngine
// builds too, silently invalidating the comparison. Always run the Phase 0
// comparison from simulate.report.ts's git history BEFORE making the code
// change you're evaluating, not after -- diffing against a same-run
// "Phase 0" number that already reflects your change proves nothing.
import { DeckItem } from '../src/types';
import { LegacyEngine } from '../src/test/reference/legacyEngine';
import type { SimulationResult } from './simulate';

export type LegacyLearnerModel = {
  pCorrect(attemptIdx: number, isBlind: boolean, priorExposures: number): number;
};

const TYPING_CPS = 4.5;
const PER_TRIAL_OVERHEAD_SEC = 1.5;
const MAX_TRIALS = 20000;

export interface LegacySimConfig {
  encodeReps: number;
  chunkDifficulty?: number;
  // LegacyEngine ignores this (always exhaustive, pre-C1) -- accepted here
  // only so callers can pass the same config shape as simulate() without
  // conditional branching.
  ladderMode?: string;
  stemTolerance?: boolean;
}

export function simulateLegacy(
  deck: DeckItem[],
  config: LegacySimConfig,
  learner: LegacyLearnerModel
): SimulationResult {
  const driver = new LegacyEngine();
  driver.init(deck, { encodeReps: config.encodeReps, chunkDifficulty: config.chunkDifficulty });

  const exposureCounts = new Map<string, number>();
  const trialsByStage: Record<string, number> = {};
  let totalTrials = 0;
  let keystrokes = 0;

  // Unlike selectTrial()/SessionState (which use the SESSION_COMPLETE_ID
  // sentinel), LegacyEngine's currentTrial() keeps re-deriving a trial for
  // the last-answered item even after isFinished() flips true (advanceCycle
  // sets `finished` but never clears `currentId`) -- it was built for the
  // characterization suite's bounded, scripted sequences, not an open-ended
  // loop, so isFinished() must be checked explicitly here or this never
  // terminates.
  while (totalTrials < MAX_TRIALS && !driver.isFinished()) {
    const trial = driver.currentTrial();
    if (!trial) break;

    const key = `${trial.itemId}:${trial.stage}:${trial.target}`;
    const priorExposures = exposureCounts.get(key) ?? 0;
    exposureCounts.set(key, priorExposures + 1);

    const p = learner.pCorrect(priorExposures, trial.isBlind, priorExposures);
    const correct = Math.random() < p;
    const typed = correct ? trial.target : '';

    const result = driver.answer(typed);
    totalTrials++;
    trialsByStage[trial.stage] = (trialsByStage[trial.stage] ?? 0) + 1;
    keystrokes += trial.target.length;

    if (result.advance === 'manual') {
      driver.next();
    }
  }

  if (totalTrials >= MAX_TRIALS) {
    throw new Error(
      `simulateLegacy(): exceeded MAX_TRIALS (${MAX_TRIALS}) without finishing -- likely a non-terminating loop`
    );
  }

  const wallClockEstimate = keystrokes / TYPING_CPS + totalTrials * PER_TRIAL_OVERHEAD_SEC;

  return { totalTrials, trialsByStage, keystrokes, wallClockEstimate, attempts: driver.stats().attempts };
}

// Verbatim from the original test/simulate.ts (git show ccc4514) -- see that
// commit for the "why" commentary this harness inherits unchanged.
export const legacyPerfectLearner: LegacyLearnerModel = {
  pCorrect: () => 1,
};

export const legacyRealisticLearner: LegacyLearnerModel = {
  pCorrect: (_attemptIdx, isBlind, priorExposures) => {
    if (!isBlind) return 1;
    return Math.min(0.95, 0.55 + 0.12 * priorExposures);
  },
};

export const legacyStrugglingLearner: LegacyLearnerModel = {
  pCorrect: (_attemptIdx, isBlind, priorExposures) => {
    if (!isBlind) return 1;
    return Math.min(0.95, 0.3 + 0.08 * priorExposures);
  },
};
