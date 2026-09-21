// MIN_WORDS_TO_CHUNK acceptance: answers at or under this many words skip
// the chunk/combine ladder entirely (stage 'full') regardless of
// chunkDifficulty. Raised from 3 to 8 after measuring that a 4-8 word back
// (the shape of a real terminology definition -- neither of the original
// two fixture decks had a card in that range) cost meaningfully more
// trials on the chunk+combine ladder than a single full-answer recall
// would, per test/fixtures/mediumDeck.ts and the Part 4 harness's
// mean+/-SD comparison (docs/BASELINE.md).
import { describe, expect, it } from 'vitest';
import { chunkText, MIN_WORDS_TO_CHUNK } from '../utils/drillEngine';

function words(n: number): string {
  return Array.from({ length: n }, (_, i) => `word${i}`).join(' ');
}

describe('MIN_WORDS_TO_CHUNK', () => {
  it('is 8', () => {
    expect(MIN_WORDS_TO_CHUNK).toBe(8);
  });

  it('a back at or under MIN_WORDS_TO_CHUNK never chunks, regardless of chunkDifficulty', () => {
    for (const n of [1, 3, 8]) {
      for (const pct of [15, 35, 50, 90]) {
        expect(chunkText(words(n), pct)).toBeNull();
      }
    }
  });

  it('a back one word over MIN_WORDS_TO_CHUNK can chunk (chunkDifficulty permitting)', () => {
    expect(chunkText(words(9), 50)).not.toBeNull();
  });
});
