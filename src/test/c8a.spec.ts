// C8a (chunk-stage criterion, part 1) tests. Doc acceptance criteria:
//   for any encodeReps value, a chunk needs exactly one correct cued
//   answer followed by exactly one correct blind ('none') answer to
//   advance -- never fewer, never more, and never encodeReps-many. Combine's
//   final window and the full stage are unaffected.
//
// Updated for C8b (Phase 9, committed after this file was first written):
// the "cued answer" step is no longer a graded 'firstLetter' typing attempt
// -- it's now an ungraded presentation (verdict 'presented', see
// c8b.spec.ts). C8a's own acceptance criterion (exactly 2 stage-units per
// chunk, independent of encodeReps) is otherwise unchanged, so this file
// keeps testing it against the shipped (post-C8b) mechanism rather than a
// transitional state nothing running today actually exhibits.
import { describe, expect, it } from 'vitest';
import { applyAnswer, buildItems, initSession, normalizeItem, SESSION_COMPLETE_ID } from '../utils/drillEngine';
import type { SessionState } from '../types';
import { FOUR_CHUNK_BACK, FOUR_CHUNK_CHUNKS, FULL_STAGE_BACK, CHUNK_DIFFICULTY } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function freshState(encodeReps: number): SessionState {
  return initSession({
    items: buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY, 'cumulative'),
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
  });
}

describe.each([1, 2, 3, 5])('C8a: a chunk needs exactly 1 cued + 1 blind at encodeReps=%i', encodeReps => {
  it('does not advance on the cued attempt alone, and does not need more than one blind success', () => {
    let state = freshState(encodeReps);
    const itemId = state.currentId;
    const chunk0 = FOUR_CHUNK_CHUNKS[0];

    // Cued attempt (chunkStreak 0): an ungraded presentation as of C8b --
    // acknowledging it must NOT advance chunkIndex, whatever was "typed".
    let result = applyAnswer(state, chunk0, { revealed: false });
    expect(result.verdict).toBe('presented');
    state = result.state;
    let item = state.items.find(i => i.id === itemId)!;
    expect(item.chunkIndex).toBe(0);
    expect(item.chunkStreak).toBe(1);

    // Blind attempt (chunkStreak 1): correct, advances exactly once --
    // regardless of encodeReps.
    result = applyAnswer(state, chunk0, { revealed: false });
    expect(result.verdict).toBe('exact');
    state = result.state;
    item = state.items.find(i => i.id === itemId)!;
    expect(item.chunkIndex).toBe(1);
    expect(item.chunkStreak).toBe(0);
  });
});

describe('C8a: combine\'s final window and the full stage are unaffected', () => {
  it('the full stage still needs encodeReps consecutive blind successes', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FULL_STAGE_BACK }], CHUNK_DIFFICULTY),
      phase: 'encode',
      queue: [],
      stats: { ...zeroStats },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { ...zeroStats },
      config: { encodeReps: 3, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });
    const itemId = state.currentId;

    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state;
    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state;
    let item = state.items.find(i => i.id === itemId)!;
    expect(item.status).toBe('encoding'); // 2 of 3 -- not ready yet

    state = applyAnswer(state, FULL_STAGE_BACK, { revealed: false }).state;
    item = state.items.find(i => i.id === itemId)!;
    expect(item.status).toBe('ready'); // 3rd rep -- encodeReps still governs this stage
  });

  it('the final combine window still needs encodeReps consecutive blind successes', () => {
    let state = freshState(3);
    const itemId = state.currentId;

    // Walk all 4 chunks (1 cued + 1 blind each, per C8a, regardless of encodeReps).
    for (const chunk of FOUR_CHUNK_CHUNKS) {
      state = applyAnswer(state, chunk, { revealed: false }).state;
      state = applyAnswer(state, chunk, { revealed: false }).state;
    }
    let item = state.items.find(i => i.id === itemId)!;
    expect(item.stage).toBe('combine');

    // Intermediate cumulative windows still need only 1 rep each (C1, untouched).
    state = applyAnswer(state, [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1]].join(' '), {
      revealed: false,
    }).state;
    state = applyAnswer(
      state,
      [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1], FOUR_CHUNK_CHUNKS[2]].join(' '),
      { revealed: false }
    ).state;
    item = state.items.find(i => i.id === itemId)!;
    expect(item.combineSeqIdx).toBe(2); // final window {1,4}

    // Final window: encodeReps=3 still required, untouched by C8a.
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    item = state.items.find(i => i.id === itemId)!;
    expect(item.status).toBe('encoding'); // 2 of 3 -- not ready yet

    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    item = state.items.find(i => i.id === itemId)!;
    expect(item.status).toBe('ready'); // 3rd rep on the final window
  });
});

describe('C8a migration: normalizeItem clamps a pre-C8a chunkStreak into {0, 1}', () => {
  it('clamps a legacy mid-chunk chunkStreak (accumulated under the old encodeReps-per-chunk rule) down to 1', () => {
    const legacy = {
      id: 0,
      front: 'Q',
      back: FOUR_CHUNK_BACK,
      status: 'encoding',
      encodeStreak: 0,
      cycleStreak: 0,
      chunks: FOUR_CHUNK_CHUNKS,
      chunkIndex: 1,
      chunkStreak: 2, // impossible under C8a's {0,1} range -- a pre-C8a save
      combineSeq: null,
      combineSeqIdx: 0,
      combineStreak: 0,
      combineMissCount: 0,
      remediateStack: [],
      remediateQueue: [],
      remediateReturnSeqIdx: 0,
      stage: 'chunks',
    };
    const normalized = normalizeItem(legacy);
    expect(normalized.chunkStreak).toBe(1);
  });

  it('leaves a valid {0, 1} chunkStreak untouched', () => {
    const legacy = {
      id: 0,
      front: 'Q',
      back: FOUR_CHUNK_BACK,
      status: 'encoding',
      chunks: FOUR_CHUNK_CHUNKS,
      chunkIndex: 1,
      chunkStreak: 1,
      stage: 'chunks',
    };
    expect(normalizeItem(legacy).chunkStreak).toBe(1);

    const legacyZero = { ...legacy, chunkStreak: 0 };
    expect(normalizeItem(legacyZero).chunkStreak).toBe(0);
  });
});
