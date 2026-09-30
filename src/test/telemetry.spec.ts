// Per-card telemetry and reveal accounting, recorded by applyAnswer's
// recordTrialTelemetry wrapper, plus the accuracy formula that uses it.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  computeAccuracyPercent,
  computeBatchSummary,
  emptyStats,
  initSession,
  normalizeItem,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { DeckItem, SessionState } from '../types';

const DECK: DeckItem[] = [
  { front: 'Tachy', back: 'fast heart rate' },
  { front: 'Hyper', back: 'blood pressure that stays above the normal range for a long time' },
];
const SHORT = 0;
const LONG = 1;

function fresh(): SessionState {
  return initSession({
    items: buildItems(DECK, 35, 'cumulative', undefined, undefined, false),
    phase: 'encode',
    queue: [],
    stats: emptyStats(),
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: emptyStats(),
    config: { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative', cycleOrder: 'inOrder' },
  });
}

function playUntil(stop: (s: SessionState) => boolean): SessionState {
  let s = fresh();
  for (let guard = 0; !stop(s); guard++) {
    expect(guard).toBeLessThan(400);
    const t = selectTrial(s)!;
    const r = applyAnswer(s, t.cue.kind === 'present' ? '' : t.target, { revealed: false });
    s = r.advance === 'manual' ? applyNext(r.state) : r.state;
  }
  return s;
}

const item = (s: SessionState, id: number) => s.items.find(i => i.id === id)!;

describe('per-card telemetry', () => {
  it('counts a correct answer as an attempt on that card only', () => {
    const s = fresh();
    expect(s.currentId).toBe(SHORT);
    const r = applyAnswer(s, 'fast heart rate', { revealed: false });
    expect(item(r.state, SHORT)).toMatchObject({ attempts: 1, misses: 0, reveals: 0, nearMisses: 0 });
    expect(item(r.state, LONG).attempts).toBeUndefined();
  });

  it('records a wrong answer as a miss on the card', () => {
    const r = applyAnswer(fresh(), 'slow heart', { revealed: false });
    expect(r.verdict).toBe('wrong');
    expect(item(r.state, SHORT)).toMatchObject({ attempts: 1, misses: 1, reveals: 0 });
    expect(r.state.stats.misses).toBe(1);
  });

  it('records a reveal on the card and in stats.reveals, never as a miss', () => {
    const r = applyAnswer(fresh(), 'fast heart rate', { revealed: true });
    expect(r.verdict).toBe('revealed');
    expect(item(r.state, SHORT)).toMatchObject({ attempts: 1, misses: 0, reveals: 1 });
    expect(r.state.stats).toMatchObject({ attempts: 1, misses: 0, reveals: 1 });
  });

  it('records a near-miss', () => {
    const r = applyAnswer(fresh(), 'the fast heart rate', { revealed: false });
    expect(r.verdict).toBe('near');
    expect(item(r.state, SHORT)).toMatchObject({ attempts: 1, misses: 0, nearMisses: 1 });
  });

  it('does not count a chunk presentation', () => {
    const s = playUntil(st => st.currentId === LONG);
    expect(selectTrial(s)!.cue.kind).toBe('present');
    const r = applyAnswer(s, '', { revealed: false });
    expect(r.verdict).toBe('presented');
    expect(item(r.state, LONG).attempts).toBeUndefined();
  });

  it('records the chunk that broke while combining as a hard span', () => {
    const s = playUntil(
      st => st.currentId === LONG && item(st, LONG).stage === 'combine' && item(st, LONG).combineSeqIdx === 0
    );
    const it0 = item(s, LONG);
    const [first, second] = it0.chunks!;
    const r = applyAnswer(s, `${first} zzz qqq`, { revealed: false });
    expect(r.verdict).toBe('wrong');
    expect(item(r.state, LONG).stage).toBe('remediate');
    expect(item(r.state, LONG).hardSpans).toEqual([second]);
  });

  it('survives normalizeItem (a save/resume round trip)', () => {
    const r = applyAnswer(fresh(), 'slow heart', { revealed: false });
    const saved = JSON.parse(JSON.stringify(item(r.state, SHORT)));
    expect(normalizeItem(saved)).toMatchObject({ attempts: 1, misses: 1, reveals: 0, nearMisses: 0 });
  });
});

describe('computeAccuracyPercent', () => {
  it('excludes reveals from the correct count', () => {
    expect(computeAccuracyPercent({ attempts: 10, misses: 2, reveals: 3 })).toBe(50);
  });

  it('treats a missing reveals field (an old save) as 0', () => {
    expect(computeAccuracyPercent({ attempts: 4, misses: 1 })).toBe(75);
  });

  it('reads 100 with no attempts and never goes negative', () => {
    expect(computeAccuracyPercent({ attempts: 0, misses: 0, reveals: 0 })).toBe(100);
    expect(computeAccuracyPercent({ attempts: 1, misses: 1, reveals: 1 })).toBe(0);
  });

  it('is what the batch summary reports', () => {
    const s = fresh();
    const r = applyAnswer(s, 'fast heart rate', { revealed: true });
    expect(computeBatchSummary(r.state).accuracyPercent).toBe(0);
  });
});
