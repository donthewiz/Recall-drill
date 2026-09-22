// Unit tests for C2's grade() function, per the acceptance table in
// docs/V2-HANDOFF.md: exact, stopword-only omission, stopword-only
// insertion, plural difference, one content word wrong (must be wrong),
// transposed clause, empty input (must be wrong).
import { describe, expect, it } from 'vitest';
import { grade } from '../utils/drillEngine';

describe('grade', () => {
  it('exact match', () => {
    const r = grade('the cat sat on the mat', 'the cat sat on the mat');
    expect(r.verdict).toBe('exact');
    expect(r.similarity).toBe(1);
  });

  it('stopword-only omission -> near', () => {
    const r = grade('wait for bus', 'wait for the bus');
    expect(r.verdict).toBe('near');
    expect(r.missingWords).toEqual(['the']);
    expect(r.extraWords).toEqual([]);
  });

  it('stopword-only insertion -> near', () => {
    const r = grade('wait for the bus', 'wait for bus');
    expect(r.verdict).toBe('near');
    expect(r.missingWords).toEqual([]);
    expect(r.extraWords).toEqual(['the']);
  });

  it('plural difference in an otherwise-long answer -> near (stemTolerance on)', () => {
    const target = 'large green trees grow slowly near the quiet flowing rivers';
    const typed = 'large green trees grow slowly near the quiet flowing river';
    const r = grade(typed, target);
    expect(r.similarity).toBeGreaterThanOrEqual(0.9);
    expect(r.verdict).toBe('near');
  });

  it('plural difference -> wrong when stemTolerance is off', () => {
    const target = 'large green trees grow slowly near the quiet flowing rivers';
    const typed = 'large green trees grow slowly near the quiet flowing river';
    const r = grade(typed, target, { stemTolerance: false });
    expect(r.verdict).toBe('wrong');
  });

  it('one content word wrong -> wrong', () => {
    const target = 'large green trees grow slowly near the quiet flowing rivers';
    const typed = 'large green trees grow slowly near the quiet flowing streams';
    const r = grade(typed, target);
    expect(r.verdict).toBe('wrong');
  });

  it('transposed clause -> wrong', () => {
    const r = grade('energy makes cell the mitochondria', 'the mitochondria makes cell energy');
    expect(r.verdict).toBe('wrong');
  });

  it('empty input -> wrong', () => {
    const r = grade('', 'the mitochondria makes cell energy');
    expect(r.verdict).toBe('wrong');
    expect(r.missingWords).toEqual(['the', 'mitochondria', 'makes', 'cell', 'energy']);
  });

  it('lenient: false always returns wrong for a non-exact answer, even a stopword-only diff', () => {
    const r = grade('wait for bus', 'wait for the bus', { lenient: false });
    expect(r.verdict).toBe('wrong');
  });

  it('a genuinely wrong short answer is not rescued by the near-miss tier', () => {
    const r = grade('dog', 'cat');
    expect(r.verdict).toBe('wrong');
  });
});

// Phase 1: punctuation normalization. Grading must never fail a correct
// answer over punctuation alone, but a symbol that changes the answer's
// meaning (a decimal point, a leading minus sign, a comparison operator, a
// unit-changing '+') must still be caught.
describe('grade punctuation normalization', () => {
  const exactPairs: [string, string][] = [
    ['pre op', 'pre-op'],
    ['and or', 'and/or'],
    ['10 mg', '10mg'],
    ['Menieres disease', "Ménière's disease"],
    ['Na +', 'Na+'],
    ['5 %', '5%'],
    ['itis', '-itis'],
    ['dont', "don't"],
    ['7.4', '7.4'],
    ['-5', '−5'],
    ['- 5', '-5'],
    ['10 20', '10-20'],
    ['10 - 20', '10-20'],
    ['tachycardia fast heart rate', 'tachycardia (fast heart rate)'],
  ];

  for (const [typed, target] of exactPairs) {
    it(`"${typed}" vs "${target}" -> exact`, () => {
      expect(grade(typed, target).verdict).toBe('exact');
    });
  }

  const wrongPairs: [string, string][] = [
    ['74', '7.4'],
    ['60', '<60'],
    ['Na', 'Na+'],
    ['5', '-5'],
    ['BE 2 to 2', 'BE -2 to +2'],
    ['tachycardia', 'tachycardia (fast heart rate)'],
  ];

  for (const [typed, target] of wrongPairs) {
    it(`"${typed}" vs "${target}" -> wrong`, () => {
      expect(grade(typed, target).verdict).toBe('wrong');
    });
  }
});
