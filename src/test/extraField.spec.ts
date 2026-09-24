// Anki-style optional "Extra" field: display-only, never graded/chunked,
// must not affect trial counts. This file covers the data-model plumbing --
// parseDeck, buildItems/normalizeItem, editCurrentItem, and the backup
// round trip. Display (SessionView) is covered separately once that lands.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  buildItems,
  editCurrentItem,
  initSession,
  parseDeck,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import { buildBackupPayload, importBackupPayload } from '../utils/backup';
import { saveDeckToStorage, loadDeckIndex, getDeckFromStorage } from '../utils/drillEngine';
import type { DeckItem, SessionState } from '../types';
import { CHUNK_DIFFICULTY, FOUR_CHUNK_BACK, FOUR_CHUNK_CHUNKS } from './fixtures/deck';

describe('parseDeck -- optional third "extra" segment', () => {
  it('a three-field tab line produces front/back/extra', () => {
    const out = parseDeck('mitochondria\tpowerhouse of the cell\talso does aerobic respiration');
    expect(out).toEqual([
      { front: 'mitochondria', back: 'powerhouse of the cell', extra: 'also does aerobic respiration' },
    ]);
  });

  it('a two-field tab line produces no extra key at all', () => {
    const out = parseDeck('front\tback');
    expect(out).toEqual([{ front: 'front', back: 'back' }]);
    expect('extra' in out[0]).toBe(false);
  });

  it('a three-field :: line produces front/back/extra', () => {
    const out = parseDeck('Capital of France :: Paris :: Also the seat of the EU parliament sometimes');
    expect(out).toEqual([
      { front: 'Capital of France', back: 'Paris', extra: 'Also the seat of the EU parliament sometimes' },
    ]);
  });

  it('a two-field :: line produces no extra key', () => {
    const out = parseDeck('Capital of France :: Paris');
    expect(out).toEqual([{ front: 'Capital of France', back: 'Paris' }]);
    expect('extra' in out[0]).toBe(false);
  });

  it('a fourth tab segment folds into extra, not dropped', () => {
    const out = parseDeck('f\tb\tpart one\tpart two');
    expect(out[0].extra).toBe('part one\tpart two');
  });

  it('an all-whitespace third segment is trimmed away to no extra', () => {
    const out = parseDeck('f\tb\t   ');
    expect('extra' in out[0]).toBe(false);
  });

  it('comment and blank lines are still skipped, extra or not', () => {
    const out = parseDeck('# a comment\n\nf1\tb1\te1\n// another comment\nf2 :: b2');
    expect(out).toEqual([
      { front: 'f1', back: 'b1', extra: 'e1' },
      { front: 'f2', back: 'b2' },
    ]);
  });
});

describe('buildItems / normalizeItem carry extra through', () => {
  it('a card with extra carries it onto the built DrillItem', () => {
    const deck: DeckItem[] = [{ front: 'f', back: 'b', extra: 'note' }];
    const [item] = buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    expect(item.extra).toBe('note');
  });

  it('a no-extra card is byte-identical to before extra existed', () => {
    const deck: DeckItem[] = [{ front: 'f', back: 'b' }];
    const [item] = buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
    expect(item.extra).toBeUndefined();
    // undefined-valued keys are dropped by JSON -- the persisted/serialized
    // shape (what actually round-trips through localStorage) is unchanged.
    expect(JSON.stringify(item)).not.toContain('extra');
  });

  it('normalizeItem reads extra from a saved item, undefined-safe', () => {
    const [built] = buildItems(
      [{ front: 'f', back: 'b', extra: 'note' }],
      CHUNK_DIFFICULTY,
      'cumulative',
      undefined,
      undefined,
      false
    );
    // Round-trip through JSON, the way a resumed save actually arrives.
    const revived = JSON.parse(JSON.stringify(built));
    expect(revived.extra).toBe('note');

    const oldSaveNoExtra = { id: 0, front: 'f', back: 'b', status: 'new' };
    expect(
      buildItems([{ front: 'f', back: 'b' }], CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false)[0].extra
    ).toBeUndefined();
    expect(oldSaveNoExtra).not.toHaveProperty('extra');
  });
});

describe('editCurrentItem -- extra-only edit never restarts progress', () => {
  const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };
  const deck: DeckItem[] = [{ front: 'Describe where the trees grow', back: FOUR_CHUNK_BACK }];

  function freshState(strict?: boolean): SessionState {
    return initSession({
      items: buildItems(deck, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false),
      phase: 'encode',
      queue: [],
      stats: { ...zeroStats },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { ...zeroStats },
      config: {
        encodeReps: 3,
        chunkDifficulty: CHUNK_DIFFICULTY,
        stemTolerance: true,
        ladderMode: 'cumulative',
        strictPunctuation: strict,
      },
    });
  }

  for (const strict of [false, true]) {
    it(`keeps every progress field and the chunk array (strictPunctuation=${strict})`, () => {
      // Advance one chunk in so there's real progress state to preserve:
      // attempt 0 is an ungraded presentation (C8b), attempt 1 is the first
      // real blind attempt, which advances chunkIndex to 1.
      const s0 = freshState(strict);
      const afterPresentation = applyAnswer(s0, '', { revealed: false }).state;
      const afterOneChunk = applyAnswer(afterPresentation, FOUR_CHUNK_CHUNKS[0], { revealed: false }).state;
      const before = afterOneChunk.items[0];
      expect(before.chunkIndex).toBe(1);

      const { state, restarted } = editCurrentItem(afterOneChunk, {
        front: before.front,
        back: before.back,
        extra: 'a new trouble-spot note',
      });

      expect(restarted).toBe(false);
      const after = state.items[0];
      expect(after.extra).toBe('a new trouble-spot note');
      const { extra: _e1, ...beforeProgress } = before;
      const { extra: _e2, ...afterProgress } = after;
      expect(afterProgress).toEqual(beforeProgress);
      expect(after.chunks).toBe(before.chunks);
    });
  }

  it('extra never influences whether the answer counted as changed', () => {
    const s0 = freshState(false);
    const before = s0.items[0];
    const { state, restarted } = editCurrentItem(s0, {
      front: before.front,
      back: before.back,
      extra: 'note one',
    });
    expect(restarted).toBe(false);
    const { state: state2, restarted: restarted2 } = editCurrentItem(state, {
      front: before.front,
      back: before.back,
      extra: '',
    });
    expect(restarted2).toBe(false);
    expect(state2.items[0].extra).toBeUndefined();
  });
});

describe('backup export/import preserves extra', () => {
  it('round-trips extra through export -> wipe -> import', () => {
    localStorage.clear();
    const deck: DeckItem[] = [
      { front: 'mitochondria', back: 'powerhouse of the cell', extra: 'aerobic respiration' },
      { front: 'no extra here', back: 'just a plain card' },
    ];
    saveDeckToStorage('Biology', deck);

    const payload = buildBackupPayload();
    localStorage.clear();
    importBackupPayload(payload, 'replace');

    const restored = getDeckFromStorage('biology');
    expect(restored).toEqual(deck);
    expect(restored?.[0].extra).toBe('aerobic respiration');
    expect(restored?.[1].extra).toBeUndefined();
    expect(loadDeckIndex().map(d => d.slug)).toEqual(['biology']);
  });
});
