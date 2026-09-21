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
import {
  FULL_STAGE_BACK,
  TWO_CHUNK_BACK,
  TWO_CHUNK_CHUNKS,
  TWO_CHUNK_DIFFICULTY,
  CHUNK_DIFFICULTY,
} from './fixtures/deck';

describe('renderFirstLetterCue', () => {
  it('keeps the first character of each word and underscores the rest, preserving word count', () => {
    expect(renderFirstLetterCue('The heart pumps blood')).toBe('T__ h____ p____ b____');
  });

  it('leaves punctuation visible in place, only underscoring letters/digits', () => {
    expect(renderFirstLetterCue('blood.')).toBe('b____.');
  });

  it('leaves a one-character word as-is', () => {
    expect(renderFirstLetterCue('a b c')).toBe('a b c');
  });

  it('preserves the first character\'s original case', () => {
    expect(renderFirstLetterCue('Recall Drill')).toBe('R_____ D____');
  });

  // Punctuation resets the run, so the alphanumeric character right after it
  // gets its own reveal too -- "don't" surfaces both "d" and "t" ("d__'t"),
  // not just "d". This is the same rule exercised by the medical cases
  // below, just via an apostrophe instead of a hyphen or slash.
  it('reveals the first alphanumeric character of each run, even mid-word after punctuation', () => {
    expect(renderFirstLetterCue("don't stop")).toBe("d__'t s___");
  });

  // Regression coverage for a real bug: the original implementation revealed
  // index 0 of the *word*, not the first alphanumeric of each *run*. That's
  // indistinguishable from correct for an ordinary word (which is one run),
  // but medical combining-form word parts routinely lead with a hyphen or
  // slash -- e.g. suffixes like "-itis"/"-emia" and prefixes like "brady-".
  // Under the old rule, index 0 of "-itis" is the hyphen itself, so the
  // "revealed" character carries no information and every suffix card
  // rendered an identical, uninformative "-____". Do not simplify this back
  // to an index-0 check -- these cases exist specifically to catch that
  // regression.
  it('reveals the first alphanumeric of each run for medical word parts led/trailed by punctuation', () => {
    expect(renderFirstLetterCue('-itis')).toBe('-i___');
    expect(renderFirstLetterCue('-emia')).toBe('-e___');
    expect(renderFirstLetterCue('brady-')).toBe('b____-');
    expect(renderFirstLetterCue('cardi/o')).toBe('c____/o');
  });

  it('degenerate case: a single alphanumeric character after punctuation is left fully revealed', () => {
    expect(renderFirstLetterCue('-a')).toBe('-a');
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

  // C8b (Phase 9) replaced the chunks stage's firstLetter cue entirely with
  // an ungraded presentation -- this test originally covered firstLetter
  // there; see c8b.spec.ts for the presentation-specific coverage this test
  // was split into. Kept here (updated, not deleted) since it's still the
  // place documenting the chunks stage's full cue lifecycle across a miss
  // and a chunk-to-chunk transition.
  it("chunks stage: each chunk starts with a presentation, not firstLetter (C8b)", () => {
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

    expect(selectTrial(state)!.cue).toEqual({ kind: 'present' });

    // Acknowledging the presentation (whatever's "typed" is ignored) moves
    // to the first real, blind attempt -- never firstLetter.
    state = applyAnswer(state, 'anything', { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({ kind: 'none' });

    // A miss on the blind attempt resets to chunkStreak 0 -- re-presenting
    // the chunk, not escalating to a hint.
    state = applyAnswer(state, 'wrong', { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({ kind: 'present' });

    // Re-acknowledge, then answer the blind attempt correctly -> completes
    // chunk 0 -> chunk 1 starts back at its own presentation.
    state = applyAnswer(state, 'anything', { revealed: false }).state;
    state = applyAnswer(state, TWO_CHUNK_CHUNKS[0], { revealed: false }).state;
    expect(selectTrial(state)!.cue).toEqual({ kind: 'present' });
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

// C8b (Phase 9) narrowed this acceptance criterion deliberately: the chunks
// stage's attempt 0 is now an ungraded presentation that DOES show the
// complete target (see c8b.spec.ts) -- but it's explicitly not an
// "attempt" at all (no typing, no grading, verdict 'presented' rather than
// 'exact'/'wrong'), so it doesn't reintroduce the problem C5 fixed
// (transcription being graded as if it were recall). What C5's guarantee
// actually protects is that no *graded, typed* trial ever shows the
// complete target pre-attempt -- which still holds.
describe('C5 acceptance: no graded trial ever exposes the complete target before typing', () => {
  it('walking a full session (chunks -> combine -> cycle) never yields a graded cue that reveals the full text pre-attempt', () => {
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

    for (let i = 0; i < 200 && state.currentId !== SESSION_COMPLETE_ID; i++) {
      const trial = selectTrial(state);
      if (!trial) break;
      // selectTrial only ever produces 'firstLetter', 'none', or (chunks
      // stage attempt 0, C8b) 'present' -- 'full' is reveal-only and never
      // what the engine hands back for a fresh trial.
      expect(['firstLetter', 'none', 'present']).toContain(trial.cue.kind);
      if (trial.cue.kind === 'firstLetter') {
        expect(trial.cue.pattern).not.toBe(trial.target);
      }
      // 'present' is the one cue that does show the complete target --
      // acceptable because it's explicitly not a graded attempt (see the
      // describe block's header comment).
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
