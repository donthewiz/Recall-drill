import { DeckItem } from '../../src/types';

// 12 prose cards, backs averaging ~18 words (range 17-22), per Part 4 of the
// v2 handoff doc's simulation fixtures. Long enough to force multi-chunk
// combine ladders at the default chunk difficulty.
export const proseDeck: DeckItem[] = [
  {
    front: 'How do mitochondria generate cellular energy?',
    back: 'Mitochondria generate cellular energy by converting nutrients into ATP through a process called oxidative phosphorylation inside their inner membrane.',
  },
  {
    front: 'What did the French Revolution change?',
    back: 'The French Revolution began in 1789 and fundamentally transformed French society by abolishing the monarchy and feudal privileges.',
  },
  {
    front: 'What does photosynthesis do?',
    back: 'Photosynthesis converts light energy into chemical energy stored in glucose, releasing oxygen as a byproduct of the reaction.',
  },
  {
    front: 'How does binary search work?',
    back: 'A binary search algorithm repeatedly divides a sorted array in half to locate a target value efficiently.',
  },
  {
    front: 'What does the supply and demand model explain?',
    back: 'The supply and demand model explains how prices adjust based on the relative scarcity and desire for goods.',
  },
  {
    front: "What is Newton's second law?",
    back: "Newton's second law states that force equals mass multiplied by acceleration for any given object in motion.",
  },
  {
    front: 'What is the water cycle?',
    back: 'The water cycle describes the continuous movement of water through evaporation, condensation, precipitation, and collection on Earth.',
  },
  {
    front: 'What is DNA replication?',
    back: 'DNA replication is the biological process of producing two identical copies of DNA from one original molecule.',
  },
  {
    front: 'What was the Cold War?',
    back: 'The Cold War was a prolonged period of geopolitical tension between the United States and the Soviet Union after World War II.',
  },
  {
    front: 'What is encapsulation in object-oriented programming?',
    back: "In object-oriented programming, encapsulation restricts direct access to an object's internal state, exposing behavior only through defined methods.",
  },
  {
    front: 'What does the French verb être mean?',
    back: 'The French verb être means to be and is one of the most frequently used irregular verbs in the language.',
  },
  {
    front: 'What is confirmation bias?',
    back: "Confirmation bias is the tendency to search for and interpret information in ways that support one's existing beliefs.",
  },
];
