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
// Phase 4 (C5) made every wrong verdict in the encode phase return
// `advance: 'manual'` instead of 'auto' (replacing the timed auto-retry with
// an explicit Enter/Next, so the diff is actually read and the C2 override
// stays reachable) -- LegacyEngine can never produce this, since it's a
// frozen pre-C5 snapshot and always returns 'auto' there. So this suite no
// longer hard-codes `advance` on encode-phase wrong-verdict results; see
// expectWrong() below, which checks only `verdict` and calls driver.next()
// when (and only when) the result says to -- the same pattern this suite
// already used for cycle-phase manual results. RealEngineDriver.next() is a
// no-op outside the cycle phase (see engineDriver.ts), so calling it
// unconditionally is safe for both drivers.
//
// Phase 8 (C8a) changed the chunks stage's advance criterion from
// "chunkStreak reaches encodeReps" to "one correct answer at cue level
// 'none'", independent of encodeReps -- so the "four-chunk card" scenario
// (encodeReps: 1, where old and new chunk-stage trial counts genuinely
// diverge: 1 correct answer per chunk under the old rule, always 2 under
// the new one) can no longer run identically against both drivers.
// LegacyEngine is a frozen pre-C8a snapshot and will never satisfy the new
// rule. That scenario's two variants now live separately: the original,
// verbatim, in characterization.legacy.spec.ts (proving LegacyEngine's old
// behavior is undisturbed), and a C8a-aware version in
// characterization.engine.spec.ts (same remediation/B1 coverage, updated
// chunk-walk). The "two-chunk card" scenario below stays here unmodified --
// it uses encodeReps: 2, where the old and new chunk criteria happen to
// require the same 2 trials per chunk, so it's still valid against both
// drivers.
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
  TWO_CHUNK_DIFFICULTY,
  CHUNK_DIFFICULTY,
} from './fixtures/deck';
import type { DriverAnswerResult, EngineDriver } from './reference/legacyEngine';

function expectWrong(driver: EngineDriver, res: DriverAnswerResult): void {
  expect(res.verdict).toBe('wrong');
  if (res.advance === 'manual') driver.next();
}

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
      expectWrong(driver, res);
      expect(driver.stats()).toEqual({ attempts: 1, misses: 1, nearMisses: 0, overrides: 0 });
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
      expect(driver.stats()).toEqual({ attempts: 3, misses: 1, nearMisses: 0, overrides: 0 });

      // Cycle miss: streak resets to 0, manual advance required.
      res = driver.answer('nope');
      expect(res).toEqual({ verdict: 'wrong', advance: 'manual' });
      expect(driver.snapshotItem(itemId)).toMatchObject({ cycleStreak: 0 });
      expect(driver.stats()).toEqual({ attempts: 4, misses: 2, nearMisses: 0, overrides: 0 });
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

      // This scenario stops here, one driver.next() short of fully finished:
      // what that next() does now diverges by driver (Phase 3: the real
      // engine enters the Final check instead of finishing; LegacyEngine,
      // frozen, still finishes immediately). See characterization.engine.spec.ts
      // and characterization.legacy.spec.ts for the driver-specific endings,
      // same split as the C8a chunk-criterion divergence noted above.
    });
  });

  describe('two-chunk card: chunks -> combine miss -> remediate -> combine -> ready', () => {
    it('walks the exact (stage,target,streak,status) sequence, correctly attributing the miss to only the culprit chunk (post-B1-fix)', () => {
      const driver = makeDriver();
      // Pinned to the exhaustive ladder (pre-C1): this scenario's assertions
      // are written around buildCombineSequence's original n(n-1)/2 window
      // shape and uniform encodeReps-per-window requirement. C1 (Phase 3)
      // adds a separate 'cumulative' (forward-chaining) scenario instead of
      // redesigning this one.
      driver.init([{ front: 'Q2', back: TWO_CHUNK_BACK }], {
        encodeReps: 2,
        chunkDifficulty: TWO_CHUNK_DIFFICULTY,
        ladderMode: 'exhaustive',
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
      // genuinely NOT at fault; only chunk 0 ("the mitochondria produces
      // most of") is missing. windowChunkCount=2 -> missThreshold=1 ->
      // remediates immediately. Post-B1-fix: findAllCulpritChunks uses the
      // LCS alignment, so it correctly flags only chunk 0, not both.
      const res = driver.answer(TWO_CHUNK_CHUNKS[1]);
      expectWrong(driver, res);
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

  describe('cycle phase: miss resets streak, reinsertion keeps the item in the queue', () => {
    it('walks miss -> correct -> correct -> mastered', () => {
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
      // Stops here, one driver.next() short of fully finished -- see the
      // full-stage-card scenario above for why what that next() does now
      // diverges by driver (Phase 3's Final check, real-engine-only).
      expect(driver.stats()).toEqual({ attempts: 4, misses: 1, nearMisses: 0, overrides: 0 });
    });
  });
}
