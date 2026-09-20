import { describe, expect, it } from 'vitest';
import { runCharacterizationSuite } from './characterization.shared';
import { RealEngineDriver } from './harness/engineDriver';
import { FULL_STAGE_BACK, TWO_CHUNK_BACK, TWO_CHUNK_CHUNKS, CHUNK_DIFFICULTY } from './fixtures/deck';
import { applyAnswer, buildItems, initSession, SESSION_COMPLETE_ID } from '../utils/drillEngine';
import type { SessionState } from '../types';

runCharacterizationSuite(() => new RealEngineDriver());

// Purity fix (found while implementing B2, not one of B1-B5): applyAnswer's
// remediate-stage branch used to mutate it.remediateStack/.remediateQueue in
// place via push()/pop()/shift() and by assigning directly onto a
// RemediateItem's .streak/.missCount -- but those are shared references with
// the input state until cloned, so applyAnswer was silently mutating its
// caller's input state, violating the "never mutate the input" contract the
// v2 handoff doc requires. Fixed by cloning remediateStack (and each
// RemediateItem) and remediateQueue before mutating.
describe('applyAnswer purity: never mutates its input state', () => {
  it('a remediate-stage answer leaves the original state.items entry untouched', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: TWO_CHUNK_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      config: { encodeReps: 2, chunkDifficulty: CHUNK_DIFFICULTY },
    });

    // Walk to a combine miss that enters remediate.
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[1], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[1], { revealed: false }).state;
    state = applyAnswer(state, 'makes cell energy', { revealed: false }).state;

    const it = state.items.find(i => i.id === state.currentId)!;
    expect(it.stage).toBe('remediate');
    const beforeSnapshot = JSON.parse(JSON.stringify(it.remediateStack));
    const stackRefBefore = it.remediateStack;

    // Answer correctly once (streak 1 of 2) -- mutates rTop.streak in the
    // naive implementation.
    applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false });

    // The ORIGINAL state object (still referenced by `state`/`it`/`stackRefBefore`)
    // must be completely unaffected by the call above.
    expect(it.remediateStack).toBe(stackRefBefore);
    expect(JSON.parse(JSON.stringify(it.remediateStack))).toEqual(beforeSnapshot);
    expect(it.remediateStack[0].streak).toBe(0);
  });
});

// B2 fix (Phase 1): a revealed trial resets the streak to 0 and never counts
// as a miss, regardless of what was typed. Engine-only -- see
// characterization.shared.ts's header comment for why this can't run against
// LegacyEngine.
describe('B2 fix: revealing resets the streak and does not count as a miss', () => {
  it('encode phase: reveal then type the now-visible answer correctly -- streak resets, no miss counted', () => {
    const driver = new RealEngineDriver();
    driver.init([{ front: 'Q', back: FULL_STAGE_BACK }], { encodeReps: 2 });
    const itemId = driver.currentTrial()!.itemId;

    // Reach a blind trial (streak 1).
    driver.answer(FULL_STAGE_BACK);
    expect(driver.currentTrial()!.isBlind).toBe(true);
    expect(driver.snapshotItem(itemId)).toMatchObject({ encodeStreak: 1 });

    // Reveal, then type the now-visible answer correctly -- must NOT advance
    // the streak or the item, and must NOT count as a miss.
    driver.showAnswer();
    const res = driver.answer(FULL_STAGE_BACK);
    expect(res).toEqual({ verdict: 'revealed', advance: 'auto' });
    expect(driver.snapshotItem(itemId)).toMatchObject({ status: 'encoding', encodeStreak: 0 });
    expect(driver.stats()).toEqual({ attempts: 2, misses: 0 });

    // The trial stays put (same item, same stage) -- not blind again until
    // another genuine correct answer.
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'full',
      target: FULL_STAGE_BACK,
      isBlind: false,
    });
  });

  it('encode phase: reveal then type something wrong -- still resets to 0, still no miss counted', () => {
    const driver = new RealEngineDriver();
    driver.init([{ front: 'Q', back: FULL_STAGE_BACK }], { encodeReps: 2 });
    driver.answer(FULL_STAGE_BACK);
    const itemId = driver.currentTrial()!.itemId;

    driver.showAnswer();
    const res = driver.answer('nonsense');
    expect(res).toEqual({ verdict: 'revealed', advance: 'auto' });
    expect(driver.snapshotItem(itemId)).toMatchObject({ encodeStreak: 0 });
    expect(driver.stats()).toEqual({ attempts: 2, misses: 0 });
  });

  it('combine stage: reveal resets combineStreak, not combineMissCount', () => {
    const driver = new RealEngineDriver();
    driver.init([{ front: 'Q', back: TWO_CHUNK_BACK }], {
      encodeReps: 2,
      chunkDifficulty: CHUNK_DIFFICULTY,
    });
    const itemId = driver.currentTrial()!.itemId;
    driver.answer(TWO_CHUNK_CHUNKS[0]);
    driver.answer(TWO_CHUNK_CHUNKS[0]);
    driver.answer(TWO_CHUNK_CHUNKS[1]);
    driver.answer(TWO_CHUNK_CHUNKS[1]);
    expect(driver.currentTrial()).toMatchObject({ stage: 'combine' });

    driver.answer(TWO_CHUNK_BACK); // genuine correct, combineStreak -> 1
    expect(driver.snapshotItem(itemId)).toMatchObject({ combineStreak: 1 });

    driver.showAnswer();
    const res = driver.answer(TWO_CHUNK_BACK);
    expect(res).toEqual({ verdict: 'revealed', advance: 'auto' });
    expect(driver.snapshotItem(itemId)).toMatchObject({ combineStreak: 0, combineMissCount: 0 });
  });

  it('cycle phase: reveal resets cycleStreak, reinserts into queue, no miss counted, still manual advance', () => {
    const driver = new RealEngineDriver();
    driver.init([{ front: 'Q', back: FULL_STAGE_BACK }], { encodeReps: 1 });
    driver.answer(FULL_STAGE_BACK);
    const itemId = driver.currentTrial()!.itemId;
    expect(driver.currentTrial()).toMatchObject({ stage: 'cycle' });

    driver.showAnswer();
    const res = driver.answer(FULL_STAGE_BACK);
    expect(res).toEqual({ verdict: 'revealed', advance: 'manual' });
    expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 0 });
    expect(driver.stats()).toEqual({ attempts: 2, misses: 0 });
  });
});
