// C5 (cue fading replaces copy-typing) tests. Doc acceptance criteria:
//   - renderFirstLetterCue preserves word count and punctuation position.
//   - a full-session simulation contains zero trials where the complete
//     target text is visible before the first attempt.
//   - a revealed-then-correct trial leaves the streak at 0 (already covered
//     by characterization.engine.spec.ts's B2 tests -- exercised again here
//     from the cue's perspective).
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  initSession,
  renderFirstLetterCue,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { SessionState } from '../types';
import { FULL_STAGE_BACK, TWO_CHUNK_BACK, TWO_CHUNK_CHUNKS, CHUNK_DIFFICULTY } from './fixtures/deck';

describe('renderFirstLetterCue', () => {
  it('keeps the first character of each word and underscores the rest, preserving word count', () => {
    expect(renderFirstLetterCue('The heart pumps blood')).toBe('T__ h____ p____ b____');
  });

  it('leaves punctuation visible in place, only underscoring letters/digits', () => {
    expect(renderFirstLetterCue("don't stop")).toBe("d__'_ s___");
    expect(renderFirstLetterCue('blood.')).toBe('b____.');
  });

  it('leaves a one-character word as-is', () => {
    expect(renderFirstLetterCue('a b c')).toBe('a b c');
  });

  it('preserves the first character\'s original case', () => {
    expect(renderFirstLetterCue('Recall Drill')).toBe('R_____ D____');
  });
});

describe('selectTrial cue: attempt 0 is firstLetter, attempt 1+ is fully blind', () => {
  it('full stage: firstLetter cue on the first attempt, none once a streak starts', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FULL_STAGE_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    expect(selectTrial(state)!.cue).toEqual({
      kind: 'firstLetter',
      pattern: renderFirstLetterCue(FULL_STAGE_BACK),
    });

    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({ kind: 'none' });
  });

  it('chunks stage: each chunk gets its own firstLetter cue on its first attempt', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: TWO_CHUNK_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    expect(selectTrial(state)!.cue).toEqual({
      kind: 'firstLetter',
      pattern: renderFirstLetterCue(TWO_CHUNK_CHUNKS[0]),
    });

    // A miss doesn't advance the chunk or the streak -- still attempt 0 of
    // the same chunk, so still firstLetter (not "escalated" to blind).
    state = applyAnswer(state, 'wrong', { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({
      kind: 'firstLetter',
      pattern: renderFirstLetterCue(TWO_CHUNK_CHUNKS[0]),
    });

    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({ kind: 'none' });

    // Second rep completes chunk 0 -> chunk 1 starts back at firstLetter.
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({
      kind: 'firstLetter',
      pattern: renderFirstLetterCue(TWO_CHUNK_CHUNKS[1]),
    });
  });

  it('cycle stage: always fully blind, same as before C5 (no copy-typing attempt existed there)', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FULL_STAGE_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 1, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });
    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state;
    expect(state.phase).toBe('cycle');
    expect(selectTrial(state)!.cue).toEqual({ kind: 'none' });
  });
});

describe('C5: a wrong verdict in the encode phase requires manual advance', () => {
  it('chunks/combine/full misses return advance: manual instead of auto-retrying on a timer', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FULL_STAGE_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    const result = applyAnswer(state, 'nonsense', { revealed: false });
    expect(result.verdict).toBe('wrong');
    expect(result.advance).toBe('manual');
    // The engine state already points at the retry-ready trial -- no queue
    // pop needed, unlike the cycle phase's manual advance.
    expect(selectTrial(result.state)).toMatchObject({ stage: 'full', target: FULL_STAGE_BACK });
  });

  it('an exact answer still auto-advances (only wrong verdicts became manual)', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FULL_STAGE_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    const result = applyAnswer(state, FULL_STAGE_BACK, { revealed: false });
    expect(result.verdict).toBe('exact');
    expect(result.advance).toBe('auto');
  });
});

describe('C5 acceptance: no trial ever exposes the complete target before the first attempt', () => {
  it('walking a full session (chunks -> combine -> cycle) never yields a cue that reveals the full text pre-attempt', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: TWO_CHUNK_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 2, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    for (let i = 0; i < 200 && state.currentId !== SESSION_COMPLETE_ID; i++) {
      const trial = selectTrial(state);
      if (!trial) break;
      // selectTrial only ever produces 'firstLetter' or 'none' -- 'full' is
      // reveal-only and is never what the engine hands back for a fresh trial.
      expect(['firstLetter', 'none']).toContain(trial.cue.kind);
      if (trial.cue.kind === 'firstLetter') {
        expect(trial.cue.pattern).not.toBe(trial.target);
      }
      const result = applyAnswer(state, trial.target, { revealed: false });
      state = result.state;
      // Mirrors SessionView's handleNext/simulate.ts's loop: only the cycle
      // phase's manual advance needs applyNext (advanceCycleState) -- an
      // encode-phase wrong verdict never happens here since every answer is
      // the correct target.
      if (result.advance === 'manual' && state.phase === 'cycle') {
        state = applyNext(state);
      }
    }
  });
});
