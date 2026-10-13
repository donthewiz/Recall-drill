// List chunks and combine windows are slices of the card's own answer
// (2026-10-13): typing the card as written is never marked wrong, strict
// punctuation or not, ordered or any-order.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  advanceToNextBatch,
  buildItems,
  chunkText,
  computeMinimumTrials,
  findAllCulpritChunks,
  grade,
  initSession,
  joinWindow,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import { listItemSpans, splitListItems } from '../utils/grading';
import type { SessionState } from '../types';
import { perfectLearner, simulate } from '../../test/simulate';

interface Case {
  name: string;
  back: string;
  chunks: string[];
  // windows[e] = chunks 0..e+1 as one combine window, written by hand.
  windows: string[];
}

const CASES: Case[] = [
  {
    name: 'ends "..., and x"',
    back: 'humerus, radius and ulna, carpals, metacarpals, and phalanges',
    chunks: ['humerus, radius and ulna', 'carpals, metacarpals, and phalanges'],
    windows: ['humerus, radius and ulna, carpals, metacarpals, and phalanges'],
  },
  {
    name: 'a parenthetical item',
    back: 'cranial (frontal, parietal), facial, spinal (cervical; thoracic), sacral, coccygeal',
    chunks: ['cranial (frontal, parietal), facial', 'spinal (cervical; thoracic), sacral, coccygeal'],
    windows: ['cranial (frontal, parietal), facial, spinal (cervical; thoracic), sacral, coccygeal'],
  },
  {
    name: 'three chunks with "and" before the last item',
    back: 'red, orange, yellow, green, blue, indigo, violet, and white',
    chunks: ['red, orange, yellow', 'green, blue, indigo', 'violet, and white'],
    windows: [
      'red, orange, yellow, green, blue, indigo',
      'red, orange, yellow, green, blue, indigo, violet, and white',
    ],
  },
  {
    name: 'semicolons and odd spacing',
    back: 'alpha;  beta ;gamma; delta ,epsilon; zeta; eta;  theta',
    chunks: ['alpha;  beta ;gamma', 'delta ,epsilon; zeta', 'eta;  theta'],
    windows: [
      'alpha;  beta ;gamma; delta ,epsilon; zeta',
      'alpha;  beta ;gamma; delta ,epsilon; zeta; eta;  theta',
    ],
  },
  {
    name: 'a 3-item list over the threshold',
    back: 'fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), and synovial joints (freely movable)',
    chunks: ['fibrous joints (sutures, syndesmoses)', 'cartilaginous joints (symphyses)', 'synovial joints (freely movable)'],
    windows: [
      'fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses)',
      'fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), and synovial joints (freely movable)',
    ],
  },
];

describe('listItemSpans', () => {
  it('slices out the same items splitListItems returns', () => {
    for (const c of CASES) {
      const items = listItemSpans(c.back).map(([a, b]) => c.back.slice(a, b));
      expect(items).toEqual(splitListItems(c.back));
    }
  });
});

describe('list chunks and windows are the card\'s own text', () => {
  for (const c of CASES) {
    it(`${c.name}: chunk targets and window targets`, () => {
      const chunks = chunkText(c.back, 35, 3);
      expect(chunks).toEqual(c.chunks);
      for (const anyOrder of [false, true]) {
        c.windows.forEach((w, i) => {
          expect(joinWindow(chunks!, 0, i + 2, anyOrder, c.back)).toBe(w);
        });
        // A window from the middle starts at its first chunk's first item.
        if (chunks!.length === 3) {
          expect(joinWindow(chunks!, 1, 3, anyOrder, c.back)).toBe(c.back.slice(c.back.indexOf(chunks![1])));
        }
      }
    });

    for (const strict of [false, true]) {
      for (const anyOrder of [false, true]) {
        it(`${c.name}: typing the card as written is exact on every trial (strict ${strict}, anyOrder ${anyOrder})`, () => {
          const items = buildItems([{ front: 'Q', back: c.back, anyOrder }], 35, 'cumulative', undefined, 3, false);
          let s: SessionState = initSession({
            items,
            phase: 'encode',
            queue: [],
            stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
            currentId: SESSION_COMPLETE_ID,
            batchIndex: 0,
            batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
            config: { encodeReps: 1, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative', strictPunctuation: strict },
          });
          const seen: string[] = [];
          for (let i = 0; i < 100; i++) {
            const t = selectTrial(s);
            if (!t) {
              if (s.phase !== 'batch-done') break;
              s = advanceToNextBatch(s);
              continue;
            }
            // Every target is the card's text, from an item's start to an item's end.
            expect(c.back.includes(t.target)).toBe(true);
            seen.push(t.target);
            const r = applyAnswer(s, t.cue.kind === 'present' ? '' : t.target, { revealed: false });
            if (t.cue.kind !== 'present') expect(r.verdict).toBe('exact');
            s = r.state;
          }
          expect(s.stats.misses).toBe(0);
          for (const w of [...c.chunks, ...c.windows]) expect(seen).toContain(w);
          expect(seen).toContain(c.back); // the cycle and the Final check
        });
      }
    }
  }

  it('grade() is exact for the card as written, on the whole answer and every slice', () => {
    for (const c of CASES) {
      for (const strictPunctuation of [false, true]) {
        for (const w of [c.back, ...c.chunks, ...c.windows]) {
          expect(grade(w, w, { strictPunctuation }).verdict).toBe('exact');
          expect(grade(w, w, { strictPunctuation, anyOrder: true }).verdict).toBe('exact');
        }
      }
    }
  });

  it('the old re-joined window, with the "and" dropped, was wrong on strict decks', () => {
    const c = CASES[0];
    const rejoined = 'humerus, radius and ulna carpals, metacarpals, phalanges';
    expect(grade(c.back, rejoined, { strictPunctuation: true }).verdict).toBe('wrong');
    expect(grade(c.back, c.windows[0], { strictPunctuation: true }).verdict).toBe('exact');
  });

  it('computeMinimumTrials still equals a perfect run\'s attempts', () => {
    const deck = CASES.map(c => ({ front: 'Q', back: c.back }));
    for (const encodeReps of [1, 3]) {
      for (const minWords of [3, 8]) {
        const config = { encodeReps, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' as const };
        const items = buildItems(deck, 35, 'cumulative', undefined, minWords);
        expect(simulate(deck, config, perfectLearner, minWords).attempts).toBe(computeMinimumTrials(items, encodeReps));
      }
    }
  });
});

describe('remediation on slice windows', () => {
  const back = 'red, orange, yellow, green, blue, indigo, violet, and white';
  const chunks = ['red, orange, yellow', 'green, blue, indigo', 'violet, and white'];

  it('finds the chunk that holds the missed word', () => {
    expect(findAllCulpritChunks('red, orange, yellow, green, blue, indigo, violet, and white', chunks, 0, 2, false, undefined, back)).toEqual([2]);
    expect(findAllCulpritChunks('red, orange, yellow, green, blue, violet, and white', chunks, 0, 2, true, undefined, back)).toEqual([1]);
    expect(findAllCulpritChunks('red, yellow, green, blue, indigo, violet, and white', chunks, 0, 2, true, undefined, back)).toEqual([0]);
    // The "and" between chunks belongs to none: a dropped "and" with every
    // chunk's own words right falls back to the last chunk.
    expect(findAllCulpritChunks('red, orange, yellow, green, blue, indigo, violet, white', chunks, 0, 1, true, undefined, back)).toEqual([1]);
  });

  it('finds it for an any-order card, wherever the item was typed', () => {
    const typed = 'white, violet, indigo, green, yellow, red, orange';
    expect(findAllCulpritChunks(typed, chunks, 0, 2, true, { stemTolerance: true }, back)).toEqual([1]);
  });

  it('without the answer (an old save) joins the chunks as before', () => {
    expect(joinWindow(chunks, 0, 2)).toBe('red, orange, yellow green, blue, indigo');
    expect(joinWindow(chunks, 0, 2, true)).toBe('red, orange, yellow, green, blue, indigo');
    // Chunks that aren't in the answer (an old save): the same join.
    expect(joinWindow(['x, y', 'z, w'], 0, 2, false, back)).toBe('x, y z, w');
  });
});
