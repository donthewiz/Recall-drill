// C8b (presentation trial replaces the cued chunk attempt, part 2) tests.
// Doc acceptance criteria:
//   the chunks stage never shows a graded typing attempt with the full
//   answer already visible -- attempt 0 is a pure read, attempt 1 is the
//   first real retrieval attempt. A presentation trial never appears in
//   stats.attempts, stats.misses, or a diff.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  initSession,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import { simulate, perfectLearner } from '../../test/simulate';
import type { SessionState } from '../types';
import { TWO_CHUNK_BACK, TWO_CHUNK_CHUNKS, TWO_CHUNK_DIFFICULTY } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function freshState(): SessionState {
  return initSession({
    items: buildItems([{ front: 'Q', back: TWO_CHUNK_BACK }], TWO_CHUNK_DIFFICULTY),
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps: 2, chunkDifficulty: TWO_CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
  });
}

describe('C8b: selectTrial produces a presentation cue for a fresh chunk', () => {
  it('cue is { kind: "present" } with no payload -- the text to show is Trial.target', () => {
    const state = freshState();
    const trial = selectTrial(state)!;
    expect(trial.stage).toBe('chunks');
    expect(trial.cue).toEqual({ kind: 'present' });
    expect(trial.target).toBe(TWO_CHUNK_CHUNKS[0]);
  });
});

describe('C8b: a presentation trial is acknowledged, not graded', () => {
  it('advances chunkStreak from 0 to 1 regardless of what is "typed", never counts as an attempt or a miss', () => {
    const state = freshState();

    for (const typed of ['', 'anything', 'nonsense that would fail grading']) {
      const result = applyAnswer(state, typed, { revealed: false });
      expect(result.verdict).toBe('presented');
      expect(result.advance).toBe('auto');
      expect(result.feedback.diff).toBeUndefined(); // never a diff -- nothing was graded
      expect(result.state.stats).toEqual(zeroStats); // not counted as an attempt, never a miss
      const it = result.state.items.find(i => i.id === result.state.currentId)!;
      expect(it.chunkIndex).toBe(0); // never advances the chunk by itself
      expect(it.chunkStreak).toBe(1);
    }
  });

  it('the subsequent blind attempt (chunkStreak 1) is the first one that can actually be wrong', () => {
    let state = freshState();
    state = applyAnswer(state, 'anything', { revealed: false }).state; // acknowledge presentation

    const result = applyAnswer(state, 'nonsense', { revealed: false });
    expect(result.verdict).toBe('wrong');
    expect(result.state.stats.attempts).toBe(1);
    expect(result.state.stats.misses).toBe(1);
    expect(result.feedback.diff).toBeDefined();
  });
});

describe('C8b: test/simulate.ts counts a presentation trial toward wall clock but not keystrokes', () => {
  const deck = [{ front: 'Q', back: TWO_CHUNK_BACK }];
  const config = { encodeReps: 2, chunkDifficulty: TWO_CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' as const };

  it('trialsByStage.chunks counts both the presentation and the blind attempt for each chunk', () => {
    const result = simulate(deck, config, perfectLearner);
    // 2 chunks x (1 presentation + 1 blind) = 4 chunk trials, regardless of
    // encodeReps (C8a) -- both halves of each pair count as trials.
    expect(result.trialsByStage.chunks).toBe(4);
  });

  it("simulate()'s total keystrokes exactly match a hand-walked session that skips presentation trials", () => {
    // Independently walks the same deck/config with a perfect (always
    // correct) learner via the raw engine, summing keystrokes the same way
    // simulate.ts does (trial.target.length, except cue 'present' -> 0), so
    // this doesn't just re-assert simulate.ts's own formula against itself.
    let state: SessionState = initSession({
      items: buildItems(deck, config.chunkDifficulty, config.ladderMode),
      phase: 'encode',
      queue: [],
      stats: { ...zeroStats },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { ...zeroStats },
      config,
    });

    let expectedKeystrokes = 0;
    for (let i = 0; i < 200 && state.currentId !== SESSION_COMPLETE_ID; i++) {
      const trial = selectTrial(state);
      if (!trial) break;
      if (trial.cue.kind !== 'present') expectedKeystrokes += trial.target.length;
      const result = applyAnswer(state, trial.target, { revealed: false });
      state = result.state;
      if (result.advance === 'manual' && state.phase === 'cycle') {
        state = applyNext(state);
      }
    }

    const simResult = simulate(deck, config, perfectLearner);
    expect(simResult.keystrokes).toBe(expectedKeystrokes);
    expect(expectedKeystrokes).toBeGreaterThan(0); // sanity: the test isn't vacuously comparing 0 to 0
  });
});
