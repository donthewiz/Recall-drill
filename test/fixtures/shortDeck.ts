import { DeckItem } from '../../src/types';

// 12 short term/definition cards (backs 1-4 words), per Part 4 of the v2
// handoff doc's simulation fixtures. Short backs mostly land on the 'full'
// stage (<=3 words skips chunking) or a minimal 2-chunk ladder.
export const shortDeck: DeckItem[] = [
  { front: 'Capital of France', back: 'Paris' },
  { front: 'Chemical symbol for gold', back: 'Au' },
  { front: 'Largest planet in the solar system', back: 'Jupiter' },
  { front: 'HTTP status code for "not found"', back: '404' },
  { front: 'Author of "1984"', back: 'George Orwell' },
  { front: 'SI unit of electric current', back: 'ampere' },
  { front: 'Smallest prime number', back: 'two' },
  { front: 'Command to list files in a Unix shell', back: 'ls' },
  { front: 'Powerhouse of the cell', back: 'mitochondria' },
  { front: 'Freezing point of water in Celsius', back: 'zero degrees' },
  { front: 'Git command to stage all changes', back: 'git add' },
  { front: 'Number of continents on Earth', back: 'seven' },
];
