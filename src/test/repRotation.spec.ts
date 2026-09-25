// Phase 2 (within-session spacing, 2026-09-24): a correct rep that's still
// short of criterion now rotates to another batch card too, not just a
// stage-unit completion. The presentation beat -> blind attempt pair stays
// adjacent (that rotation call is skipped on purpose -- see applyAnswer's
// isPresentation branch), and a wrong answer still retries the same card.
import { describe, expect, it } from 'vitest';
import { applyAnswer, buildItems, initSession, selectTrial } from '../utils/drillEngine';
import type { DeckItem, SessionState, Trial } from '../types';
import { CHUNK_DIFFICULTY, FOUR_CHUNK_BACK } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function freshState(items: SessionState['items'], encodeReps: number): SessionState {
  return initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: -1,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: {
      encodeReps,
      chunkDifficulty: CHUNK_DIFFICULTY,
      stemTolerance: true,
      ladderMode: 'cumulative',
    },
  });
}

const encodingCount = (state: SessionState) =>
  state.items.filter(i => i.status !== 'ready' && i.status !== 'mastered').length;

describe('Phase 2: rotate to another card between reps', () => {
  it('no two consecutive graded encode trials are on the same card while more than one card is still encoding', () => {
    const deck: DeckItem[] = [
      { front: 'Q0', back: 'answer zero' },
      { front: 'Q1', back: 'answer one' },
      { front: 'Q2', back: 'answer two' },
    ];
    const items = buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    let s = freshState(items, 3);

    let prevItemId: number | null = null;
    let guard = 0;
    while (s.items.some(i => i.status !== 'ready')) {
      expect(guard++).toBeLessThan(200);
      const trial = selectTrial(s)!;
      if (prevItemId !== null && encodingCount(s) > 1) {
        expect(trial.itemId).not.toBe(prevItemId);
      }
      s = applyAnswer(s, trial.target, { revealed: false }).state;
      prevItemId = trial.itemId;
    }
    expect(s.items.every(i => i.status === 'ready')).toBe(true);
  });

  it("a wrong answer serves the same card next", () => {
    const deck: DeckItem[] = [
      { front: 'Q0', back: 'answer zero' },
      { front: 'Q1', back: 'answer one' },
      { front: 'Q2', back: 'answer two' },
    ];
    const items = buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    const s0 = freshState(items, 3);
    const currentId = s0.currentId;

    const res = applyAnswer(s0, 'nonsense wrong answer', { revealed: false });
    expect(res.verdict).toBe('wrong');
    expect(res.state.currentId).toBe(currentId);
    expect(selectTrial(res.state)!.itemId).toBe(currentId);
  });

  it('a presentation trial and its blind attempt stay adjacent, and final-window reps rotate while another card is still encoding', () => {
    // encodeReps deliberately large: the chunked card's chunk stage and
    // intermediate combine windows cost a fixed number of rotating turns
    // (independent of encodeReps -- see requiredRepsForWindow/C8a), but the
    // FINAL combine window needs encodeReps consecutive reps. A large value
    // here keeps the filler card (which needs the same encodeReps to reach
    // 'ready') still pending for at least the first couple of those reps,
    // so rotation during the final window is actually observable.
    const encodeReps = 8;
    const deck: DeckItem[] = [
      { front: 'Trees', back: FOUR_CHUNK_BACK },
      { front: 'Filler', back: 'a filler answer' },
    ];
    const items = buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    const TREES = items[0].id;
    let s = freshState(items, encodeReps);

    const trace: Trial[] = [];
    let guard = 0;
    while (s.items.some(i => i.status !== 'ready')) {
      expect(guard++).toBeLessThan(500);
      const trial = selectTrial(s)!;
      trace.push(trial);
      const typed = trial.cue.kind === 'present' ? '' : trial.target;
      s = applyAnswer(s, typed, { revealed: false }).state;
    }
    expect(s.items.every(i => i.status === 'ready')).toBe(true);

    // Every TREES presentation is immediately followed by TREES' own blind
    // attempt of the same chunk text -- never interrupted by a rotation.
    const presentationIdxs = trace
      .map((t, i) => ({ t, i }))
      .filter(({ t }) => t.itemId === TREES && t.cue.kind === 'present')
      .map(({ i }) => i);
    expect(presentationIdxs.length).toBe(4); // FOUR_CHUNK_BACK -> 4 chunks
    for (const i of presentationIdxs) {
      const next = trace[i + 1];
      expect(next.itemId).toBe(TREES);
      expect(next.cue.kind).toBe('none');
      expect(next.target).toBe(trace[i].target);
    }

    // The final combine window's target is the whole answer (start 1, end
    // === chunks.length) -- every rep of it shares that same target.
    const finalWindowIdxs = trace
      .map((t, i) => ({ t, i }))
      .filter(({ t }) => t.itemId === TREES && t.stage === 'combine' && t.target === FOUR_CHUNK_BACK)
      .map(({ i }) => i);
    expect(finalWindowIdxs.length).toBe(encodeReps);
    // At least one pair of consecutive final-window reps has the filler
    // card's own trial rotated in between -- proving reps within the same
    // window are spread across the batch, not run back to back.
    const hasRotatedGap = finalWindowIdxs.some((idx, k) => k > 0 && idx - finalWindowIdxs[k - 1] > 1);
    expect(hasRotatedGap).toBe(true);
  });
});
