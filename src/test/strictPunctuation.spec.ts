// Phase 2: per-deck "Punctuation must match" mode.
// grade()-level unit tests for the strict comparator, plus applyAnswer/
// storage integration tests proving the deck's mode is actually respected
// end-to-end (not just by grade() in isolation) and that old decks/sessions
// saved before this setting existed default to false.
import { describe, expect, it, beforeEach } from 'vitest';
import {
  grade,
  applyAnswer,
  buildItems,
  initSession,
  SESSION_COMPLETE_ID,
  saveDeckToStorage,
  loadDeckIndex,
} from '../utils/drillEngine';
import type { SessionState, SavedDeckEntry } from '../types';

describe('grade() strict punctuation mode', () => {
  // Strict mode ignores accents and decorative/structural punctuation
  // (brackets, quotes, apostrophes, commas, colons, semicolons, and a
  // sentence-ending . ! ?), but every word is required (no stopword/stem
  // forgiveness) and every other symbol -- hyphens, slashes, +, %, <, >, =,
  // a digit-internal period -- must match literally.
  const rightPairs: [string, string][] = [
    ['tachycardia fast heart rate', 'tachycardia (fast heart rate)'],
    ['the fight or flight response', 'the "fight or flight" response'],
    ['normal range 7.35-7.45', 'normal range: 7.35-7.45'],
    ['heart lungs kidneys', 'heart, lungs, kidneys'],
    ['the end', 'The end.'],
    ['dont', 'don’t'],
    ['pre-op', 'pre—op'],
    ['Menieres disease', 'Ménière’s disease'],
    ['Menière', 'Menière'],
  ];
  for (const [typed, target] of rightPairs) {
    it(`strict: "${typed}" vs "${target}" -> exact`, () => {
      expect(grade(typed, target, { strictPunctuation: true }).verdict).toBe('exact');
    });
  }

  const wrongPairs: [string, string][] = [
    ['tachycardia', 'tachycardia (fast heart rate)'],
    ['inflammation of stomach', 'inflammation of the stomach'],
    ['inflammation of the joint', 'inflammation of the joints'],
    ['pre op', 'pre-op'],
    ['and or', 'and/or'],
    ['74', '7.4'],
    ['Na', 'Na+'],
    ['5', '-5'],
  ];
  for (const [typed, target] of wrongPairs) {
    it(`strict: "${typed}" vs "${target}" -> wrong`, () => {
      expect(grade(typed, target, { strictPunctuation: true }).verdict).toBe('wrong');
    });
  }

  // Phase 1's punctuation table must be unaffected when strict is explicitly off.
  const phase1ExactPairs: [string, string][] = [
    ['pre op', 'pre-op'],
    ['and or', 'and/or'],
    ['10 mg', '10mg'],
    ['Na +', 'Na+'],
    ['5 %', '5%'],
    ['itis', '-itis'],
    ['dont', "don't"],
    ['tachycardia fast heart rate', 'tachycardia (fast heart rate)'],
  ];
  for (const [typed, target] of phase1ExactPairs) {
    it(`strict off: "${typed}" vs "${target}" -> exact (unchanged from Phase 1)`, () => {
      expect(grade(typed, target, { strictPunctuation: false }).verdict).toBe('exact');
    });
  }

  const phase1WrongPairs: [string, string][] = [
    ['74', '7.4'],
    ['Na', 'Na+'],
    ['5', '-5'],
  ];
  for (const [typed, target] of phase1WrongPairs) {
    it(`strict off: "${typed}" vs "${target}" -> wrong (unchanged from Phase 1)`, () => {
      expect(grade(typed, target, { strictPunctuation: false }).verdict).toBe('wrong');
    });
  }
});

// applyAnswer integration: proves the SessionConfig's strictPunctuation flag
// (not just grade()'s own opts) actually drives the full-stage grading path,
// and that an old config missing the field behaves exactly like false.
function freshState(back: string, strictPunctuation?: boolean): SessionState {
  return initSession({
    items: buildItems([{ front: 'Q', back }], 100, 'cumulative'),
    phase: 'encode',
    queue: [],
    stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    config: { encodeReps: 1, chunkDifficulty: 100, stemTolerance: true, ladderMode: 'cumulative', strictPunctuation },
  });
}

describe('applyAnswer respects the deck-level strictPunctuation setting', () => {
  const target = 'inflammation of the stomach';
  const typed = 'inflammation of stomach'; // drops the stopword "the"

  it('strictPunctuation: true grades a dropped-stopword difference wrong (near-miss tier disabled)', () => {
    const state = freshState(target, true);
    const result = applyAnswer(state, typed, { revealed: false });
    expect(result.verdict).toBe('wrong');
    expect(result.state.stats.misses).toBe(1);
  });

  it('strictPunctuation: false grades the same difference near (stopword forgiveness applies)', () => {
    const state = freshState(target, false);
    const result = applyAnswer(state, typed, { revealed: false });
    expect(result.verdict).toBe('near');
    expect(result.state.stats.nearMisses).toBe(1);
  });

  it('an old config with strictPunctuation undefined (pre-Phase-2 session) behaves like false', () => {
    const state = freshState(target, undefined);
    const result = applyAnswer(state, typed, { revealed: false });
    expect(result.verdict).toBe('near');
  });
});

describe('saveDeckToStorage / loadDeckIndex: strictPunctuation persistence', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('a deck saved with strictPunctuation: true round-trips through the deck index', () => {
    saveDeckToStorage('Meds', [{ front: 'BE', back: 'BE -2 to +2' }], null, true);
    const entry = loadDeckIndex().find(d => d.slug === 'meds');
    expect(entry?.strictPunctuation).toBe(true);
  });

  it('a deck saved without the strictPunctuation arg defaults to false', () => {
    saveDeckToStorage('Cats', [{ front: 'capital of france', back: 'paris' }]);
    const entry = loadDeckIndex().find(d => d.slug === 'cats');
    expect(entry?.strictPunctuation).toBe(false);
  });

  it('an old deck-index entry saved before this field existed loads as strict = false', () => {
    // Simulates a real pre-Phase-2 localStorage payload: the key is simply
    // absent from the stored object, not present-and-undefined.
    const legacyEntry = { slug: 'legacy', name: 'Legacy', count: 1 } as SavedDeckEntry;
    localStorage.setItem('deck-index', JSON.stringify([legacyEntry]));
    const entry = loadDeckIndex().find(d => d.slug === 'legacy');
    expect(entry?.strictPunctuation).toBeUndefined();
    expect(entry?.strictPunctuation ?? false).toBe(false);
  });
});
