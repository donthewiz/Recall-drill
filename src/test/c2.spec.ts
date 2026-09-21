// C2 (lenient grading) integration tests: near-miss advances the streak like
// exact but tallies nearMisses instead of misses, and the manual override
// retroactively converts a still-pending wrong verdict to exact. See
// grade.spec.ts for the grade() function's own unit tests.
import { describe, expect, it } from 'vitest';
import { applyAnswer, buildItems, initSession, SESSION_COMPLETE_ID } from '../utils/drillEngine';
import type { SessionState } from '../types';

const PROSE_TARGET =
  'large green trees grow slowly near the quiet flowing rivers'; // 10 words

// chunkDifficulty defaults to 100 (full-card mode, chunkText returns null
// regardless of length) so the trial's target is the whole back text -- most
// of these tests care about grade() interacting with applyAnswer, not the
// chunking ladder, and a chunked target would otherwise silently compare
// against a 3-word chunk instead of the intended long answer.
function freshState(
  back: string,
  encodeReps = 2,
  stemTolerance = true,
  chunkDifficulty = 100
): SessionState {
  return initSession({
    items: buildItems([{ front: 'Q', back }], chunkDifficulty, 'cumulative'),
    phase: 'encode',
    queue: [],
    stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    config: { encodeReps, chunkDifficulty, stemTolerance, ladderMode: 'cumulative' },
  });
}

describe('C2 near-miss: advances the streak like exact, tallies nearMisses not misses', () => {
  it('dropping a stopword from an otherwise-exact long answer counts as near and advances the streak', () => {
    const target = 'wait for the bus at the station today please';
    const state = freshState(target, 2);
    const typed = 'wait for bus at the station today please'; // drops "the" (stopword)
    const result = applyAnswer(state, typed, { revealed: false });

    expect(result.verdict).toBe('near');
    expect(result.feedback.type).toBe('info');
    expect(result.feedback.dwellKey).toBe('near-miss');
    expect(result.feedback.diff).toBeDefined();
    expect(result.state.stats).toEqual({ attempts: 1, misses: 0, nearMisses: 1, overrides: 0 });
    // Advances exactly like exact: encodeStreak went from 0 -> 1 (encodeReps=2, not yet ready).
    const it = result.state.items.find(i => i.id === result.state.currentId)!;
    expect(it.encodeStreak).toBe(1);
    expect(it.status).toBe('encoding');
  });

  it('a plural-only difference on a long answer counts as near when stemTolerance is on', () => {
    const state = freshState(PROSE_TARGET, 1); // encodeReps 1: near immediately masters the stage-unit
    const typed = 'large green trees grow slowly near the quiet flowing river'; // river, not rivers
    const result = applyAnswer(state, typed, { revealed: false });
    expect(result.verdict).toBe('near');
    expect(result.state.stats.nearMisses).toBe(1);
    expect(result.state.stats.misses).toBe(0);
  });

  it('the same plural difference counts as wrong when stemTolerance is off', () => {
    const state = freshState(PROSE_TARGET, 1, false);
    const typed = 'large green trees grow slowly near the quiet flowing river';
    const result = applyAnswer(state, typed, { revealed: false });
    expect(result.verdict).toBe('wrong');
    expect(result.state.stats.misses).toBe(1);
    expect(result.state.stats.nearMisses).toBe(0);
  });

  it('a near-miss in the cycle phase advances cycleStreak and does not increment misses', () => {
    let state = freshState('wait for the bus at the station today please', 1);
    // Reach cycle phase (encodeReps=1, single item).
    state = applyAnswer(state, 'wait for the bus at the station today please', { revealed: false })
      .state;
    expect(state.phase).toBe('cycle');

    const result = applyAnswer(
      state,
      'wait for bus at the station today please', // drops "the"
      { revealed: false }
    );
    expect(result.verdict).toBe('near');
    expect(result.state.stats.nearMisses).toBe(1);
    expect(result.state.stats.misses).toBe(0);
    const it = result.state.items.find(i => i.id === result.state.currentId)!;
    expect(it.cycleStreak).toBe(1);
  });
});

describe('C2 manual override: retroactively counts a pending wrong verdict as exact', () => {
  it('override does not double-count the attempt, decrements nothing (miss was never committed), and increments overrides', () => {
    const state = freshState('the mitochondria makes cell energy', 2, true, 35); // chunks stage on a 5-word back (>3 words)
    const trial = state.items[0];
    // First submit a genuinely wrong answer against the SAME target the shell
    // would still be showing (chunks stage, chunk 0) -- but per the shell's
    // deferred-apply design, this "wrong" result is never committed to the
    // state the override then operates on.
    const target = trial.chunks![trial.chunkIndex];
    const wrongResult = applyAnswer(state, 'nonsense answer', { revealed: false });
    expect(wrongResult.verdict).toBe('wrong');
    expect(wrongResult.state.stats.misses).toBe(1); // this is the DISCARDED result

    // The override call operates on the ORIGINAL (pre-wrong) state, not
    // wrongResult.state -- mirrors handleOverride canceling the pending timer
    // before the wrong result was ever applied.
    const overrideResult = applyAnswer(state, target, { revealed: false, override: true });
    expect(overrideResult.verdict).toBe('exact');
    expect(overrideResult.state.stats).toEqual({
      attempts: 0, // NOT incremented -- this isn't a new attempt
      misses: 0, // the discarded wrong result's miss was never committed
      nearMisses: 0,
      overrides: 1,
    });
    const it = overrideResult.state.items.find(i => i.id === overrideResult.state.currentId)!;
    expect(it.chunkStreak).toBe(1); // advanced exactly as a genuine correct answer would
  });

  it('override on the final rep of a stage-unit advances the item exactly like a genuine correct answer', () => {
    const state = freshState('run fast today', 1, true); // full stage (3 words), encodeReps=1
    const target = state.items[0].back;
    const overrideResult = applyAnswer(state, target, { revealed: false, override: true });
    expect(overrideResult.verdict).toBe('exact');
    expect(overrideResult.state.stats.overrides).toBe(1);
    expect(overrideResult.state.stats.attempts).toBe(0);
    // Single item, encodeReps=1 -> immediately reaches 'ready' and advances
    // straight to cycle phase, same as a genuine correct answer would.
    expect(overrideResult.state.phase).toBe('cycle');
  });
});
