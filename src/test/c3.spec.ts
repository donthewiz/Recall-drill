// C3 (batch the encode phase) tests. Doc acceptance criteria:
//   - a 13-card deck at batchSize: 5 produces batches of 5/5/3.
//   - encode trial order within a batch shows at least one item switch
//     before any item reaches 'ready'.
//   - resume after "Save and stop" restores the same batch and the same
//     per-item stage state.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  initSession,
  partitionIntoBatches,
  resolveBatchConfig,
  selectNextEncodeItem,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { DeckItem, SavedSessionState, SessionState } from '../types';
import { CHUNK_DIFFICULTY } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

// Every back is 9 words (deliberately > MIN_WORDS_TO_CHUNK, 8, so it still
// chunks at all) -> chunkText at CHUNK_DIFFICULTY (20%) yields 4 chunks,
// same mechanics as fixtures/deck.ts's FOUR_CHUNK_BACK -- so each card
// needs multiple stage-units (4 chunks + 3 combine windows under the
// cumulative ladder) before it's 'ready', which is what makes interleaving
// observable within a single item's encoding. The exact chunk count isn't
// asserted anywhere in this file -- only that there's more than one
// stage-unit per item -- so it doesn't matter that this no longer matches
// TWO_CHUNK_BACK's 2-chunk shape.
function makeChunkedDeck(count: number): DeckItem[] {
  return Array.from({ length: count }, (_, i) => ({
    front: `Q${i}`,
    back: `alpha${i} beta${i} gamma${i} delta${i} epsilon${i} zeta${i} eta${i} theta${i} iota${i}`,
  }));
}

function freshState(items: ReturnType<typeof buildItems>, batchSize: number, encodeReps = 1): SessionState {
  return initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative', batchSize },
  });
}

describe('partitionIntoBatches', () => {
  it('a 13-card deck at batchSize 5 produces batches of 5/5/3', () => {
    const items = buildItems(makeChunkedDeck(13), CHUNK_DIFFICULTY, 'cumulative', 5);
    const batches = partitionIntoBatches(items, 5);
    expect(batches.map(b => b.length)).toEqual([5, 5, 3]);
  });

  it('batchSize 0 (or omitted) is a single whole-deck batch', () => {
    const items = buildItems(makeChunkedDeck(13), CHUNK_DIFFICULTY, 'cumulative');
    expect(partitionIntoBatches(items, 0).length).toBe(1);
    expect(partitionIntoBatches(items).length).toBe(1);
  });
});

describe('selectNextEncodeItem', () => {
  it('round-robins over not-yet-ready items, skipping ready ones', () => {
    const items = buildItems(makeChunkedDeck(3), CHUNK_DIFFICULTY, 'cumulative', 3);
    const [batch] = partitionIntoBatches(items, 3);
    expect(selectNextEncodeItem(batch, SESSION_COMPLETE_ID)).toBe(batch[0]);
    expect(selectNextEncodeItem(batch, batch[0].id)).toBe(batch[1]);
    expect(selectNextEncodeItem(batch, batch[1].id)).toBe(batch[2]);
    expect(selectNextEncodeItem(batch, batch[2].id)).toBe(batch[0]); // wraps

    const readyBatch = batch.map((it, idx) => (idx === 1 ? { ...it, status: 'ready' as const } : it));
    expect(selectNextEncodeItem(readyBatch, readyBatch[0].id)).toBe(readyBatch[2]); // skips the ready one

    const allReady = batch.map(it => ({ ...it, status: 'ready' as const }));
    expect(selectNextEncodeItem(allReady, allReady[0].id)).toBeNull();
  });
});

describe('C3 acceptance: encode trial order within a batch interleaves before any item is ready', () => {
  it('visits more than one distinct item before the first item reaches ready', () => {
    const items = buildItems(makeChunkedDeck(5), CHUNK_DIFFICULTY, 'cumulative', 5);
    let state = freshState(items, 5, 1);

    const visitedBeforeReady = new Set<number>();
    for (let i = 0; i < 200; i++) {
      const trial = selectTrial(state);
      if (!trial) break;
      visitedBeforeReady.add(trial.itemId);
      if (state.items.some(it => it.status === 'ready')) break;
      state = applyAnswer(state, trial.target, { revealed: false }).state;
    }

    expect(visitedBeforeReady.size).toBeGreaterThan(1);
  });

  it('is fully massed (one item at a time) when there is only a single item -- batching never changes single-item behavior', () => {
    const items = buildItems(makeChunkedDeck(1), CHUNK_DIFFICULTY, 'cumulative', 5);
    let state = freshState(items, 5, 1);
    const itemId = selectTrial(state)!.itemId;

    for (let i = 0; i < 10 && state.phase === 'encode'; i++) {
      const trial = selectTrial(state);
      if (!trial) break;
      expect(trial.itemId).toBe(itemId);
      state = applyAnswer(state, trial.target, { revealed: false }).state;
    }
  });
});

// Drives a session to the exact moment the interstitial first appears
// (batch 0's items all mastered, more batches remain) -- always-correct
// answers, cycle-phase manual advances handled the same way
// SessionView/simulate.ts do.
function driveToFirstInterstitial(state: SessionState): SessionState {
  for (let i = 0; i < 2000 && state.phase !== 'batch-done'; i++) {
    const trial = selectTrial(state);
    if (!trial) throw new Error('session finished before reaching an interstitial');
    const result = applyAnswer(state, trial.target, { revealed: false });
    state = result.state;
    if (result.advance === 'manual' && state.phase === 'cycle') {
      state = applyNext(state);
    }
  }
  return state;
}

describe('C3 acceptance: resume after "Save and stop" restores the same batch and per-item state', () => {
  it('round-tripping through a SavedSessionState-shaped save reproduces the interstitial exactly', () => {
    // 7 items at batchSize 5 -> batches of [5, 2], so finishing batch 0 lands
    // on the interstitial with a second batch still to come.
    const items = buildItems(makeChunkedDeck(7), CHUNK_DIFFICULTY, 'cumulative', 5);
    let state = freshState(items, 5, 1);
    state = driveToFirstInterstitial(state);

    expect(state.phase).toBe('batch-done');
    expect(state.batchIndex).toBe(0);

    // Mirrors SessionView's persistState -> App.handleResumeSession round trip.
    const saved: SavedSessionState = {
      deckName: 'Test deck',
      phase: state.phase,
      queue: state.queue,
      stats: state.stats,
      items: state.items,
      encodeReps: state.config.encodeReps,
      chunkDifficulty: state.config.chunkDifficulty,
      stemTolerance: state.config.stemTolerance,
      ladderMode: state.config.ladderMode,
      batchIndex: state.batchIndex,
      batchSize: state.config.batchSize,
      batchStartStats: state.batchStartStats,
      timestamp: Date.now(),
    };
    // Round-trip through JSON, the way localStorage actually stores it.
    const reloaded: SavedSessionState = JSON.parse(JSON.stringify(saved));

    const { batchIndex, batchSize } = resolveBatchConfig(reloaded, reloaded.items);
    const resumedState: SessionState = initSession({
      items: reloaded.items,
      phase: reloaded.phase,
      queue: reloaded.queue,
      stats: reloaded.stats,
      currentId: SESSION_COMPLETE_ID,
      batchIndex,
      batchStartStats: reloaded.batchStartStats ?? reloaded.stats,
      config: {
        encodeReps: reloaded.encodeReps,
        chunkDifficulty: reloaded.chunkDifficulty ?? 35,
        stemTolerance: reloaded.stemTolerance ?? true,
        ladderMode: reloaded.ladderMode ?? 'cumulative',
        batchSize,
      },
    });

    expect(resumedState.phase).toBe('batch-done');
    expect(resumedState.batchIndex).toBe(state.batchIndex);
    expect(resumedState.items).toEqual(state.items);
    expect(resumedState.stats).toEqual(state.stats);
  });

  it('migrates a pre-C3 save (no batchIndex/batchSize) to batchIndex 0, batchSize items.length', () => {
    const items = buildItems(makeChunkedDeck(3), CHUNK_DIFFICULTY, 'cumulative');
    const legacySave: Pick<SavedSessionState, 'batchIndex' | 'batchSize'> = {};
    const resolved = resolveBatchConfig(legacySave, items);
    expect(resolved).toEqual({ batchIndex: 0, batchSize: items.length });
  });
});
