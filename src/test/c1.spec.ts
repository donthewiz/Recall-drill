// C1 (forward-chaining combine ladder) tests. Doc acceptance criteria:
//   buildCombineSequence(6, 'cumulative').length === 5
//   buildCombineSequence(6, 'exhaustive').length === 15
// plus an end-to-end trial-count check matching the doc's own worked example
// (4-chunk answer, encodeReps=3: 12 chunk + (1+1+3) combine + 2 cycle = 19).
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildCombineSequence,
  buildItems,
  initSession,
  requiredRepsForWindow,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { SessionState } from '../types';
import { FOUR_CHUNK_BACK, FOUR_CHUNK_CHUNKS, CHUNK_DIFFICULTY } from './fixtures/deck';

describe('buildCombineSequence', () => {
  it('cumulative (forward chaining): n-1 growing-prefix windows', () => {
    const seq = buildCombineSequence(6, 'cumulative');
    expect(seq.length).toBe(5);
    expect(seq).toEqual([
      { start: 1, end: 2 },
      { start: 1, end: 3 },
      { start: 1, end: 4 },
      { start: 1, end: 5 },
      { start: 1, end: 6 },
    ]);
  });

  it('exhaustive: n(n-1)/2 windows, unchanged from the original ladder', () => {
    const seq = buildCombineSequence(6, 'exhaustive');
    expect(seq.length).toBe(15);
  });

  it('defaults to cumulative when no mode is given', () => {
    expect(buildCombineSequence(4)).toEqual(buildCombineSequence(4, 'cumulative'));
  });
});

describe('requiredRepsForWindow', () => {
  it('requires just 1 rep for every window except the final (whole-answer) one', () => {
    const seq = buildCombineSequence(4, 'cumulative');
    const reps = seq.map(w => requiredRepsForWindow(w, 4, 3));
    expect(reps).toEqual([1, 1, 3]); // {1,2}, {1,3}, {1,4} with encodeReps=3
  });
});

function walkChunksToCombine(state: SessionState, chunks: string[], encodeReps: number): SessionState {
  for (const chunk of chunks) {
    for (let i = 0; i < encodeReps; i++) {
      state = applyAnswer(state, chunk, { revealed: false }).state;
    }
  }
  return state;
}

describe('C1 end-to-end: cumulative ladder matches the doc\'s worked trial count', () => {
  it('4-chunk answer, encodeReps=3: 12 chunk + (1+1+3) combine + 2 cycle = 19 trials, 0 misses', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY, 'cumulative'),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      config: { encodeReps: 3, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    // 4 chunks x 3 reps = 12 trials.
    state = walkChunksToCombine(state, FOUR_CHUNK_CHUNKS, 3);
    let item = state.items.find(i => i.id === state.currentId)!;
    expect(item.stage).toBe('combine');
    expect(item.combineSeq).toEqual([
      { start: 1, end: 2 },
      { start: 1, end: 3 },
      { start: 1, end: 4 },
    ]);

    // Window {1,2}: needs only 1 rep.
    const w12 = [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1]].join(' ');
    state = applyAnswer(state, w12, { revealed: false }).state;
    item = state.items.find(i => i.id === state.currentId)!;
    expect(item.combineSeqIdx).toBe(1);

    // Window {1,3}: needs only 1 rep.
    const w13 = [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1], FOUR_CHUNK_CHUNKS[2]].join(' ');
    state = applyAnswer(state, w13, { revealed: false }).state;
    item = state.items.find(i => i.id === state.currentId)!;
    expect(item.combineSeqIdx).toBe(2);

    // Window {1,4} (the whole answer): needs the full encodeReps=3.
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    expect(state.phase).toBe('cycle'); // only item in deck -> auto-advances to cycle

    // Cycle: 2 correct answers to master (manual advance between them).
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;
    state = applyNext(state);
    state = applyAnswer(state, FOUR_CHUNK_BACK, { revealed: false }).state;

    expect(state.stats).toEqual({ attempts: 19, misses: 0, nearMisses: 0, overrides: 0 });
    const finalItem = state.items[0];
    expect(finalItem.status).toBe('mastered');
  });
});

describe('C1 remediation still works correctly under the cumulative ladder', () => {
  it('a genuinely wrong combine answer on the final window still enters remediate and B1 attributes correctly', () => {
    let state: SessionState = initSession({
      items: buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], CHUNK_DIFFICULTY, 'cumulative'),
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      config: { encodeReps: 1, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    });

    // encodeReps=1: each chunk/window needs only 1 rep, except the final
    // combine window which (per requiredRepsForWindow) also needs just 1
    // here since encodeReps itself is 1.
    state = walkChunksToCombine(state, FOUR_CHUNK_CHUNKS, 1);
    // Walk the two intermediate cumulative windows correctly.
    state = applyAnswer(state, [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1]].join(' '), {
      revealed: false,
    }).state;
    state = applyAnswer(
      state,
      [FOUR_CHUNK_CHUNKS[0], FOUR_CHUNK_CHUNKS[1], FOUR_CHUNK_CHUNKS[2]].join(' '),
      { revealed: false }
    ).state;

    let item = state.items.find(i => i.id === state.currentId)!;
    expect(item.stage).toBe('combine');
    expect(item.combineSeqIdx).toBe(2); // final window {1,4}

    // Drop "green" from the final window -- windowChunkCount=4 -> missThreshold=2.
    const dropped = 'large trees grow slowly near the quiet river';
    state = applyAnswer(state, dropped, { revealed: false }).state;
    state = applyAnswer(state, dropped, { revealed: false }).state;

    item = state.items.find(i => i.id === state.currentId)!;
    expect(item.stage).toBe('remediate');
    // B1 fix still applies: only the chunk containing the dropped word is queued.
    expect(item.remediateStack.length).toBe(1);
    expect(item.remediateStack[0].text).toBe(FOUR_CHUNK_CHUNKS[0]);
  });
});
