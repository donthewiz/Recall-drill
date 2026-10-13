// List answers are chunked at item boundaries (2026-10-12), and the word rule
// never cuts inside parentheses.
import { describe, expect, it } from 'vitest';
import { buildItem, chunkText, computeMinimumTrials, listItems } from '../utils/drillEngine';

describe('listItems', () => {
  it('splits on commas and semicolons, trims, and drops a leading "and"/"or"', () => {
    expect(listItems('skeletal, cardiac, and smooth')).toEqual(['skeletal', 'cardiac', 'smooth']);
    expect(listItems('alpha; beta; or gamma')).toEqual(['alpha', 'beta', 'gamma']);
  });

  it('keeps separators inside () and [] and each item\'s own wording', () => {
    expect(listItems('true (vertebrosternal, sternal), false [x; y], floating')).toEqual([
      'true (vertebrosternal, sternal)',
      'false [x; y]',
      'floating',
    ]);
    expect(listItems('2 nasal, 2 lacrimal, 1 vomer')).toEqual(['2 nasal', '2 lacrimal', '1 vomer']);
  });

  it('is a list only with 3 or more items', () => {
    expect(listItems('radius and ulna')).toBeNull();
    expect(listItems('alpha, beta')).toBeNull();
    expect(listItems('a, , b,')).toBeNull();
    expect(listItems('humerus, radius and ulna, carpals')).toEqual(['humerus', 'radius and ulna', 'carpals']);
  });
});

describe('chunkText on list answers', () => {
  const six = '1 frontal, 2 parietal, 2 temporal, 1 occipital, 1 sphenoid, 1 ethmoid';

  it('cuts at item boundaries, never mid-item', () => {
    // 6 items x 35% = 2.1 -> 2 items per chunk.
    expect(chunkText(six, 35)).toEqual(['1 frontal, 2 parietal', '2 temporal, 1 occipital', '1 sphenoid, 1 ethmoid']);
  });

  it('chunks a list of 4+ items whatever its word count', () => {
    expect(chunkText('epithelial, connective, muscle, nervous', 35)).toEqual([
      'epithelial, connective',
      'muscle, nervous',
    ]);
  });

  it('merges a lonely 1-item trailing chunk into the one before', () => {
    // 5 items x 35% = 1.75 -> 2: [2, 2, 1] -> [2, 3].
    expect(chunkText('a, b, c, d, e', 35)).toEqual(['a, b', 'c, d, e']);
  });

  it('a 3-item list: not at or under the threshold; over it, one item per chunk (2026-10-13)', () => {
    expect(chunkText('skeletal, cardiac, smooth', 35)).toBeNull();
    const long = 'fibrous joints (sutures, syndesmoses), cartilaginous joints (symphyses), synovial joints (freely movable)';
    expect(chunkText(long, 35)).toEqual([
      'fibrous joints (sutures, syndesmoses)',
      'cartilaginous joints (symphyses)',
      'synovial joints (freely movable)',
    ]);
    // The card's own threshold: 11 words, so a limit of 20 keeps it whole.
    expect(chunkText(long, 35, 20)).toBeNull();
    // Whatever the percentage, but 100 or more.
    expect(chunkText(long, 15)).toHaveLength(3);
    expect(chunkText(long, 100)).toBeNull();
  });

  it('chunkDifficulty >= 100 still means no chunking', () => {
    expect(chunkText(six, 100)).toBeNull();
  });

  it('uses the same percentage on items as on words', () => {
    // 8 items x 35% = 2.8 -> 3 per chunk: [3, 3, 2].
    expect(chunkText('a, b, c, d, e, f, g, h', 35)).toEqual(['a, b, c', 'd, e, f', 'g, h']);
    // 8 items x 50% = 4 per chunk.
    expect(chunkText('a, b, c, d, e, f, g, h', 50)).toEqual(['a, b, c, d', 'e, f, g, h']);
  });
});

describe('chunkText word rule and parentheses', () => {
  it('moves a cut inside parentheses to just after the closing word', () => {
    // 12 words x 35% = 4 per chunk; the first cut would fall after "(w3 w4".
    expect(chunkText('w1 w2 (w3 w4 w5 w6 w7 w8 w9 w10) w11 w12', 35)).toEqual([
      'w1 w2 (w3 w4 w5 w6 w7 w8 w9 w10)',
      'w11 w12',
    ]);
  });

  it('cuts as before when no parenthesis is open at the cut', () => {
    expect(chunkText('one two three four five six seven eight nine ten eleven twelve', 35)).toEqual([
      'one two three four',
      'five six seven eight',
      'nine ten eleven twelve',
    ]);
  });
});

describe('everything that reads chunks follows', () => {
  it('buildItem chunks a list by items, and the minimum trials count those chunks', () => {
    const item = buildItem({ front: 'Q', back: 'a, b, c, d, e, f' }, 0, 35, 'cumulative', 8);
    expect(item.stage).toBe('chunks');
    expect(item.chunks).toEqual(['a, b', 'c, d', 'e, f']);
    // 3 chunks + 1 intermediate window + 1 x encodeReps final window + 1 cycle + 1 final.
    expect(computeMinimumTrials([item], 1)).toBe(3 + 1 + 1 + 1 + 1);
  });
});
