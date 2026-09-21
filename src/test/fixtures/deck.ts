import { DeckItem } from '../../types';

// Word counts and chunkDifficulty are chosen deliberately (verified against
// chunkText's exact bucketing algorithm) so each card lands on a specific rung
// of the encode ladder:
//   - "full-stage" back has <=3 words -> chunkText returns null -> stage 'full'.
//   - "two-chunk" back is 9 words, chunked at TWO_CHUNK_DIFFICULTY (50%) ->
//     chunks ["the mitochondria produces most of", "the cells energy supply"]
//     (buildCombineSequence(2) => 1 window, windowChunkCount=2 => missThreshold=1).
//   - "four-chunk" back is 9 words, chunked at CHUNK_DIFFICULTY (20%) -> chunks
//     ["large green", "trees grow", "slowly near", "the quiet river"]
//     (buildCombineSequence(4) => 6 windows spanning missThreshold 1 and 2).
// Both chunked backs are deliberately >MIN_WORDS_TO_CHUNK (8) -- a back at
// or under that word count skips chunking entirely regardless of
// chunkDifficulty (see drillEngine.ts's chunkText). They need two different
// chunkDifficulty values because they share a 9-word length but need to
// split into a different number of chunks (2 vs 4).
export const CHUNK_DIFFICULTY = 20;
export const TWO_CHUNK_DIFFICULTY = 50;

export const characterizationDeck: DeckItem[] = [
  {
    front: 'What do cats do a lot?',
    back: 'cats sleep often',
  },
  {
    front: 'What does the mitochondria do?',
    back: 'the mitochondria produces most of the cells energy supply',
  },
  {
    front: 'Describe where the trees grow',
    back: 'large green trees grow slowly near the quiet river',
  },
];

export const FULL_STAGE_BACK = 'cats sleep often';
export const TWO_CHUNK_BACK = 'the mitochondria produces most of the cells energy supply';
export const TWO_CHUNK_CHUNKS = ['the mitochondria produces most of', 'the cells energy supply'];
export const FOUR_CHUNK_BACK = 'large green trees grow slowly near the quiet river';
export const FOUR_CHUNK_CHUNKS = ['large green', 'trees grow', 'slowly near', 'the quiet river'];
