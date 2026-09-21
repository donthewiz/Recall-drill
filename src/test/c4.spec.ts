// C4 (honest progress display) tests. Doc acceptance criteria:
//   - progress is strictly monotonic across a simulated session (never
//     decreases).
//   - starts > 0 after the first correct chunk.
//   - reaches exactly 1.0 only when all items are mastered.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  computeItemProgress,
  computeSessionProgress,
  initSession,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { DrillItem, SessionState } from '../types';
import { FOUR_CHUNK_BACK, FOUR_CHUNK_CHUNKS, CHUNK_DIFFICULTY } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function freshState(items: DrillItem[], encodeReps = 2): SessionState {
  return initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
  });
}

describe('computeItemProgress', () => {
  it('new is 0, ready is 0.7, mastered is 1.0', () => {
    const [item] = buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY);
    expect(computeItemProgress(item, 2)).toBe(0);
    expect(computeItemProgress({ ...item, status: 'ready' }, 2)).toBe(0.7);
    expect(computeItemProgress({ ...item, status: 'mastered' }, 2)).toBe(1);
  });

  it('encoding: chunk progress falls strictly between 0 and 0.7 and grows with chunkIndex/chunkStreak', () => {
    const [item] = buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY);
    const encoding = { ...item, status: 'encoding' as const };

    const atStart = computeItemProgress(encoding, 2);
    const oneChunkStreaking = computeItemProgress({ ...encoding, chunkStreak: 1 }, 2);
    const oneChunkDone = computeItemProgress({ ...encoding, chunkIndex: 1 }, 2);
    const twoChunksDone = computeItemProgress({ ...encoding, chunkIndex: 2 }, 2);

    expect(atStart).toBe(0);
    expect(oneChunkStreaking).toBeGreaterThan(atStart);
    expect(oneChunkDone).toBeGreaterThan(oneChunkStreaking);
    expect(twoChunksDone).toBeGreaterThan(oneChunkDone);
    expect(twoChunksDone).toBeLessThan(0.7);
  });

  it('encoding: combine-stage progress picks up where the chunks left off (all chunks pre-credited)', () => {
    const [item] = buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY);
    const justFinishedChunks = { ...item, status: 'encoding' as const, chunkIndex: 4, chunkStreak: 0 };
    const enteredCombine = {
      ...justFinishedChunks,
      stage: 'combine' as const,
      combineSeqIdx: 0,
      combineStreak: 0,
    };
    // Both represent "all 4 chunks done, 0 combine windows done" -- should
    // read the same regardless of which stage label is currently active.
    expect(computeItemProgress(enteredCombine, 2)).toBeCloseTo(computeItemProgress(justFinishedChunks, 2), 10);

    const midCombine = { ...enteredCombine, combineSeqIdx: 2 };
    expect(computeItemProgress(midCombine, 2)).toBeGreaterThan(computeItemProgress(enteredCombine, 2));
  });

  it("encoding: remediate holds progress flat at the combine window it interrupted (doesn't dip)", () => {
    const [item] = buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY);
    const midCombine = {
      ...item,
      status: 'encoding' as const,
      chunkIndex: 4,
      stage: 'combine' as const,
      combineSeqIdx: 1,
      combineStreak: 0, // a miss resets this to 0 before remediate is entered
    };
    const nowRemediating = { ...midCombine, stage: 'remediate' as const };
    expect(computeItemProgress(nowRemediating, 2)).toBe(computeItemProgress(midCombine, 2));
  });
});

describe('computeSessionProgress', () => {
  it('deckFraction averages every item; batchFraction averages only the given subset', () => {
    const items = buildItems(
      [
        { front: 'Q1', back: FOUR_CHUNK_BACK },
        { front: 'Q2', back: FOUR_CHUNK_BACK },
      ],
      CHUNK_DIFFICULTY
    );
    const mastered = { ...items[0], status: 'mastered' as const };
    const fresh = { ...items[1], status: 'new' as const };
    const both = [mastered, fresh];

    expect(computeSessionProgress(both, 2).deckFraction).toBeCloseTo(0.5, 10);
    expect(computeSessionProgress(both, 2, [mastered]).batchFraction).toBe(1);
    expect(computeSessionProgress(both, 2, [fresh]).batchFraction).toBe(0);
    expect(computeSessionProgress(both, 2).masteredCount).toBe(1);
  });

  it('defaults batch to the full item list when omitted (matches the doc\'s 2-arg signature)', () => {
    const items = buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY);
    const result = computeSessionProgress(items, 2);
    expect(result.batchFraction).toBe(result.deckFraction);
  });
});

describe('C4 acceptance: progress over a full perfect-learner session', () => {
  it('never decreases, starts > 0 after the first correct chunk, and reaches exactly 1.0 only once every item is mastered', () => {
    let state = freshState(buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY, 'cumulative'));

    const readings: number[] = [computeSessionProgress(state.items, state.config.encodeReps).deckFraction];
    expect(readings[0]).toBe(0);

    for (let i = 0; i < 500 && state.currentId !== SESSION_COMPLETE_ID; i++) {
      const it = state.items.find(x => x.id === state.currentId);
      if (!it) break;

      let target: string;
      if (state.phase === 'cycle') {
        target = it.back;
      } else if (it.stage === 'chunks' && it.chunks) {
        target = it.chunks[it.chunkIndex];
      } else if (it.stage === 'combine' && it.chunks && it.combineSeq) {
        const seq = it.combineSeq[it.combineSeqIdx];
        target = it.chunks.slice(seq.start - 1, seq.end).join(' ');
      } else {
        target = FOUR_CHUNK_BACK;
      }

      const result = applyAnswer(state, target, { revealed: false });
      state = result.state;
      if (result.advance === 'manual' && state.phase === 'cycle') {
        state = applyNext(state);
      }
      readings.push(computeSessionProgress(state.items, state.config.encodeReps).deckFraction);
    }

    // First correct chunk answer is readings[1] -- must be > 0.
    expect(readings[1]).toBeGreaterThan(0);

    for (let i = 1; i < readings.length; i++) {
      expect(readings[i]).toBeGreaterThanOrEqual(readings[i - 1]);
    }

    expect(readings[readings.length - 1]).toBe(1);
    expect(state.items.every(it => it.status === 'mastered')).toBe(true);

    // 1.0 is reached only at the very end -- every earlier reading is < 1.
    for (let i = 0; i < readings.length - 1; i++) {
      expect(readings[i]).toBeLessThan(1);
    }
  });
});
