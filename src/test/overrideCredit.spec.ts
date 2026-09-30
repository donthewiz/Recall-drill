// "Count as correct" (2026-09-26): SessionView now runs the override on the
// state from just BEFORE the wrong answer (preWrongStateRef), not on the
// post-miss state it used to. This pins the engine half of that contract:
// an override on the pre-answer state leaves the card exactly where a typed
// correct answer would -- same item progress, same queue, same next card --
// in every phase. Only the stats differ (no attempt, no miss, +1 override).
// The SessionView half (using the snapshot) has no component test; it's in
// the manual check.
import { describe, expect, it } from 'vitest';
import { applyAnswer, applyNext, buildItems, initSession, selectTrial, SESSION_COMPLETE_ID } from '../utils/drillEngine';
import type { DeckItem, DrillItem, SessionState } from '../types';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };
const DECK: DeckItem[] = [
  { front: 'Tachy', back: 'fast heart rate' },
  { front: 'Hyper', back: 'blood pressure that stays above the normal range for a long time' },
  { front: 'itis', back: 'inflammation' },
];
const LONG = 1;

function fresh(): SessionState {
  return initSession({
    items: buildItems(DECK, 35, 'cumulative', undefined, undefined, false),
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative', cycleOrder: 'inOrder' },
  });
}

function playUntil(stop: (s: SessionState) => boolean): SessionState {
  let s = fresh();
  for (let guard = 0; !stop(s); guard++) {
    expect(guard).toBeLessThan(400);
    const t = selectTrial(s)!;
    const r = applyAnswer(s, t.cue.kind === 'present' ? '' : t.target, { revealed: false });
    s = r.advance === 'manual' ? applyNext(r.state) : r.state;
  }
  return s;
}

const item = (s: SessionState, id: number) => s.items.find(i => i.id === id)!;
// Ladder position only: per-card telemetry (attempts/misses/...) is left out,
// since the old post-miss route below also recorded the miss it overrode.
const progress = (i: DrillItem) => {
  const { id: _id, attempts: _a, misses: _m, reveals: _r, nearMisses: _n, hardSpans: _h, ...rest } = i;
  return rest;
};

// Third field: did the old post-miss route already land on the correct-answer
// progress? Only for a blind chunk attempt (the post-miss trial is that chunk's
// presentation beat, and the override flag skips it) -- everywhere else it didn't.
const SCENARIOS: [string, (s: SessionState) => boolean, boolean][] = [
  ['full-stage card, 2nd rep', s => s.phase === 'encode' && s.currentId === 0 && item(s, 0).encodeStreak === 1, false],
  ['chunk, blind attempt', s => s.phase === 'encode' && s.currentId === LONG && item(s, LONG).stage === 'chunks' && item(s, LONG).chunkStreak === 1, true],
  ['first 2-part combination (a miss would isolate)', s => s.phase === 'encode' && s.currentId === LONG && item(s, LONG).stage === 'combine' && item(s, LONG).combineSeqIdx === 0, false],
  ['whole-answer window, 2nd rep', s => s.phase === 'encode' && s.currentId === LONG && item(s, LONG).stage === 'combine' && item(s, LONG).combineSeqIdx === 1 && item(s, LONG).combineStreak === 1, false],
  ['review, the answer that would master', s => s.phase === 'cycle' && item(s, s.currentId).cycleStreak === 1, false],
  ['final check', s => s.phase === 'final', false],
];

describe('override on the pre-answer state credits a correct answer', () => {
  for (const [name, stop, oldRouteMatched] of SCENARIOS) {
    it(name, () => {
      const pre = playUntil(stop);
      const t = selectTrial(pre)!;
      const correct = applyAnswer(pre, t.target, { revealed: false });
      const wrong = applyAnswer(pre, 'zzz wrong', { revealed: false });
      expect(wrong.verdict).toBe('wrong');
      const override = applyAnswer(pre, t.target, { revealed: false, override: true });

      expect(override.verdict).toBe('exact');
      expect(progress(item(override.state, t.itemId))).toEqual(progress(item(correct.state, t.itemId)));
      expect(override.state.queue).toEqual(correct.state.queue);
      expect(override.state.currentId).toBe(correct.state.currentId);
      expect(override.state.phase).toBe(correct.state.phase);
      expect(override.advance).toBe(correct.advance);
      expect(override.state.stats).toEqual({ ...pre.stats, overrides: pre.stats.overrides + 1 });

      // The post-miss route the UI used to take: it misses the correct-answer
      // state everywhere except a blind chunk attempt -- the reason for the change.
      const postMiss = applyAnswer(wrong.state, selectTrial(wrong.state)!.target, { revealed: false, override: true });
      const same =
        JSON.stringify(progress(item(postMiss.state, t.itemId))) === JSON.stringify(progress(item(correct.state, t.itemId))) &&
        JSON.stringify(postMiss.state.queue) === JSON.stringify(correct.state.queue);
      expect(same).toBe(oldRouteMatched);
    });
  }
});
