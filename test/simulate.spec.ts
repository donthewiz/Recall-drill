import { describe, expect, it } from 'vitest';
import { shortDeck } from './fixtures/shortDeck';
import { proseDeck } from './fixtures/proseDeck';
import { listDeck } from './fixtures/listDeck';
import { perfectLearner, realisticLearner, simulate, strugglingLearner } from './simulate';

const config = { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' as const };

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
    const validStages = new Set(['chunks', 'combine', 'remediate', 'full', 'cycle', 'final']);
    for (const stage of Object.keys(result.trialsByStage)) {
      expect(validStages.has(stage)).toBe(true);
    }
  });

  it('a struggling learner never needs fewer trials than a perfect one on the same deck', () => {
    const perfect = simulate(proseDeck, config, perfectLearner);
    const struggling = simulate(proseDeck, config, strugglingLearner);
    expect(struggling.totalTrials).toBeGreaterThanOrEqual(perfect.totalTrials);
  });

  // C1 (Phase 3) acceptance target, per docs/V2-HANDOFF.md: "shows >=40%
  // reduction on the fixture deck for a perfect learner." That holds once
  // cards average >=4 chunks -- see docs/BASELINE.md's Phase 3 section for
  // the full chunkDifficulty sweep and why proseDeck's fixture cards only
  // average 3 chunks (25% reduction) at SetupView's actual 35% default.
  it('cumulative ladder gives >=40% trial-count reduction vs exhaustive once cards average >=4 chunks (perfect learner)', () => {
    const fourChunkConfig = { encodeReps: 3, chunkDifficulty: 25, stemTolerance: true };
    const exhaustive = simulate(
      proseDeck,
      { ...fourChunkConfig, ladderMode: 'exhaustive' as const },
      perfectLearner
    );
    const cumulative = simulate(
      proseDeck,
      { ...fourChunkConfig, ladderMode: 'cumulative' as const },
      perfectLearner
    );
    const reduction = 1 - cumulative.totalTrials / exhaustive.totalTrials;
    expect(reduction).toBeGreaterThanOrEqual(0.4);
  });

  // 2026-10-12: a batched config used to stop at the first batch's
  // interstitial (selectTrial returns null on 'batch-done').
  it('runs every batch of a batched config through to the Final check', () => {
    for (const batchSize of [5, 10]) {
      const result = simulate(shortDeck, { ...config, encodeReps: 1, batchSize }, perfectLearner);
      // Every card: 1 full rep, 2 cycle answers, 1 Final check answer.
      expect(result.trialsByStage).toEqual({ full: 12, cycle: 24, final: 12 });
    }
  });

  it('listDeck: 12 list cards of 3-8 items, one of 19 words, two with an ordered front', () => {
    expect(listDeck).toHaveLength(12);
    const items = listDeck.map(c => c.back.split(/,(?![^(]*\))/).length);
    expect(Math.min(...items)).toBe(3);
    expect(Math.max(...items)).toBe(8);
    expect(listDeck.filter(c => c.back.split(/\s+/).length === 19)).toHaveLength(1);
    expect(listDeck.filter(c => /proximal to distal|superior to inferior/.test(c.front))).toHaveLength(2);
  });
});
