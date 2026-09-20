import { describe, expect, it } from 'vitest';
import { shortDeck } from './fixtures/shortDeck';
import { proseDeck } from './fixtures/proseDeck';
import { perfectLearner, realisticLearner, simulate, strugglingLearner } from './simulate';

const config = { encodeReps: 3, chunkDifficulty: 35 };

describe('simulate', () => {
  it('runs a nonzero number of trials for every learner/deck combination', () => {
    for (const deck of [shortDeck, proseDeck]) {
      for (const learner of [perfectLearner, realisticLearner, strugglingLearner]) {
        const result = simulate(deck, config, learner);
        expect(result.totalTrials).toBeGreaterThan(0);
        expect(result.keystrokes).toBeGreaterThan(0);
        expect(result.wallClockEstimate).toBeGreaterThan(0);
      }
    }
  });

  it('reports trialsByStage keys that are valid stage names', () => {
    const result = simulate(proseDeck, config, realisticLearner);
    const validStages = new Set(['chunks', 'combine', 'remediate', 'full', 'cycle']);
    for (const stage of Object.keys(result.trialsByStage)) {
      expect(validStages.has(stage)).toBe(true);
    }
  });

  it('a struggling learner never needs fewer trials than a perfect one on the same deck', () => {
    const perfect = simulate(proseDeck, config, perfectLearner);
    const struggling = simulate(proseDeck, config, strugglingLearner);
    expect(struggling.totalTrials).toBeGreaterThanOrEqual(perfect.totalTrials);
  });
});
