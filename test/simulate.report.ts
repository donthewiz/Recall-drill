// Prints the Part 4 scoreboard that docs/V2-HANDOFF.md asks for. Run with
// `npm run simulate`.
//
// Harness fix 1: every (deck, learner) config is run RUNS_PER_CONFIG times
// under a deterministic seed (see prng.ts/simulate.stats.ts) and reported as
// mean +/- sample SD, instead of one unseeded sample -- a single run's
// ~25% run-to-run variance was previously indistinguishable from a real
// phase-to-phase effect.
// Harness fix 2: mediumDeck (test/fixtures/mediumDeck.ts, backs 4-8 words)
// joins shortDeck/proseDeck -- neither existing fixture has a card in the
// range MIN_WORDS_TO_CHUNK-style changes actually affect.
//
// Also prints a Phase 0 baseline vs current ("final") comparison, using
// simulateLegacy.ts (src/test/reference/legacyEngine.ts, the frozen
// pre-Phase-1 snapshot) run through the SAME seeded/N-run machinery, so the
// comparison is apples-to-apples statistics on both sides rather than a
// live mean/SD against a single old number frozen in BASELINE.md's git
// history.
import { shortDeck } from './fixtures/shortDeck';
import { proseDeck } from './fixtures/proseDeck';
import { mediumDeck } from './fixtures/mediumDeck';
import { perfectLearner, realisticLearner, simulate, strugglingLearner, SimulationResult } from './simulate';
import {
  legacyPerfectLearner,
  legacyRealisticLearner,
  legacyStrugglingLearner,
  simulateLegacy,
} from './simulateLegacy';
import { AggregatedResult, fmt, runSeeded, withinOneSd } from './simulate.stats';

const RUNS_PER_CONFIG = 50;

const config = { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' as const };

const decks: { name: string; deck: typeof shortDeck }[] = [
  { name: 'shortDeck', deck: shortDeck },
  { name: 'proseDeck', deck: proseDeck },
  { name: 'mediumDeck', deck: mediumDeck },
];

const learners: {
  name: string;
  current: typeof perfectLearner;
  legacy: typeof legacyPerfectLearner;
}[] = [
  { name: 'perfect', current: perfectLearner, legacy: legacyPerfectLearner },
  { name: 'realistic', current: realisticLearner, legacy: legacyRealisticLearner },
  { name: 'struggling', current: strugglingLearner, legacy: legacyStrugglingLearner },
];

function formatStageBreakdown(byStage: SimulationResult['trialsByStage']): string {
  return Object.entries(byStage)
    .sort((a, b) => b[1] - a[1])
    .map(([stage, count]) => `${stage}:${count}`)
    .join(' ');
}

console.log(`\n=== Current engine, ${RUNS_PER_CONFIG} seeded runs per config (mean +/- SD) ===\n`);
const currentRows: string[] = [
  '| Deck | Learner | Total trials | Keystrokes | Wall clock (est, s) | Trials by stage (last run) |',
  '|---|---|---|---|---|---|',
];
const currentResults = new Map<string, AggregatedResult>();
for (const { name: deckName, deck } of decks) {
  for (const { name: learnerName, current } of learners) {
    const seedLabel = `current:${deckName}:${learnerName}`;
    let lastResult: SimulationResult | null = null;
    const agg = runSeeded(seedLabel, RUNS_PER_CONFIG, () => {
      lastResult = simulate(deck, config, current);
      return lastResult;
    });
    currentResults.set(`${deckName}:${learnerName}`, agg);
    currentRows.push(
      `| ${deckName} | ${learnerName} | ${fmt(agg.totalTrials, 1)} | ${fmt(agg.keystrokes, 1)} | ${fmt(agg.wallClockEstimate, 1)} | ${formatStageBreakdown(lastResult!.trialsByStage)} |`
    );
  }
}
console.log(currentRows.join('\n'));

console.log(`\n=== Phase 0 baseline (legacyEngine.ts), ${RUNS_PER_CONFIG} seeded runs per config (mean +/- SD) ===\n`);
const legacyRows: string[] = [
  '| Deck | Learner | Total trials | Keystrokes | Wall clock (est, s) |',
  '|---|---|---|---|---|',
];
const legacyResults = new Map<string, AggregatedResult>();
for (const { name: deckName, deck } of decks) {
  for (const { name: learnerName, legacy } of learners) {
    const seedLabel = `legacy:${deckName}:${learnerName}`;
    const agg = runSeeded(seedLabel, RUNS_PER_CONFIG, () => simulateLegacy(deck, config, legacy));
    legacyResults.set(`${deckName}:${learnerName}`, agg);
    legacyRows.push(
      `| ${deckName} | ${learnerName} | ${fmt(agg.totalTrials, 1)} | ${fmt(agg.keystrokes, 1)} | ${fmt(agg.wallClockEstimate, 1)} |`
    );
  }
}
console.log(legacyRows.join('\n'));

console.log(
  `\n=== Phase 0 baseline vs final (current), ${RUNS_PER_CONFIG} seeded runs each -- "not distinguishable" means |mean diff| <= max(SD_phase0, SD_final) ===\n`
);
const cmpRows: string[] = [
  '| Deck | Learner | Trials: Phase 0 | Trials: Final | Distinguishable? | Keystrokes: Phase 0 | Keystrokes: Final | Distinguishable? |',
  '|---|---|---|---|---|---|---|---|',
];
for (const { name: deckName } of decks) {
  for (const { name: learnerName } of learners) {
    const key = `${deckName}:${learnerName}`;
    const phase0 = legacyResults.get(key)!;
    const final = currentResults.get(key)!;
    const trialsFlag = withinOneSd(phase0.totalTrials, final.totalTrials) ? 'NOT DISTINGUISHABLE' : 'distinguishable';
    const keystrokesFlag = withinOneSd(phase0.keystrokes, final.keystrokes)
      ? 'NOT DISTINGUISHABLE'
      : 'distinguishable';
    cmpRows.push(
      `| ${deckName} | ${learnerName} | ${fmt(phase0.totalTrials, 1)} | ${fmt(final.totalTrials, 1)} | ${trialsFlag} | ${fmt(phase0.keystrokes, 1)} | ${fmt(final.keystrokes, 1)} | ${keystrokesFlag} |`
    );
  }
}
console.log(cmpRows.join('\n'));
