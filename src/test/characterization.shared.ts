// Characterization suite for the session state machine. Originally written in
// Phase 0 against src/components/SessionView.tsx's pre-fix behavior (including
// bugs B1/B2), and run against both reference/legacyEngine.ts (a frozen
// synchronous transcription of the pre-fix handleCheck/advanceEncode/
// advanceCycle) and the pure drillEngine.ts reducer, to prove the Phase 0
// extraction was behavior-preserving.
//
// Phase 1 (see docs/V2-HANDOFF.md) deliberately fixes B1 and B2, so this
// shared suite's B1-related assertions were UPDATED to expect the correct,
// post-fix culprit attribution (see the two-chunk and four-chunk describe
// blocks below) -- this suite still runs against both drivers because B1's
// fix lives in findAllCulpritChunks, a low-level helper legacyEngine.ts
// imports live from drillEngine.ts rather than hand-transcribing, so it picks
// the fix up automatically. B2's test was MOVED OUT of this shared suite
// entirely, into characterization.engine.spec.ts -- legacyEngine.ts's
// showAnswer()/answer() never read a revealed flag at all (that's part of the
// hand-transcribed orchestration layer B2 changes, not a shared low-level
// helper), so it can never satisfy the fixed behavior, and there's no more
// value in continuing to prove it still exhibits the old bug (already proven
// and committed in Phase 0's history).
//
// Out of scope for this suite:
//   - B5 (unguarded double-Enter race) -- a timing/re-entrancy issue that needs
//     a DOM-level harness to observe meaningfully; not characterized here.
//   - App.tsx's handleFinishSession stale-persist quirk -- lives outside the
//     extraction target (SessionView/drillEngine), not covered here.
import { describe, it, expect } from 'vitest';
import {
  FULL_STAGE_BACK,
  TWO_CHUNK_BACK,
  TWO_CHUNK_CHUNKS,
  FOUR_CHUNK_BACK,
  FOUR_CHUNK_CHUNKS,
  CHUNK_DIFFICULTY,
} from './fixtures/deck';
import type { EngineDriver } from './reference/legacyEngine';

export function runCharacterizationSuite(makeDriver: () => EngineDriver): void {
  describe('full-stage card: encode -> cycle -> mastered', () => {
    it('walks the exact (stage,target,streak,status) sequence', () => {
      const driver = makeDriver();
      driver.init([{ front: 'Q1', back: FULL_STAGE_BACK }], { encodeReps: 2 });

      let trial = driver.currentTrial();
      expect(trial).toEqual({
        itemId: expect.any(Number),
        stage: 'full',
        target: FULL_STAGE_BACK,
        isBlind: false,
      });
      const itemId = trial!.itemId;
      expect(driver.snapshotItem(itemId)).toMatchObject({
        stage: 'full',
        status: 'encoding',
        encodeStreak: 0,
      });

      // A miss first: streak stays at 0, misses tallied, same trial.
      let res = driver.answer('totally wrong');
      expect(res).toEqual({ verdict: 'wrong', advance: 'auto' });
      expect(driver.stats()).toEqual({ attempts: 1, misses: 1 });
      expect(driver.snapshotItem(itemId)).toMatchObject({ encodeStreak: 0, status: 'encoding' });

      // First correct: streak 1, still 'encoding' (encodeReps=2), now blind.
      res = driver.answer(FULL_STAGE_BACK);
      expect(res).toEqual({ verdict: 'exact', advance: 'auto' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ encodeStreak: 1, status: 'encoding' });
      trial = driver.currentTrial();
      expect(trial).toEqual({ itemId, stage: 'full', target: FULL_STAGE_BACK, isBlind: true });

      // Second correct: streak meets encodeReps -> status 'ready' -> auto-advances
      // to cycle phase (only item in deck, nothing left to encode).
      res = driver.answer(FULL_STAGE_BACK);
      expect(res).toEqual({ verdict: 'exact', advance: 'auto' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ status: 'ready' });
      trial = driver.currentTrial();
      expect(trial).toEqual({ itemId, stage: 'cycle', target: FULL_STAGE_BACK, isBlind: true });
      expect(driver.stats()).toEqual({ attempts: 3, misses: 1 });

      // Cycle miss: streak resets to 0, manual advance required.
      res = driver.answer('nope');
      expect(res).toEqual({ verdict: 'wrong', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 0 });
      expect(driver.stats()).toEqual({ attempts: 4, misses: 2 });
      driver.next();

      // Cycle correct, not yet mastered (needs streak 2).
      res = driver.answer(FULL_STAGE_BACK);
      expect(res).toEqual({ verdict: 'exact', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 1, status: 'ready' });
      driver.next();

      // Cycle correct again -> mastered.
      res = driver.answer(FULL_STAGE_BACK);
      expect(res).toEqual({ verdict: 'exact', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 2, status: 'mastered' });
      expect(driver.isFinished()).toBe(false);
      driver.next();

      expect(driver.isFinished()).toBe(true);
    });
  });

  describe('two-chunk card: chunks -> combine miss -> remediate -> combine -> ready', () => {
    it('walks the exact (stage,target,streak,status) sequence, correctly attributing the miss to only the culprit chunk (post-B1-fix)', () => {
      const driver = makeDriver();
      driver.init([{ front: 'Q2', back: TWO_CHUNK_BACK }], {
        encodeReps: 2,
        chunkDifficulty: CHUNK_DIFFICULTY,
      });

      let trial = driver.currentTrial()!;
      const itemId = trial.itemId;
      expect(trial).toEqual({ itemId, stage: 'chunks', target: TWO_CHUNK_CHUNKS[0], isBlind: false });

      // Chunk 0 to streak 2 -> advances to chunk 1.
      driver.answer(TWO_CHUNK_CHUNKS[0]);
      driver.answer(TWO_CHUNK_CHUNKS[0]);
      expect(driver.snapshotItem(itemId)).toMatchObject({ chunkIndex: 1, chunkStreak: 0, stage: 'chunks' });
      trial = driver.currentTrial()!;
      expect(trial).toEqual({ itemId, stage: 'chunks', target: TWO_CHUNK_CHUNKS[1], isBlind: false });

      // Chunk 1 to streak 2 -> chunks exhausted -> stage 'combine'.
      driver.answer(TWO_CHUNK_CHUNKS[1]);
      driver.answer(TWO_CHUNK_CHUNKS[1]);
      expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineSeqIdx: 0, combineStreak: 0 });
      trial = driver.currentTrial()!;
      expect(trial).toEqual({ itemId, stage: 'combine', target: TWO_CHUNK_BACK, isBlind: false });

      // Miss the combine window by typing only the second chunk's content --
      // everything the user typed matches chunk 1 in order, so chunk 1 is
      // genuinely NOT at fault; only chunk 0 ("the mitochondria") is missing.
      // windowChunkCount=2 -> missThreshold=1 -> remediates immediately.
      // Post-B1-fix: findAllCulpritChunks uses the LCS alignment, so it
      // correctly flags only chunk 0, not both.
      const res = driver.answer('makes cell energy');
      expect(res).toEqual({ verdict: 'wrong', advance: 'auto' });
      expect(driver.snapshotItem(itemId)).toMatchObject({
        stage: 'remediate',
        combineMissCount: 0,
        remediateStackLen: 1,
        remediateQueueLen: 0,
      });
      trial = driver.currentTrial()!;
      expect(trial).toEqual({
        itemId,
        stage: 'remediate',
        target: TWO_CHUNK_CHUNKS[0],
        isBlind: false,
      });

      // Resolve the single remediate spot -> queue already empty -> resumes
      // combine at the window that originally failed.
      driver.answer(TWO_CHUNK_CHUNKS[0]);
      driver.answer(TWO_CHUNK_CHUNKS[0]);
      expect(driver.snapshotItem(itemId)).toMatchObject({ stage: 'combine', combineSeqIdx: 0, combineStreak: 0 });
      trial = driver.currentTrial()!;
      expect(trial).toEqual({ itemId, stage: 'combine', target: TWO_CHUNK_BACK, isBlind: false });

      // Now pass the combine window for real -> status 'ready' -> only item
      // in deck -> auto-advances straight to cycle phase.
      driver.answer(TWO_CHUNK_BACK);
      driver.answer(TWO_CHUNK_BACK);
      expect(driver.snapshotItem(itemId)).toMatchObject({ status: 'ready' });
      trial = driver.currentTrial()!;
      expect(trial).toEqual({ itemId, stage: 'cycle', target: TWO_CHUNK_BACK, isBlind: true });
    });
  });

  describe('four-chunk card: post-B1-fix culprit attribution + full remediate branch coverage', () => {
    it('flags only the chunks that actually mismatch, not the whole window (B1 fixed)', () => {
      const driver = makeDriver();
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

  describe('cycle phase: miss resets streak, reinsertion keeps the item in the queue', () => {
    it('walks miss -> correct -> correct -> mastered -> session finished', () => {
      const driver = makeDriver();
      driver.init([{ front: 'Q5', back: FULL_STAGE_BACK }], { encodeReps: 1 });
      const itemId = driver.currentTrial()!.itemId;

      // Reach 'ready' then cycle immediately (encodeReps=1, only item in deck).
      driver.answer(FULL_STAGE_BACK);
      expect(driver.currentTrial()).toEqual({ itemId, stage: 'cycle', target: FULL_STAGE_BACK, isBlind: true });

      let res = driver.answer('wrong');
      expect(res).toEqual({ verdict: 'wrong', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 0 });
      driver.next();

      res = driver.answer(FULL_STAGE_BACK);
      expect(res).toEqual({ verdict: 'exact', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 1, status: 'ready' });
      driver.next();

      res = driver.answer(FULL_STAGE_BACK);
      expect(res).toEqual({ verdict: 'exact', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 2, status: 'mastered' });
      expect(driver.isFinished()).toBe(false);

      driver.next();
      expect(driver.isFinished()).toBe(true);
      expect(driver.stats()).toEqual({ attempts: 4, misses: 1 });
    });
  });
}
