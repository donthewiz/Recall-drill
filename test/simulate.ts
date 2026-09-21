// Trial-count simulation harness, per Part 4 of docs/V2-HANDOFF.md. Drives the
// pure drillEngine.ts reducer with a synthetic learner model instead of a
// human, so the trial-count claims in the handoff doc are measured, not
// assumed. Later phases (C1/C2/C5) diff their own numbers against the
// baseline this produces -- see docs/BASELINE.md.
import { Cue, DeckItem, SessionConfig, SessionState } from '../src/types';
import {
  applyAnswer,
  applyNext,
  buildItems,
  initSession,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../src/utils/drillEngine';

// Phase 4 (C5): the learner model is handed the real Cue instead of a
// blind/not-blind boolean, per Part 4 of docs/V2-HANDOFF.md.
export type LearnerModel = {
  pCorrect(attemptIdx: number, cue: Cue, priorExposures: number): number;
};

export interface SimulationResult {
  totalTrials: number;
  trialsByStage: Record<string, number>;
  keystrokes: number;
  wallClockEstimate: number;
}

// Tunables -- not pinned by the handoff doc, chosen as reasonable estimates
// and documented here so later phases reuse the same assumptions.
const TYPING_CPS = 4.5; // characters per second
const PER_TRIAL_OVERHEAD_SEC = 1.5; // reading the prompt + reaction time

// Safety cap: a real session cannot run forever. If a learner model or a
// state-machine change ever produces a non-terminating loop, fail loudly
// instead of hanging.
const MAX_TRIALS = 20000;

export function simulate(
  deck: DeckItem[],
  config: SessionConfig,
  learner: LearnerModel
): SimulationResult {
  const items = buildItems(deck, config.chunkDifficulty, config.ladderMode);
  let state: SessionState = initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    config,
  });

  // Tracks how many times each distinct stage-unit target has been attempted,
  // so the learner model can improve with repeated exposure.
  const exposureCounts = new Map<string, number>();
  const trialsByStage: Record<string, number> = {};
  let totalTrials = 0;
  let keystrokes = 0;

  while (totalTrials < MAX_TRIALS) {
    const trial = selectTrial(state);
    if (!trial) break;

    const key = `${trial.itemId}:${trial.stage}:${trial.target}`;
    const priorExposures = exposureCounts.get(key) ?? 0;
    exposureCounts.set(key, priorExposures + 1);

    const p = learner.pCorrect(priorExposures, trial.cue, priorExposures);
    const correct = Math.random() < p;
    const typed = correct ? trial.target : '';

    const result = applyAnswer(state, typed, { revealed: false });
    totalTrials++;
    trialsByStage[trial.stage] = (trialsByStage[trial.stage] ?? 0) + 1;
    keystrokes += trial.target.length;

    state = result.state;
    // Phase 4 (C5): a wrong verdict in the encode phase also returns
    // advance: 'manual' now, but the engine state already points at the
    // right trial (same item/stage, streak reset) -- no queue to pop.
    // applyNext is advanceCycleState, so it must only run for the cycle
    // phase's manual advance (see SessionView.tsx's handleNext for the
    // same guard).
    if (result.advance === 'manual' && state.phase === 'cycle') {
      state = applyNext(state);
    }
  }

  if (totalTrials >= MAX_TRIALS) {
    throw new Error(
      `simulate(): exceeded MAX_TRIALS (${MAX_TRIALS}) without finishing -- likely a non-terminating loop`
    );
  }

  const wallClockEstimate = keystrokes / TYPING_CPS + totalTrials * PER_TRIAL_OVERHEAD_SEC;

  return { totalTrials, trialsByStage, keystrokes, wallClockEstimate };
}

// Phase 4 (C5) removed copy-typing: attempt 0 now shows a firstLetter cue
// (first character of each word) rather than the full target, so it's no
// longer modeled as free. These per-cue base rates and increments are
// tunables (not pinned by the handoff doc, same status as TYPING_CPS/
// PER_TRIAL_OVERHEAD_SEC above): firstLetter is modeled as reliably easier
// than a fully blind attempt (a real retrieval cue, not transcription) but
// not free, since the learner still has to produce the rest of the word from
// memory.
export const perfectLearner: LearnerModel = {
  pCorrect: () => 1,
};

export const realisticLearner: LearnerModel = {
  pCorrect: (_attemptIdx, cue, priorExposures) => {
    if (cue.kind === 'firstLetter') return Math.min(0.97, 0.75 + 0.1 * priorExposures);
    return Math.min(0.95, 0.55 + 0.12 * priorExposures);
  },
};

export const strugglingLearner: LearnerModel = {
  pCorrect: (_attemptIdx, cue, priorExposures) => {
    if (cue.kind === 'firstLetter') return Math.min(0.95, 0.5 + 0.08 * priorExposures);
    return Math.min(0.95, 0.3 + 0.08 * priorExposures);
  },
};
