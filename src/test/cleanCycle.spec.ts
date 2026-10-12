// A clean card masters the cycle with one correct answer (2026-10-12).
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  computeItemProgress,
  cycleRepsToMaster,
  editCurrentItem,
  initSession,
  selectTrial,
} from '../utils/drillEngine';
import type { DrillItem, SessionState } from '../types';

const zero = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

// Two short cards, both 'ready', starting in the cycle (in deck order).
function cycle(encodeReps = 1, patch: Partial<DrillItem> = {}): SessionState {
  const items = buildItems(
    [
      { front: 'heart', back: 'cardi' },
      { front: 'liver', back: 'hepat' },
    ],
    35,
    'cumulative',
    undefined,
    8,
    false
  ).map(i => ({ ...i, status: 'ready' as const, ...(i.id === 0 ? patch : {}) }));
  return initSession({
    items,
    phase: 'cycle',
    queue: [],
    stats: { ...zero },
    currentId: -1,
    batchIndex: 0,
    batchStartStats: { ...zero },
    config: { encodeReps, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative', cycleOrder: 'inOrder' },
  });
}

const card0 = (s: SessionState) => s.items.find(i => i.id === 0)!;

describe('cycleRepsToMaster', () => {
  it('is 1 with no miss and no reveal, else 2; near misses do not count', () => {
    expect(cycleRepsToMaster({})).toBe(1);
    expect(cycleRepsToMaster({ misses: 0, reveals: 0, nearMisses: 3 } as DrillItem)).toBe(1);
    expect(cycleRepsToMaster({ misses: 1 })).toBe(2);
    expect(cycleRepsToMaster({ reveals: 1 })).toBe(2);
  });
});

describe('the cycle', () => {
  for (const encodeReps of [1, 3]) {
    it(`a clean card is mastered by one correct answer (encodeReps ${encodeReps}), with the "Mastered" text`, () => {
      const r = applyAnswer(cycle(encodeReps), 'cardi', { revealed: false });
      expect(card0(r.state).status).toBe('mastered');
      expect(r.feedback.text).toBe('Mastered! Item retired.');
      expect(r.state.queue).toEqual([1]);
    });
  }

  it('a near answer masters a clean card too', () => {
    const s = cycle(1, { back: 'the heart part', front: 'h' });
    const r = applyAnswer(s, 'heart part', { revealed: false });
    expect(r.verdict).toBe('near');
    expect(card0(r.state).status).toBe('mastered');
  });

  it('a card with a miss or a reveal needs 2 in a row, as before', () => {
    for (const patch of [{ misses: 1 }, { reveals: 1 }]) {
      const r = applyAnswer(cycle(1, patch), 'cardi', { revealed: false });
      expect(card0(r.state).status).toBe('ready');
      expect(card0(r.state).cycleStreak).toBe(1);
      expect(r.feedback.text).toBe('Correct — will test once more later in the session.');
    }
  });

  it('a miss in the cycle makes the card need 2', () => {
    let s = applyNext(applyAnswer(cycle(), 'zzz', { revealed: false }).state);
    while (s.currentId !== 0) s = applyNext(applyAnswer(s, selectTrial(s)!.target, { revealed: false }).state);
    s = applyAnswer(s, 'cardi', { revealed: false }).state;
    expect(card0(s).status).toBe('ready');
  });

  it('"Count as correct" keeps the card clean (its miss is never recorded)', () => {
    const pre = cycle();
    const wrong = applyAnswer(pre, 'zzz', { revealed: false });
    expect(card0(wrong.state).misses).toBe(1);
    const override = applyAnswer(pre, 'cardi', { revealed: false, override: true });
    expect(card0(override.state).misses).toBe(0);
    expect(card0(override.state).status).toBe('mastered');
  });

  it('an edit that restarts a card resets its counters, so it is clean again', () => {
    const s = cycle(1, { misses: 2, reveals: 1 });
    const { state, restarted } = editCurrentItem(s, { front: 'heart', back: 'cardio' });
    expect(restarted).toBe(true);
    expect(cycleRepsToMaster(card0(state))).toBe(1);
  });

  it('the Final check is unchanged: one correct answer each', () => {
    let s = cycle();
    for (let n = 0; n < 2; n++) s = applyNext(applyAnswer(s, selectTrial(s)!.target, { revealed: false }).state);
    expect(s.phase).toBe('final');
    const r = applyAnswer(s, selectTrial(s)!.target, { revealed: false });
    expect(r.state.items.find(i => i.id === selectTrial(s)!.itemId)!.finalDone).toBe(true);
    expect(r.advance).toBe('manual');
  });
});

describe('progress', () => {
  it("counts a ready card's cycle: 1 needed when clean, 2 otherwise", () => {
    const base = cycle().items[0];
    expect(computeItemProgress({ ...base, cycleStreak: 0 }, 1)).toBeCloseTo(0.7);
    expect(computeItemProgress({ ...base, cycleStreak: 1, misses: 1 }, 1)).toBeCloseTo(0.85);
    // A miss resets the streak and makes the card need 2: progress drops.
    expect(computeItemProgress({ ...base, cycleStreak: 0, misses: 2 }, 1)).toBeCloseTo(0.7);
  });
});
