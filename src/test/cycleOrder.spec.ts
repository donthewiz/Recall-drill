// Cycle review order ('shuffled' vs 'inOrder') tests.
//   - inOrder walks the batch's cards in deck order (DrillItem.id), even
//     though buildItems shuffled the array within the batch.
//   - inOrder never reinserts mid-pass: a miss (or a first correct) comes
//     back on the next pass, still in deck order.
//   - inOrder is scoped to the current batch like shuffled mode.
//   - shuffled (and undefined, for old saves/configs) keeps the original
//     mid-pass reinsertion.
import { describe, expect, it } from 'vitest';
import { applyAnswer, applyNext, buildItems, initSession, orderCycleQueue } from '../utils/drillEngine';
import type { CycleOrder, DeckItem, SessionState } from '../types';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function makeShortDeck(count: number): DeckItem[] {
  return Array.from({ length: count }, (_, i) => ({ front: `Q${i}`, back: `answer${i}` }));
}

// Starts straight in the cycle phase: every item already 'ready', empty
// queue -- initSession builds the first pass via advanceCycleState.
function cycleState(count: number, batchSize: number, cycleOrder?: CycleOrder): SessionState {
  const items = buildItems(makeShortDeck(count), 35, 'cumulative', batchSize).map(it => ({
    ...it,
    status: 'ready' as const,
  }));
  return initSession({
    items,
    phase: 'cycle',
    queue: [],
    stats: zeroStats,
    currentId: -1,
    batchIndex: 0,
    batchStartStats: zeroStats,
    config: { encodeReps: 1, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative', batchSize, cycleOrder },
  });
}

// Answers the current card (correct unless its id is in `missIds` for this
// visit), advances, and returns the id that was shown.
function step(state: SessionState, miss: boolean): { id: number; next: SessionState } {
  const it = state.items.find(i => i.id === state.currentId)!;
  const res = applyAnswer(state, miss ? 'zzzz wrong' : it.back, { revealed: false });
  return { id: it.id, next: applyNext(res.state) };
}

describe('orderCycleQueue', () => {
  it('inOrder sorts ids ascending without mutating the input', () => {
    const ids = [3, 0, 4, 1, 2];
    expect(orderCycleQueue(ids, 'inOrder')).toEqual([0, 1, 2, 3, 4]);
    expect(ids).toEqual([3, 0, 4, 1, 2]);
  });

  it('shuffled (and default) returns a permutation of the same ids', () => {
    expect([...orderCycleQueue([3, 0, 4, 1, 2], 'shuffled')].sort()).toEqual([0, 1, 2, 3, 4]);
    expect([...orderCycleQueue([3, 0, 4, 1, 2])].sort()).toEqual([0, 1, 2, 3, 4]);
  });
});

describe('inOrder cycle phase', () => {
  it('a perfect run is two full passes in deck order', () => {
    let s = cycleState(5, 5, 'inOrder');
    const seen: number[] = [];
    for (let n = 0; n < 10; n++) {
      const r = step(s, false);
      seen.push(r.id);
      s = r.next;
    }
    expect(seen).toEqual([0, 1, 2, 3, 4, 0, 1, 2, 3, 4]);
    expect(s.items.every(i => i.status === 'mastered')).toBe(true);
  });

  it('a miss does not break order: the card returns on the next pass', () => {
    let s = cycleState(5, 5, 'inOrder');
    const seen: number[] = [];
    // Pass 1: miss card 1. Pass 2: all correct (masters 0,2,3,4; card 1
    // reaches streak 1). Pass 3: only card 1 is left.
    const missOn = new Set([1]);
    for (let n = 0; n < 11; n++) {
      const cur = s.currentId;
      const r = step(s, n < 5 && missOn.has(cur));
      seen.push(r.id);
      s = r.next;
    }
    expect(seen).toEqual([0, 1, 2, 3, 4, 0, 1, 2, 3, 4, 1]);
    expect(s.items.every(i => i.status === 'mastered')).toBe(true);
  });

  it('a revealed answer also waits for the next pass', () => {
    let s = cycleState(4, 4, 'inOrder');
    expect(s.currentId).toBe(0);
    const res = applyAnswer(s, '', { revealed: true });
    expect(res.state.queue).toEqual([1, 2, 3]);
  });

  it('is scoped to the current batch', () => {
    const s = cycleState(8, 5, 'inOrder');
    expect(s.currentId).toBe(0);
    expect(s.queue).toEqual([1, 2, 3, 4]);
  });
});

describe('shuffled cycle phase is unchanged', () => {
  for (const order of ['shuffled', undefined] as const) {
    it(`cycleOrder=${String(order)}: a first correct is reinserted into the current pass`, () => {
      const s = cycleState(5, 5, order);
      const before = s.queue.length;
      const it0 = s.items.find(i => i.id === s.currentId)!;
      const res = applyAnswer(s, it0.back, { revealed: false });
      expect(res.state.queue.length).toBe(before + 1);
      expect(res.state.queue).toContain(it0.id);
    });
  }
});
