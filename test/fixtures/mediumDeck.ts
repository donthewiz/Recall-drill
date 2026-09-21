import { DeckItem } from '../../src/types';

// 12 medium-length cards, backs 4-8 words -- the shape of real terminology
// definitions (a short phrase, not a single word like shortDeck and not a
// full explanatory sentence like proseDeck). Added specifically because
// neither shortDeck (backs <=2 words) nor proseDeck (backs 17-22 words) has
// any card in the 4-8 word range MIN_WORDS_TO_CHUNK actually targets, which
// made that change untestable against the existing two fixtures.
export const mediumDeck: DeckItem[] = [
  { front: 'Define osmosis', back: 'movement of water across a membrane' },
  { front: 'Define inflation (economics)', back: 'a general rise in prices over time' },
  { front: 'Define recursion', back: 'a function that calls itself' },
  { front: 'Define photosynthesis in one phrase', back: 'plants converting light into chemical energy' },
  { front: 'Define federalism', back: 'shared power between national and state governments' },
  { front: 'Define entropy', back: 'a measure of disorder in a system' },
  { front: 'Define latency', back: 'the delay before data transfer begins' },
  { front: 'Define natural selection', back: 'survival and reproduction favoring certain traits' },
  { front: 'Define amortization', back: 'paying off debt through scheduled payments' },
  { front: 'Define homeostasis', back: 'maintaining stable conditions despite external change' },
  { front: 'Define polymorphism (programming)', back: 'different objects responding to one call' },
  { front: 'Define supply-side economics', back: 'lowering taxes to boost production and growth' },
];
