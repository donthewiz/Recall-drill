// Cross-check between two independent implementations of "how many trials
// will this deck take": computeMinimumTrials (src/utils/drillEngine.ts),
// the cold-start estimate's floor, and the real engine driven end-to-end by
// the seeded simulate() harness (test/simulate.ts) with the PERFECT learner
// (every attempt correct first try -- the one learner model for which the
// engine's actual trial count and the estimator's predicted floor SHOULD be
// identical, not just close).
//
// This test intentionally duplicates what computeMinimumTrials already
// claims in its own doc comment -- that's the point. computeMinimumTrials
// is a hand-derived formula that has to keep tracking applyAnswer's actual
// trial sequence (chunk presentation vs. blind attempt counting, combine
// window rep requirements, cycle-phase mastery, ...) as that sequence
// evolves. A future change to the engine can easily update applyAnswer's
// behavior without anyone remembering to update the parallel formula in
// computeMinimumTrials, and nothing else in the suite would catch that --
// every other computeMinimumTrials-adjacent test asserts against
// computeMinimumTrials's own output, not against the engine. This test
// fails the moment the two diverge, which is the actual failure mode it
// exists to catch. Do not delete this as "redundant" with
// c1/c3/c8a.spec.ts or simulate.spec.ts -- none of those compare the
// estimator's prediction to a real driven session.
import { describe, expect, it } from 'vitest';
import { DeckItem, SessionConfig } from '../src/types';
import { buildItems, computeMinimumTrials } from '../src/utils/drillEngine';
import { shortDeck } from './fixtures/shortDeck';
import { mediumDeck } from './fixtures/mediumDeck';
import { proseDeck } from './fixtures/proseDeck';
import { perfectLearner, simulate } from './simulate';

// Deliberately built from cards whose word count sits well clear of both
// MIN_WORDS_TO_CHUNK values under test (3 and 8) on either side -- shortDeck
// backs are 1-2 words (always unchunked) and proseDeck backs are 17-22
// words (always chunked) -- so this deck's chunked/full-stage split is the
// same at every minWordsToChunk value the matrix below exercises, rather
// than shifting out from under the test.
const mixedDeck: DeckItem[] = [...shortDeck.slice(0, 6), ...proseDeck.slice(0, 6)];

const decks: { name: string; deck: DeckItem[] }[] = [
  { name: 'shortDeck', deck: shortDeck },
  { name: 'mediumDeck', deck: mediumDeck },
  { name: 'proseDeck', deck: proseDeck },
  { name: 'mixedDeck (chunked + full-stage cards)', deck: mixedDeck },
];

const ENCODE_REPS_VALUES = [1, 3, 5];
const MIN_WORDS_TO_CHUNK_VALUES = [3, 8];

describe('computeMinimumTrials matches a real perfect-learner session exactly', () => {
  for (const { name: deckName, deck } of decks) {
    for (const encodeReps of ENCODE_REPS_VALUES) {
      for (const minWordsToChunk of MIN_WORDS_TO_CHUNK_VALUES) {
        it(`${deckName}, encodeReps=${encodeReps}, minWordsToChunk=${minWordsToChunk}`, () => {
          const config: SessionConfig = {
            encodeReps,
            chunkDifficulty: 35,
            stemTolerance: true,
            ladderMode: 'cumulative',
          };

          const result = simulate(deck, config, perfectLearner, minWordsToChunk);

          // Same chunk/combine shape the harness just drove through --
          // computeMinimumTrials needs the built DrillItem[] (chunks,
          // combineSeq), not the raw DeckItem[] deck.
          const items = buildItems(deck, config.chunkDifficulty, config.ladderMode, undefined, minWordsToChunk);
          const predictedFloor = computeMinimumTrials(items, encodeReps, config.ladderMode);

          expect(result.attempts).toBe(predictedFloor);
        });
      }
    }
  }
});
