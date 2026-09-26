// Chain contiguity (2026-09-26): a chunked card stays current while its
// answer is being assembled -- every chunk, every intermediate combine
// window, and any remediation run back to back. Rotation to another batch
// card resumes only after a correct answer on the final (whole-answer)
// combine window. Full-stage cards still rotate after every correct rep
// (Phase 2, unchanged).
import { describe, expect, it } from 'vitest';
import { applyAnswer, buildItems, initSession, selectTrial } from '../utils/drillEngine';
import type { DeckItem, LadderMode, SessionState, Trial } from '../types';
import { CHUNK_DIFFICULTY, FOUR_CHUNK_BACK } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };
const ENCODE_REPS = 3;

function freshState(items: SessionState['items'], ladderMode: LadderMode): SessionState {
  return initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: -1,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: {
      encodeReps: ENCODE_REPS,
      chunkDifficulty: CHUNK_DIFFICULTY,
      stemTolerance: true,
      ladderMode,
    },
  });
}

const encodingCount = (state: SessionState) =>
  state.items.filter(i => i.status !== 'ready' && i.status !== 'mastered').length;

interface Step {
  trial: Trial;
  // encodingCount after this trial's answer was applied
  encodingAfter: number;
}

// Runs the encode phase to completion (whole-deck batch, deck order),
// answering every trial correctly except where `answerFor` returns an
// override string.
function runEncode(
  deck: DeckItem[],
  ladderMode: LadderMode,
  answerFor: (trial: Trial, s: SessionState) => string | undefined = () => undefined
): { steps: Step[]; ids: number[] } {
  const items = buildItems(deck, CHUNK_DIFFICULTY, ladderMode, undefined, undefined, false);
  let s = freshState(items, ladderMode);
  const steps: Step[] = [];
  let guard = 0;
  while (s.phase === 'encode') {
    expect(guard++).toBeLessThan(500);
    const trial = selectTrial(s)!;
    const typed = answerFor(trial, s) ?? (trial.cue.kind === 'present' ? '' : trial.target);
    s = applyAnswer(s, typed, { revealed: false }).state;
    steps.push({ trial, encodingAfter: encodingCount(s) });
  }
  expect(s.items.every(i => i.status === 'ready')).toBe(true);
  return { steps, ids: items.map(i => i.id) };
}

const LONG_DECK: DeckItem[] = [
  { front: 'Short A', back: 'answer alpha' },
  { front: 'Trees', back: FOUR_CHUNK_BACK },
  { front: 'Short B', back: 'answer beta' },
];

// From the long card's first trial through its first final-window trial,
// every trial is the long card; after that final-window correct rep, the
// next trial is a different card while more than one card is still encoding.
function assertContiguous(steps: Step[], longId: number) {
  const first = steps.findIndex(st => st.trial.itemId === longId);
  const firstFinal = steps.findIndex(
    st => st.trial.itemId === longId && st.trial.stage === 'combine' && st.trial.target === FOUR_CHUNK_BACK
  );
  expect(first).toBeGreaterThanOrEqual(0);
  expect(firstFinal).toBeGreaterThan(first);
  for (let i = first; i <= firstFinal; i++) {
    expect(steps[i].trial.itemId).toBe(longId);
  }
  expect(steps[firstFinal].encodingAfter).toBeGreaterThan(1);
  expect(steps[firstFinal + 1].trial.itemId).not.toBe(longId);
  return { first, firstFinal };
}

describe('Chain contiguity: a chunked card stays on screen until its whole answer is assembled', () => {
  it('cumulative ladder: chunks and intermediate windows run back to back, then the final window rotates', () => {
    const { steps, ids } = runEncode(LONG_DECK, 'cumulative');
    assertContiguous(steps, ids[1]);
  });

  it('exhaustive ladder: short-of-criterion reps on intermediate windows stay on the card too', () => {
    const { steps, ids } = runEncode(LONG_DECK, 'exhaustive');
    const { first, firstFinal } = assertContiguous(steps, ids[1]);
    // Sanity: exhaustive mode actually produced repeated intermediate-window
    // reps inside the contiguous run (encodeReps per window).
    const combineIntermediate = steps
      .slice(first, firstFinal)
      .filter(st => st.trial.stage === 'combine');
    expect(combineIntermediate.length).toBeGreaterThanOrEqual(ENCODE_REPS * 5);
  });

  it('remediation stays on the card and contiguity holds up to the final window', () => {
    const longIdx = 1;
    let missed = false;
    const { steps, ids } = runEncode(LONG_DECK, 'cumulative', (trial, s) => {
      if (!missed && trial.itemId === s.items[longIdx].id && trial.stage === 'combine') {
        missed = true;
        return 'large green trees';
      }
      return undefined;
    });
    expect(missed).toBe(true);
    const longId = ids[longIdx];
    const remediationTrials = steps.filter(st => st.trial.itemId === longId && st.trial.stage === 'remediate');
    expect(remediationTrials.length).toBeGreaterThan(0);
    const { firstFinal } = assertContiguous(steps, longId);
    // Every remediation trial falls inside the contiguous run.
    const lastRemediate = steps.map(st => st.trial.stage).lastIndexOf('remediate');
    expect(lastRemediate).toBeLessThan(firstFinal);
  });

  it('full-stage only: consecutive graded trials alternate cards while more than one is encoding (Phase 2 unchanged)', () => {
    const deck: DeckItem[] = [
      { front: 'Short A', back: 'answer alpha' },
      { front: 'Short B', back: 'answer beta' },
    ];
    const { steps } = runEncode(deck, 'cumulative');
    for (let i = 1; i < steps.length; i++) {
      if (steps[i - 1].encodingAfter > 1) {
        expect(steps[i].trial.itemId).not.toBe(steps[i - 1].trial.itemId);
      }
    }
  });
});
