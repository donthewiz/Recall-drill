import { describe, expect, it } from 'vitest';
import { runCharacterizationSuite } from './characterization.shared';
import { RealEngineDriver } from './harness/engineDriver';
import {
  FULL_STAGE_BACK,
  TWO_CHUNK_BACK,
  TWO_CHUNK_CHUNKS,
  TWO_CHUNK_DIFFICULTY,
  FOUR_CHUNK_BACK,
  FOUR_CHUNK_CHUNKS,
  CHUNK_DIFFICULTY,
} from './fixtures/deck';
import { applyAnswer, applyNext, buildItems, initSession, selectTrial, SESSION_COMPLETE_ID } from '../utils/drillEngine';
import type { SessionState } from '../types';

runCharacterizationSuite(() => new RealEngineDriver());

// Phase 3 (Final check): the real-engine continuation of
// characterization.shared.ts's "full-stage card" scenario, which now stops
// one driver.next() short of fully finished because that next() diverges by
// driver -- LegacyEngine finishes immediately (see
// characterization.legacy.spec.ts), the real engine enters the Final check
// instead. Driven with the raw engine functions (not RealEngineDriver)
// since the driver's ItemSnapshot/DriverTrial shapes predate finalDone.
describe('full-stage card (Final check): the driver.next() right after cycle mastery enters phase \'final\' instead of finishing', () => {
  it('one shuffled Final-check trial over the single item, then the session finishes', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q1', back: FULL_STAGE_BACK }], 35, 'cumulative'),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' },
    });
    const itemId = state.currentId;

    // Drive to cycle mastery exactly as the shared scenario does.
    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state; // encodeStreak 1
    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state; // ready -> cycle
    state = applyAnswer(state, 'nope', { revealed: false }).state; // cycle miss
    state = applyNext(state);
    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state; // cycleStreak 1
    state = applyNext(state);
    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state; // cycleStreak 2 -> mastered
    expect(state.items.find(i => i.id === itemId)).toMatchObject({ status: 'mastered', cycleStreak: 2 });
    expect(state.currentId).not.toBe(SESSION_COMPLETE_ID);

    // The next() that would have finished LegacyEngine instead enters the
    // Final check: one shuffled, cue-free trial over the (only) item.
    state = applyNext(state);
    expect(state.phase).toBe('final');
    const trial = selectTrial(state)!;
    expect(trial).toMatchObject({ itemId, stage: 'final', target: FULL_STAGE_BACK, cue: { kind: 'none' } });

    const res = applyAnswer(state, FULL_STAGE_BACK, { revealed: false });
    expect(res.verdict).toBe('exact');
    expect(res.advance).toBe('manual');
    expect(res.state.items.find(i => i.id === itemId)).toMatchObject({
      finalDone: true,
      status: 'mastered', // Phase 3 never touches status/cycleStreak.
      cycleStreak: 2,
    });

    state = applyNext(res.state);
    expect(state.currentId).toBe(SESSION_COMPLETE_ID);
  });
});

// Phase 8 (C8a): the C8a-aware version of the "four-chunk card" scenario
// that used to live in the shared suite -- see characterization.shared.ts's
// header comment. Same B1/remediation coverage as the frozen
// characterization.legacy.spec.ts variant this replaces for RealEngineDriver,
// with the chunk-walk updated for C8a's new criterion: every chunk needs
// exactly one cued (isBlind: false) correct answer followed by one blind
// (isBlind: true) correct answer, regardless of encodeReps -- encodeReps: 1
// here specifically demonstrates that a chunk no longer advances on the
// cued attempt alone the way it did pre-C8a.
describe('four-chunk card (C8a): post-B1-fix culprit attribution + full remediate branch coverage', () => {
  it('flags only the chunks that actually mismatch, not the whole window (B1 fixed)', () => {
    const driver = new RealEngineDriver();
    // Pinned to the exhaustive ladder for the same reason as the two-chunk
    // scenario in the shared suite -- this walkthrough exercises specific
    // windows (missThreshold 1 and 2) from buildCombineSequence's original
    // shape.
    driver.init([{ front: 'Q3', back: FOUR_CHUNK_BACK }], {
      encodeReps: 1,
      chunkDifficulty: CHUNK_DIFFICULTY,
      ladderMode: 'exhaustive',
    });

    const itemId = driver.currentTrial()!.itemId;

    // C8a: every chunk needs one cued (isBlind: false) correct answer, which
    // only moves it to blind, then one blind (isBlind: true) correct answer,
    // which actually advances it -- both regardless of encodeReps: 1.
    for (const chunk of FOUR_CHUNK_CHUNKS) {
      expect(driver.currentTrial()).toEqual({ itemId, stage: 'chunks', target: chunk, isBlind: false });
      driver.answer(chunk);
      expect(driver.currentTrial()).toEqual({ itemId, stage: 'chunks', target: chunk, isBlind: true });
      driver.answer(chunk);
    }
    expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineSeqIdx: 0 });

    // buildCombineSequence(4) = [{1,2},{2,3},{1,3},{3,4},{2,4},{1,4}] (6 windows).
    // Walk the first 5 correctly to reach the final {1,4} full-answer window.
    const windows = [
      [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1]].join(' '),
      [FOUR_CHUNK_CHUNKS[1], FOUR_CHUNK_CHUNKS[2]].join(' '),
      [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1], FOUR_CHUNK_CHUNKS[2]].join(' '),
      [FOUR_CHUNK_CHUNKS[2], FOUR_CHUNK_CHUNKS[3]].join(' '),
      [FOUR_CHUNK_CHUNKS[1], FOUR_CHUNK_CHUNKS[2], FOUR_CHUNK_CHUNKS[3]].join(' '),
    ];
    for (const w of windows) {
      expect(driver.currentTrial()!.target).toBe(w);
      driver.answer(w);
    }
    expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineSeqIdx: 5 });
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'combine',
      target: FOUR_CHUNK_BACK,
      isBlind: false,
    });

    // Drop "green" (from chunk 0) and "near" (from chunk 2), leaving chunks
    // 1 and 3 typed correctly. windowChunkCount=4 -> missThreshold=2, so it
    // takes two identical misses to trigger remediation.
    const dropped = 'large trees grow slowly the quiet river';
    let res = driver.answer(dropped);
    expect(res.verdict).toBe('wrong');
    if (res.advance === 'manual') driver.next();
    expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineMissCount: 1 });

    res = driver.answer(dropped);
    expect(res.verdict).toBe('wrong');
    if (res.advance === 'manual') driver.next();
    // Post-B1-fix: the LCS alignment correctly flags only chunks 0 and 2
    // (the ones with an actually-missing word) -- chunks 1 and 3, which
    // were typed correctly, are NOT flagged.
    expect(driver.snapshotItem(itemId)).toMatchObject({
      stage: 'remediate',
      remediateStackLen: 1,
      remediateQueueLen: 1,
    });
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'remediate',
      target: FOUR_CHUNK_CHUNKS[0],
      isBlind: false,
    });

    // Miss the first remediate spot twice with unrelated text -> deeper
    // split via splitInHalf/culpritHalf (rWordCount=2 > 1).
    let zRes = driver.answer('zzz');
    if (zRes.advance === 'manual') driver.next();
    res = driver.answer('zzz');
    expect(res.verdict).toBe('wrong');
    if (res.advance === 'manual') driver.next();
    expect(driver.snapshotItem(itemId)).toMatchObject({ remediateStackLen: 2 });
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'remediate',
      target: 'large',
      isBlind: false,
    });

    // Solve the deeper 1-word level -> pops back to the 2-word parent,
    // which resets to non-blind ("expanding to parent" branch).
    driver.answer('large');
    expect(driver.snapshotItem(itemId)).toMatchObject({ remediateStackLen: 1 });
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'remediate',
      target: FOUR_CHUNK_CHUNKS[0],
      isBlind: false,
    });

    // Solve the parent (chunk 0 fully reinforced) -> stack empties -> shifts
    // the one remaining queued spot (chunk 2, the other genuine culprit) in.
    driver.answer(FOUR_CHUNK_CHUNKS[0]);
    expect(driver.snapshotItem(itemId)).toMatchObject({ remediateStackLen: 1, remediateQueueLen: 0 });
    expect(driver.currentTrial()!.target).toBe(FOUR_CHUNK_CHUNKS[2]);

    // Drain the last queued spot.
    driver.answer(FOUR_CHUNK_CHUNKS[2]);

    // Queue now empty -> resumes combine at the window that originally failed.
    expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineSeqIdx: 5, remediateStackLen: 0 });
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'combine',
      target: FOUR_CHUNK_BACK,
      isBlind: false,
    });

    // Finally pass the window for real -> status 'ready' -> only item ->
    // auto-advances to cycle.
    driver.answer(FOUR_CHUNK_BACK);
    expect(driver.snapshotItem(itemId)).toMatchObject({ status: 'ready' });
    expect(driver.currentTrial()).toEqual({
      itemId,
      stage: 'cycle',
      target: FOUR_CHUNK_BACK,
      isBlind: true,
    });
  });
});

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
      items: buildItems([{ front: 'Q', back: TWO_CHUNK_BACK }], TWO_CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: TWO_CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    // Walk to a combine miss that enters remediate.
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[1], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[1], { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[1], { revealed: false }).state;

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
    expect(driver.stats()).toEqual({ attempts: 2, misses: 0, nearMisses: 0, overrides: 0 });

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
    expect(driver.stats()).toEqual({ attempts: 2, misses: 0, nearMisses: 0, overrides: 0 });
  });

  it('combine stage: reveal resets combineStreak, not combineMissCount', () => {
    const driver = new RealEngineDriver();
    driver.init([{ front: 'Q', back: TWO_CHUNK_BACK }], {
      encodeReps: 2,
      chunkDifficulty: TWO_CHUNK_DIFFICULTY,
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
    expect(driver.stats()).toEqual({ attempts: 2, misses: 0, nearMisses: 0, overrides: 0 });
  });
});
