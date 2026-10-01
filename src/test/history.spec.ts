// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import {
  appendSessionHistory,
  buildHistoryEntry,
  buildItems,
  deleteDeckFromStorage,
  emptyStats,
  getSessionHistory,
  MAX_HISTORY_ENTRIES,
  rankHardestCards,
  saveDeckToStorage,
  SessionHistoryEntry,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import { buildBackupPayload, importBackupPayload } from '../utils/backup';
import type { DeckItem, DrillItem, SessionState } from '../types';

const DECK: DeckItem[] = [
  { front: 'Tachy', back: 'fast heart rate' },
  { front: 'Hyper', back: 'blood pressure that stays above the normal range for a long time' },
  { front: 'itis', back: 'inflammation' },
];

function doneState(items: DrillItem[]): SessionState {
  return {
    items,
    phase: 'final',
    queue: [],
    stats: { ...emptyStats(), attempts: 12, misses: 2, reveals: 1, startTime: Date.UTC(2026, 8, 30, 9) },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: emptyStats(),
    config: { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' },
  };
}

const entry = (finishedAt: string): SessionHistoryEntry => ({
  finishedAt,
  stats: emptyStats(),
  config: { encodeReps: 3, chunkDifficulty: 35, ladderMode: 'cumulative' },
  cards: [],
});

describe('buildHistoryEntry', () => {
  it('records each card with its length, chunking, and cost', () => {
    const items = buildItems(DECK, 35, 'cumulative', undefined, undefined, false);
    items[1] = { ...items[1], attempts: 9, misses: 2, reveals: 1, finalMisses: 1, hardSpans: ['normal range'] };
    const e = buildHistoryEntry(doneState(items), new Date(Date.UTC(2026, 8, 30, 10)));

    expect(e.startedAt).toBe('2026-09-30T09:00:00.000Z');
    expect(e.finishedAt).toBe('2026-09-30T10:00:00.000Z');
    expect(e.stats).toMatchObject({ attempts: 12, misses: 2, reveals: 1 });
    expect(e.cards[0]).toMatchObject({ front: 'Tachy', words: 3, chunks: 0, attempts: 0, hardSpans: [] });
    expect(e.cards[1]).toMatchObject({
      front: 'Hyper',
      words: 12,
      attempts: 9,
      misses: 2,
      reveals: 1,
      finalMisses: 1,
      hardSpans: ['normal range'],
    });
    expect(e.cards[1].chunks).toBe(items[1].chunks!.length);
  });

  it('keeps a startTime of 0 (the epoch) instead of treating it as missing', () => {
    const items = buildItems(DECK, 35, 'cumulative', undefined, undefined, false);
    const state = { ...doneState(items), stats: { ...emptyStats(), startTime: 0 } };
    expect(buildHistoryEntry(state, new Date(0)).startedAt).toBe('1970-01-01T00:00:00.000Z');
    const { startTime: _startTime, ...noStartTime } = state.stats;
    expect(buildHistoryEntry({ ...state, stats: noStartTime }).startedAt).toBeUndefined();
  });
});

describe('rankHardestCards', () => {
  const items = buildItems(DECK, 35, 'cumulative', undefined, undefined, false);

  it('orders by misses + reveals + final-check misses, then attempts, then deck order', () => {
    const scored: DrillItem[] = [
      { ...items[0], misses: 1, attempts: 4 },
      { ...items[1], misses: 1, reveals: 1, attempts: 9 },
      { ...items[2], finalMisses: 1, attempts: 6 },
    ];
    expect(rankHardestCards(scored).map(i => i.front)).toEqual(['Hyper', 'itis', 'Tachy']);
  });

  it('leaves out cards with no trouble, and respects the limit', () => {
    const scored: DrillItem[] = [{ ...items[0], attempts: 5 }, { ...items[1], misses: 3 }, { ...items[2], misses: 1 }];
    expect(rankHardestCards(scored).map(i => i.front)).toEqual(['Hyper', 'itis']);
    expect(rankHardestCards(scored, 1).map(i => i.front)).toEqual(['Hyper']);
  });
});

describe('session history storage', () => {
  beforeEach(() => localStorage.clear());

  it('appends per deck and keeps only the newest entries', () => {
    for (let n = 0; n < MAX_HISTORY_ENTRIES + 3; n++) appendSessionHistory('cats', entry(`2026-09-${n}`));
    const log = getSessionHistory('cats');
    expect(log).toHaveLength(MAX_HISTORY_ENTRIES);
    expect(log[0].finishedAt).toBe('2026-09-3');
    expect(getSessionHistory('dogs')).toEqual([]);
  });

  it('is deleted with its deck', () => {
    saveDeckToStorage('Cats', DECK);
    appendSessionHistory('cats', entry('2026-09-30'));
    deleteDeckFromStorage('cats');
    expect(getSessionHistory('cats')).toEqual([]);
  });

  it('round-trips through a backup export and replace-import', () => {
    saveDeckToStorage('Cats', DECK);
    appendSessionHistory('cats', entry('2026-09-30'));
    const payload = buildBackupPayload();
    expect(payload.decks[0].history).toHaveLength(1);

    localStorage.clear();
    importBackupPayload(payload, 'replace');
    expect(getSessionHistory('cats')).toEqual([entry('2026-09-30')]);
  });

  it('imports a backup made before history existed', () => {
    saveDeckToStorage('Cats', DECK);
    const payload = buildBackupPayload();
    delete payload.decks[0].history;
    localStorage.clear();
    importBackupPayload(payload, 'replace');
    expect(getSessionHistory('cats')).toEqual([]);
  });
});
