import { describe, expect, it } from 'vitest';
import { runCharacterizationSuite } from './characterization.shared';
import { LegacyEngine } from './reference/legacyEngine';
import { FOUR_CHUNK_BACK, FOUR_CHUNK_CHUNKS, CHUNK_DIFFICULTY } from './fixtures/deck';

runCharacterizationSuite(() => new LegacyEngine());

// Phase 8 (C8a) changed the chunks stage's advance criterion (see
// characterization.shared.ts's header comment) in a way LegacyEngine, a
// frozen pre-C8a snapshot, can never satisfy -- this scenario used to live
// in the shared suite, run against both drivers. Kept here verbatim,
// LegacyEngine-only, to keep proving the pre-C8a behavior is undisturbed;
// see characterization.engine.spec.ts for the C8a-aware version.
describe('four-chunk card (pre-C8a behavior): post-B1-fix culprit attribution + full remediate branch coverage', () => {
  it('flags only the chunks that actually mismatch, not the whole window (B1 fixed)', () => {
    const driver = new LegacyEngine();
    // Pinned to the exhaustive ladder for the same reason as the two-chunk
    // scenario in the shared suite -- this walkthrough exercises specific
    // windows (missThreshold 1 and 2) from buildCombineSequence's original
    // shape.
    // LegacyEngine.init's own signature has no ladderMode param -- it always
    // rebuilds with the original exhaustive ladder regardless (see its
    // EngineDriver.init doc comment), so there's nothing to pass here.
    driver.init([{ front: 'Q3', back: FOUR_CHUNK_BACK }], {
      encodeReps: 1,
      chunkDifficulty: CHUNK_DIFFICULTY,
    });

    const itemId = driver.currentTrial()!.itemId;

    // Walk all 4 chunks (encodeReps=1 -> each correct answer advances immediately).
    for (const chunk of FOUR_CHUNK_CHUNKS) {
      expect(driver.currentTrial()).toEqual({ itemId, stage: 'chunks', target: chunk, isBlind: false });
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
    expect(res).toEqual({ verdict: 'wrong', advance: 'auto' });
    expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineMissCount: 1 });

    res = driver.answer(dropped);
    expect(res).toEqual({ verdict: 'wrong', advance: 'auto' });
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
    driver.answer('zzz');
    res = driver.answer('zzz');
    expect(res).toEqual({ verdict: 'wrong', advance: 'auto' });
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
