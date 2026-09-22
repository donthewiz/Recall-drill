// editCurrentItem: mid-session edit of the card being drilled. Rules:
//   - answer not really changed (exactMatch under the deck's punctuation
//     mode) -> progress kept, text/chunks swapped -- unless the chunk count
//     changes or the item is in 'remediate', which restart instead.
//   - answer really changed -> the card restarts from scratch at its id;
//     from 'cycle' that drops back to 'encode' with an empty queue.
//   - stats are never touched; the input is never mutated.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  advanceToNextBatch,
  buildItems,
  editCurrentItem,
  initSession,
  selectNextEncodeItem,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { CycleOrder, DeckItem, DrillItem, SessionState } from '../types';
import { CHUNK_DIFFICULTY, FOUR_CHUNK_BACK } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

const deck: DeckItem[] = [
  { front: 'Tachycardia', back: 'fast heart rate' },
  { front: 'Inner ear disorder', back: 'Menieres disease' },
  { front: 'Before surgery', back: 'pre op' },
  { front: 'Describe where the trees grow', back: FOUR_CHUNK_BACK },
];
const TACHY = 0;
const MENIERES = 1;
const PRE_OP = 2;
const TREES = 3;

function freshState(
  opts: { encodeReps?: number; strict?: boolean; cycleOrder?: CycleOrder; batchSize?: number } = {}
): SessionState {
  return initSession({
    items: buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', opts.batchSize, undefined, false),
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: {
      encodeReps: opts.encodeReps ?? 3,
      chunkDifficulty: CHUNK_DIFFICULTY,
      stemTolerance: true,
      ladderMode: 'cumulative',
      cycleOrder: opts.cycleOrder,
      batchSize: opts.batchSize,
      strictPunctuation: opts.strict,
    },
  });
}

const itemOf = (state: SessionState, id: number): DrillItem => state.items.find(i => i.id === id)!;

// One correct step: acknowledges a presentation, types the target otherwise,
// and moves past cycle feedback / batch interstitials the way the shell does.
function step(state: SessionState): SessionState {
  if (state.phase === 'batch-done') return advanceToNextBatch(state);
  const trial = selectTrial(state)!;
  const typed = trial.cue.kind === 'present' ? '' : trial.target;
  const next = applyAnswer(state, typed, { revealed: false }).state;
  return state.phase === 'cycle' ? applyNext(next) : next;
}

function stepUntil(state: SessionState, done: (s: SessionState) => boolean): SessionState {
  let s = state;
  for (let guard = 0; !done(s); guard++) {
    if (guard > 1000) throw new Error('stepUntil: condition never reached');
    if (!selectTrial(s) && s.phase !== 'batch-done') throw new Error('stepUntil: session ended first');
    s = step(s);
  }
  return s;
}

// Progress fields -- everything on a DrillItem except its text.
function progressOf(item: DrillItem) {
  const { front: _f, back: _b, chunks: _c, ...rest } = item;
  return rest;
}

function deepFreeze<T>(obj: T): T {
  if (obj && typeof obj === 'object' && !Object.isFrozen(obj)) {
    Object.freeze(obj);
    for (const v of Object.values(obj)) deepFreeze(v);
  }
  return obj;
}

const onItem = (id: number) => (s: SessionState) => s.currentId === id;

describe('editCurrentItem -- progress kept', () => {
  it('a prompt-only edit keeps every progress field', () => {
    // Mid-streak on a full-stage card: one correct answer in, two to go.
    const s0 = step(stepUntil(freshState(), onItem(TACHY)));
    expect(itemOf(s0, TACHY).encodeStreak).toBe(1);

    const { state, restarted } = editCurrentItem(s0, { front: 'Rapid heartbeat', back: 'fast heart rate' });
    expect(restarted).toBe(false);
    expect(itemOf(state, TACHY).front).toBe('Rapid heartbeat');
    expect(progressOf(itemOf(state, TACHY))).toEqual(progressOf(itemOf(s0, TACHY)));
    expect(state.stats).toEqual(s0.stats);
    expect(state.currentId).toBe(s0.currentId);
    expect(state.phase).toBe(s0.phase);
  });

  it('an equivalent answer edit on a normal deck keeps progress (Menieres -> Ménière\'s)', () => {
    const s0 = step(stepUntil(freshState(), onItem(MENIERES)));
    const { state, restarted } = editCurrentItem(s0, {
      front: 'Inner ear disorder',
      back: "Ménière's disease",
    });
    expect(restarted).toBe(false);
    expect(itemOf(state, MENIERES).back).toBe("Ménière's disease");
    expect(progressOf(itemOf(state, MENIERES))).toEqual(progressOf(itemOf(s0, MENIERES)));
  });

  it('an equivalent edit with the same chunk count swaps in the new chunk text', () => {
    const s0 = stepUntil(freshState(), s => s.currentId === TREES && itemOf(s, TREES).stage === 'combine');
    const newBack = 'Large green trees grow slowly near the quiet river.';
    const { state, restarted } = editCurrentItem(s0, { front: 'Trees', back: newBack });
    expect(restarted).toBe(false);
    expect(itemOf(state, TREES).chunks).toEqual(['Large green', 'trees grow', 'slowly near', 'the quiet river.']);
    expect(progressOf(itemOf(state, TREES))).toEqual(progressOf(itemOf(s0, TREES)));
    expect(selectTrial(state)!.target.startsWith('Large green')).toBe(true);
  });

  it('a prompt-only edit keeps stored chunks even when chunkText would now produce different ones', () => {
    // Simulates a session saved under an older MIN_WORDS_TO_CHUNK (3): a
    // 3-word back stored as two chunks, which today's chunkText won't make.
    const s0 = stepUntil(freshState(), onItem(TACHY));
    const oldChunks = ['fast heart', 'rate'];
    const legacy: SessionState = {
      ...s0,
      items: s0.items.map(i =>
        i.id === TACHY ? { ...i, chunks: oldChunks, combineSeq: [{ start: 1, end: 2 }], stage: 'chunks' as const } : i
      ),
    };
    const { state, restarted } = editCurrentItem(legacy, { front: 'Rapid heartbeat', back: 'fast heart rate' });
    expect(restarted).toBe(false);
    expect(itemOf(state, TACHY).chunks).toEqual(oldChunks);
    expect(itemOf(state, TACHY).front).toBe('Rapid heartbeat');
    expect(progressOf(itemOf(state, TACHY))).toEqual(progressOf(itemOf(legacy, TACHY)));
  });

  it('trims both fields', () => {
    const s0 = stepUntil(freshState(), onItem(TACHY));
    const { state } = editCurrentItem(s0, { front: '  Rapid heartbeat  ', back: ' fast heart rate\n' });
    expect(itemOf(state, TACHY).front).toBe('Rapid heartbeat');
    expect(itemOf(state, TACHY).back).toBe('fast heart rate');
  });
});

describe('editCurrentItem -- punctuation mode decides whether the answer changed', () => {
  it("'pre op' -> 'pre-op' keeps progress on a normal deck", () => {
    const s0 = step(stepUntil(freshState(), onItem(PRE_OP)));
    const { state, restarted } = editCurrentItem(s0, { front: 'Before surgery', back: 'pre-op' });
    expect(restarted).toBe(false);
    expect(itemOf(state, PRE_OP).encodeStreak).toBe(1);
  });

  it("'pre op' -> 'pre-op' restarts on a strict deck", () => {
    const s0 = step(stepUntil(freshState({ strict: true }), onItem(PRE_OP)));
    expect(itemOf(s0, PRE_OP).encodeStreak).toBe(1);
    const { state, restarted } = editCurrentItem(s0, { front: 'Before surgery', back: 'pre-op' });
    expect(restarted).toBe(true);
    expect(itemOf(state, PRE_OP).encodeStreak).toBe(0);
    expect(itemOf(state, PRE_OP).back).toBe('pre-op');
  });
});

describe('editCurrentItem -- restart', () => {
  it('a real answer change mid-combine fully resets the item and nothing else', () => {
    const s0 = stepUntil(
      freshState(),
      s => s.currentId === TREES && itemOf(s, TREES).stage === 'combine' && itemOf(s, TREES).combineSeqIdx === 1
    );
    const edit = { front: 'Describe where the trees grow', back: 'tall oak trees grow quickly beside the busy highway' };
    const { state, restarted } = editCurrentItem(s0, edit);

    expect(restarted).toBe(true);
    const [expected] = buildItems([edit], CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    expect(itemOf(state, TREES)).toEqual({ ...expected, id: TREES, status: 'encoding' });
    expect(state.currentId).toBe(TREES);
    expect(state.phase).toBe('encode');
    expect(state.stats).toEqual(s0.stats);
    expect(state.items.filter(i => i.id !== TREES)).toEqual(s0.items.filter(i => i.id !== TREES));

    // Restarts right away, at a presentation beat of the new first chunk.
    const trial = selectTrial(state)!;
    expect(trial.itemId).toBe(TREES);
    expect(trial.cue.kind).toBe('present');
    expect(trial.target).toBe('tall oak');
  });

  it('an equivalent edit that changes the chunk count restarts', () => {
    const s0 = stepUntil(freshState(), s => s.currentId === TREES && itemOf(s, TREES).stage === 'combine');
    // 'quiet-river' normalizes to the same answer, but the back drops to 8
    // words -- at/under MIN_WORDS_TO_CHUNK, so it no longer chunks at all.
    const { state, restarted } = editCurrentItem(s0, {
      front: 'Describe where the trees grow',
      back: 'large green trees grow slowly near the quiet-river',
    });
    expect(restarted).toBe(true);
    expect(itemOf(state, TREES).chunks).toBeNull();
    expect(itemOf(state, TREES).stage).toBe('full');
    expect(itemOf(state, TREES).status).toBe('encoding');
  });

  it("an equivalent edit during 'remediate' restarts", () => {
    const inCombine = stepUntil(freshState(), s => s.currentId === TREES && itemOf(s, TREES).stage === 'combine');
    // Window 1-2 spans two chunks -> missThreshold 1: one miss remediates.
    const s0 = applyAnswer(inCombine, 'wrong words entirely', { revealed: false }).state;
    expect(itemOf(s0, TREES).stage).toBe('remediate');

    const { state, restarted } = editCurrentItem(s0, {
      front: 'Describe where the trees grow',
      back: 'Large green trees grow slowly near the quiet river.',
    });
    expect(restarted).toBe(true);
    expect(itemOf(state, TREES).stage).toBe('chunks');
    expect(itemOf(state, TREES).remediateStack).toEqual([]);
    expect(state.stats).toEqual(s0.stats);
  });

  for (const cycleOrder of ['inOrder', 'shuffled'] as const) {
    it(`a real answer change in cycle (${cycleOrder}) goes back to encode and never re-serves mastered cards`, () => {
      // Pass 1 gives every card cycleStreak 1; in pass 2 the first cards
      // master. Edit whichever unmastered card is up once at least one card
      // is mastered and at least one other still sits at cycleStreak 1.
      const s0 = stepUntil(freshState({ encodeReps: 1, cycleOrder }), s => {
        if (s.phase !== 'cycle') return false;
        const others = s.items.filter(i => i.id !== s.currentId);
        const cur = itemOf(s, s.currentId);
        return (
          cur.status !== 'mastered' &&
          others.some(i => i.status === 'mastered') &&
          others.some(i => i.status === 'ready' && i.cycleStreak === 1)
        );
      });
      const editedId = s0.currentId;
      const mastered = s0.items.filter(i => i.status === 'mastered').map(i => i.id);
      const streakBefore = new Map(s0.items.map(i => [i.id, i.cycleStreak]));

      const { state, restarted } = editCurrentItem(s0, {
        front: itemOf(s0, editedId).front,
        back: 'the period of time just before a surgical operation begins',
      });
      expect(restarted).toBe(true);
      expect(state.phase).toBe('encode');
      expect(state.queue).toEqual([]);
      expect(state.currentId).toBe(editedId);
      expect(itemOf(state, editedId).status).toBe('encoding');
      expect(state.stats).toEqual(s0.stats);

      // Drive to completion; record which card is served at every step.
      let s = state;
      const served: number[] = [];
      const firstSeenStreak = new Map<number, number>();
      for (let guard = 0; selectTrial(s); guard++) {
        if (guard > 1000) throw new Error('session never completed');
        served.push(s.currentId);
        if (!firstSeenStreak.has(s.currentId)) firstSeenStreak.set(s.currentId, itemOf(s, s.currentId).cycleStreak);
        s = step(s);
      }

      expect(s.currentId).toBe(SESSION_COMPLETE_ID);
      expect(s.items.every(i => i.status === 'mastered')).toBe(true);
      for (const id of mastered) expect(served).not.toContain(id);
      // Unmastered, unedited cards come back with their streak intact.
      for (const [id, streak] of firstSeenStreak) {
        if (id !== editedId) expect(streak).toBe(streakBefore.get(id));
      }
      expect(served.some(id => id !== editedId && !mastered.includes(id))).toBe(true);
    });
  }
});

describe('editCurrentItem -- purity and no-ops', () => {
  it('does not mutate a deep-frozen input, on either path, in either phase', () => {
    const encodeState = stepUntil(freshState(), s => s.currentId === TREES && itemOf(s, TREES).stage === 'combine');
    const cycleState = stepUntil(freshState({ encodeReps: 1, cycleOrder: 'inOrder' }), s => s.phase === 'cycle');
    for (const s0 of [encodeState, cycleState]) {
      const snapshot = structuredClone(s0);
      deepFreeze(s0);
      const front = itemOf(s0, s0.currentId).front;
      const back = itemOf(s0, s0.currentId).back;
      expect(() => editCurrentItem(s0, { front: 'edited prompt', back })).not.toThrow();
      expect(() => editCurrentItem(s0, { front, back: 'a completely different answer here' })).not.toThrow();
      expect(s0).toEqual(snapshot);
    }
  });

  it("is a no-op on 'batch-done'", () => {
    const s0 = stepUntil(freshState({ encodeReps: 1, batchSize: 2 }), s => s.phase === 'batch-done');
    const result = editCurrentItem(s0, { front: 'x', back: 'y' });
    expect(result.state).toBe(s0);
    expect(result.restarted).toBe(false);
  });

  it('is a no-op on an empty front or back', () => {
    const s0 = stepUntil(freshState(), onItem(TACHY));
    for (const edit of [
      { front: '   ', back: 'fast heart rate' },
      { front: 'Tachycardia', back: '' },
    ]) {
      const result = editCurrentItem(s0, edit);
      expect(result.state).toBe(s0);
      expect(result.restarted).toBe(false);
    }
  });
});

describe('selectNextEncodeItem skips mastered items', () => {
  it('never picks a mastered item, from the front or mid-rotation', () => {
    const items = buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    const batch = items.map((it, idx) => (idx === 3 ? { ...it, status: 'encoding' as const } : { ...it, status: 'mastered' as const }));
    expect(selectNextEncodeItem(batch, SESSION_COMPLETE_ID)).toBe(batch[3]);
    expect(selectNextEncodeItem(batch, batch[3].id)).toBe(batch[3]);
    expect(selectNextEncodeItem(batch, batch[0].id)).toBe(batch[3]);
    const allDone = batch.map((it, idx) => (idx === 3 ? { ...it, status: 'ready' as const } : it));
    expect(selectNextEncodeItem(allDone, allDone[0].id)).toBeNull();
  });
});
