import { DeckItem } from '../../types';

// Word counts and chunkDifficulty=20 are chosen deliberately (verified against
// chunkText's exact bucketing algorithm) so each card lands on a specific rung
// of the encode ladder:
//   - "full-stage" back has <=3 words -> chunkText returns null -> stage 'full'.
//   - "two-chunk" back is 5 words -> chunks ["the mitochondria", "makes cell energy"]
//     (buildCombineSequence(2) => 1 window, windowChunkCount=2 => missThreshold=1).
//   - "four-chunk" back is 9 words -> chunks
//     ["large green", "trees grow", "slowly near", "the quiet river"]
//     (buildCombineSequence(4) => 6 windows spanning missThreshold 1 and 2).
export const CHUNK_DIFFICULTY = 20;

export const characterizationDeck: DeckItem[] = [
  {
    front: 'What do cats do a lot?',
    back: 'cats sleep often',
  },
  {
    front: 'What does the mitochondria do?',
    back: 'the mitochondria makes cell energy',
  },
  {
    front: 'Describe where the trees grow',
    back: 'large green trees grow slowly near the quiet river',
  },
];

export const FULL_STAGE_BACK = 'cats sleep often';
export const TWO_CHUNK_BACK = 'the mitochondria makes cell energy';
export const TWO_CHUNK_CHUNKS = ['the mitochondria', 'makes cell energy'];
export const FOUR_CHUNK_BACK = 'large green trees grow slowly near the quiet river';
export const FOUR_CHUNK_CHUNKS = ['large green', 'trees grow', 'slowly near', 'the quiet river'];
