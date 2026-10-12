// Unordered list answers grade in any order (2026-10-12).
import { describe, expect, it } from 'vitest';
import {
  buildItems,
  findAllCulpritChunks,
  grade,
  initSession,
  applyAnswer,
  listOrderFromWording,
  ORDER_CUES,
  selectTrial,
  SESSION_COMPLETE_ID,
  withListOrder,
} from '../utils/drillEngine';
import type { SessionState } from '../types';

const BONES = 'humerus, radius and ulna, carpals, metacarpals, phalanges';

describe('grade() with anyOrder', () => {
  it('accepts the items in any order, exact when every item is exact', () => {
    expect(grade('phalanges, metacarpals, carpals, radius and ulna, humerus', BONES, { anyOrder: true }).verdict).toBe('exact');
    expect(grade('carpals; humerus; phalanges; radius and ulna; metacarpals', BONES, { anyOrder: true }).verdict).toBe('exact');
  });

  it('without anyOrder (absent or false) grades in order as before', () => {
    const typed = 'phalanges, metacarpals, carpals, radius and ulna, humerus';
    expect(grade(typed, BONES).verdict).toBe('wrong');
    expect(grade(typed, BONES, { anyOrder: false })).toEqual(grade(typed, BONES));
  });

  it('is near when every item matches and one only nearly', () => {
    expect(grade('phalanges, the metacarpals, carpals, radius and ulna, humerus', BONES, { anyOrder: true }).verdict).toBe('near');
  });

  it('is wrong with an item missing or one left over, and marks only the missing item', () => {
    const missing = grade('phalanges, carpals, humerus, radius and ulna', BONES, { anyOrder: true });
    expect(missing.verdict).toBe('wrong');
    expect(missing.missingWords).toEqual(['metacarpals']);
    expect(missing.diff.filter(d => !d.matched).map(d => d.word)).toEqual(['metacarpals,']);
    const extra = grade('phalanges, carpals, humerus, radius and ulna, metacarpals, femur', BONES, { anyOrder: true });
    expect(extra.verdict).toBe('wrong');
    expect(extra.extraWords).toEqual(['femur']);
  });

  it('matches items one to one: a repeated item does not cover two', () => {
    expect(grade('carpals, carpals, humerus, radius and ulna, phalanges', BONES, { anyOrder: true }).verdict).toBe('wrong');
  });

  it('splits one-word items typed without separators on whitespace, dropping "and"/"or"', () => {
    const target = 'epithelial, connective, muscle, and nervous';
    expect(grade('nervous muscle connective epithelial', target, { anyOrder: true }).verdict).toBe('exact');
    expect(grade('nervous and muscle or connective epithelial', target, { anyOrder: true }).verdict).toBe('exact');
    // The dropped "and" counts with its item in the diff.
    expect(grade('nervous, muscle, connective', target, { anyOrder: true }).diff).toEqual([
      { word: 'epithelial,', matched: false },
      { word: 'connective,', matched: true },
      { word: 'muscle,', matched: true },
      { word: 'and', matched: true },
      { word: 'nervous', matched: true },
    ]);
  });

  it('grades as today when multi-word items are typed without separators', () => {
    const typed = 'phalanges metacarpals carpals radius and ulna humerus';
    expect(grade(typed, BONES, { anyOrder: true })).toEqual(grade(typed, BONES));
  });

  it('keeps strict punctuation per item (no near tier)', () => {
    const target = 'Na+, K+, Cl-';
    expect(grade('Cl-, Na+, K+', target, { anyOrder: true, strictPunctuation: true }).verdict).toBe('exact');
    expect(grade('Cl, Na+, K+', target, { anyOrder: true, strictPunctuation: true }).verdict).toBe('wrong');
  });
});

describe('listOrderFromWording', () => {
  it('is "ordered" for every cue, else "any"', () => {
    for (const cue of ORDER_CUES) expect(listOrderFromWording(`Name them ${cue} now`)).toBe('ordered');
    expect(listOrderFromWording('Name the bones of the upper limb from proximal to distal')).toBe('ordered');
    expect(listOrderFromWording('List the regions from superior to inferior')).toBe('ordered');
    expect(listOrderFromWording('Name the types of cartilage')).toBe('any');
  });

  it('matches whole words only and ignores the cloze blank', () => {
    expect(listOrderFromWording('Name the stepson\'s bicycle parts')).toBe('any');
    expect(listOrderFromWording('The four tissue types are [...]')).toBe('any');
    expect(listOrderFromWording('The cell cycle phases: [...]')).toBe('ordered');
  });

  it('withListOrder sets anyOrder on unordered list answers only', () => {
    expect(withListOrder({ front: 'Name the types', back: 'a, b, c' })).toEqual({ front: 'Name the types', back: 'a, b, c', anyOrder: true });
    expect(withListOrder({ front: 'Name the steps', back: 'a, b, c' })).toEqual({ front: 'Name the steps', back: 'a, b, c' });
    expect(withListOrder({ front: 'Name the pair', back: 'a, b' })).toEqual({ front: 'Name the pair', back: 'a, b' });
  });
});

describe('any-order through the session', () => {
  const SIX = '1 frontal, 2 parietal, 2 temporal, 1 occipital, 1 sphenoid, 1 ethmoid';

  function start(): SessionState {
    const items = buildItems([{ front: 'Name the cranial bones', back: SIX, anyOrder: true }], 35, 'cumulative', undefined, 8, false);
    return initSession({
      items,
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: { encodeReps: 1, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' },
    });
  }

  it('a chunk and a combine window take their items in any order; windows join with ", "', () => {
    let s = start();
    s = applyAnswer(s, '', { revealed: false }).state; // presentation
    const chunk = applyAnswer(s, '2 parietal, 1 frontal', { revealed: false });
    expect(chunk.verdict).toBe('exact');
    s = chunk.state;
    for (const typed of ['', '1 occipital, 2 temporal', '', '1 ethmoid, 1 sphenoid']) s = applyAnswer(s, typed, { revealed: false }).state;
    expect(selectTrial(s)!.target).toBe('1 frontal, 2 parietal, 2 temporal, 1 occipital');
    expect(applyAnswer(s, '1 occipital, 2 temporal, 2 parietal, 1 frontal', { revealed: false }).verdict).toBe('exact');
  });

  it('remediation isolates the chunk holding the missed item, wherever it was typed', () => {
    const chunks = ['1 frontal, 2 parietal', '2 temporal, 1 occipital', '1 sphenoid, 1 ethmoid'];
    expect(findAllCulpritChunks('1 ethmoid, 2 temporal, 1 sphenoid, 1 frontal, 2 parietal', chunks, 0, 2, false, { stemTolerance: true })).toEqual([1]);
    // In order it would blame every chunk the LCS misaligned.
    expect(findAllCulpritChunks('1 ethmoid, 2 temporal, 1 sphenoid, 1 frontal, 2 parietal', chunks, 0, 2)).not.toEqual([1]);
  });
});
