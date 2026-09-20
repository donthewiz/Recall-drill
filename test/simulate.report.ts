// Prints the 6-row baseline table (3 learner models x 2 fixture decks) that
// Part 4 of docs/V2-HANDOFF.md asks for. Run with `npm run simulate`.
// Results get pasted into docs/BASELINE.md as the Phase 0 scoreboard that
// later phases (C1/C2/C5) diff their own numbers against.
import { shortDeck } from './fixtures/shortDeck';
import { proseDeck } from './fixtures/proseDeck';
import {
  perfectLearner,
  realisticLearner,
  simulate,
  strugglingLearner,
  SimulationResult,
} from './simulate';

const config = { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' as const };

const decks: { name: string; deck: typeof shortDeck }[] = [
  { name: 'shortDeck (12 term/definition cards)', deck: shortDeck },
  { name: 'proseDeck (12 prose cards, ~18 words)', deck: proseDeck },
];

const learners: { name: string; learner: typeof perfectLearner }[] = [
  { name: 'perfect', learner: perfectLearner },
  { name: 'realistic', learner: realisticLearner },
  { name: 'struggling', learner: strugglingLearner },
];

function formatStageBreakdown(byStage: SimulationResult['trialsByStage']): string {
  return Object.entries(byStage)
    .sort((a, b) => b[1] - a[1])
    .map(([stage, count]) => `${stage}:${count}`)
    .join(' ');
}

const rows: string[] = [];
rows.push(
  '| Deck | Learner | Total trials | Keystrokes | Wall clock (est, s) | Trials by stage |'
);
rows.push('|---|---|---|---|---|---|');

for (const { name: deckName, deck } of decks) {
  for (const { name: learnerName, learner } of learners) {
    const result = simulate(deck, config, learner);
    rows.push(
      `| ${deckName} | ${learnerName} | ${result.totalTrials} | ${result.keystrokes} | ${result.wallClockEstimate.toFixed(1)} | ${formatStageBreakdown(result.trialsByStage)} |`
    );
  }
}

console.log(rows.join('\n'));
