/// <reference types="node" />
// Records the TS engine's outputs as golden data for the Python port's parity
// tests (anki-addon/tests/engine/test_*_golden.py). The TS engine is the
// reference: the Python engine must reproduce every value here exactly.
//
// Run from the repo root:  npx tsx anki-addon/tools/export_golden.ts
//
// Output is deterministic: every input comes from a seeded mulberry32, keys
// are sorted, there are no timestamps, and the files are ASCII-only (every
// non-ASCII UTF-16 code unit is written as a \u escape, so invisible
// characters survive editors). Re-running it must give no diff.
//
// Non-ASCII characters in this file are written as \u{...} escapes for the
// same reason.

import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import type { DeckItem, DrillItem, LadderMode } from '../../src/types';
import { computeWordDiff, exactMatch, grade, norm } from '../../src/utils/grading';
import {
  buildCombineSequence,
  buildItem,
  buildItems,
  chunkText,
  culpritHalf,
  findAllCulpritChunks,
  MIN_WORDS_TO_CHUNK,
  normalizeItem,
  parseDeck,
  partitionIntoBatches,
  renderFirstLetterCue,
  requiredRepsForWindow,
  resolveBatchConfig,
  resolveSourceDeckEditable,
  selectNextEncodeItem,
  shuffle,
  slugify,
  splitInHalf,
} from '../../src/utils/items';
import { characterizationDeck, FOUR_CHUNK_BACK, TWO_CHUNK_BACK } from '../../src/test/fixtures/deck';
import { mediumDeck } from '../../test/fixtures/mediumDeck';
import { proseDeck } from '../../test/fixtures/proseDeck';
import { shortDeck } from '../../test/fixtures/shortDeck';
import { hashSeed, mulberry32, withSeededRandom } from '../../test/prng';

const OUT_DIR = join(dirname(fileURLToPath(import.meta.url)), '..', 'tests', 'golden');

// ---------------------------------------------------------------------------
// Deterministic JSON

function sortKeys(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sortKeys);
  if (value !== null && typeof value === 'object') {
    const out: Record<string, unknown> = {};
    for (const key of Object.keys(value).sort()) {
      const v = (value as Record<string, unknown>)[key];
      if (v !== undefined) out[key] = sortKeys(v); // JSON.stringify drops undefined too
    }
    return out;
  }
  return value;
}

function asciiOnly(json: string): string {
  let out = '';
  for (let i = 0; i < json.length; i++) {
    const c = json.charCodeAt(i);
    out += c < 0x7f ? json[i] : '\\u' + c.toString(16).padStart(4, '0');
  }
  return out;
}

function compact(value: unknown): string {
  return asciiOnly(JSON.stringify(sortKeys(value)));
}

// One top-level key per section; an array section gets one element per line
// so a parity failure diffs to the case that changed.
function writeGolden(name: string, sections: Record<string, unknown>): void {
  const parts = Object.keys(sections)
    .sort()
    .map(key => {
      const v = sections[key];
      const body = Array.isArray(v) ? '[\n' + v.map(compact).join(',\n') + '\n]' : compact(v);
      return `${JSON.stringify(key)}: ${body}`;
    });
  mkdirSync(OUT_DIR, { recursive: true });
  writeFileSync(join(OUT_DIR, name), '{\n' + parts.join(',\n') + '\n}\n', 'utf8');
}

// ---------------------------------------------------------------------------
// Seeded input generation

function makeRng(label: string) {
  const next = mulberry32(hashSeed(label));
  const int = (lo: number, hi: number) => lo + Math.floor(next() * (hi - lo + 1));
  const pick = <T>(xs: readonly T[]): T => xs[Math.floor(next() * xs.length)];
  const chance = (p: number) => next() < p;
  return { next, int, pick, chance };
}

const TAB = '\t';
const NBSP = '\u{a0}';
const BOM = '\u{feff}';
const EN_DASH = '\u{2013}';
const EM_DASH = '\u{2014}';
const MINUS = '\u{2212}';
const LSQUO = '\u{2018}';
const RSQUO = '\u{2019}';
const LDQUO = '\u{201c}';
const RDQUO = '\u{201d}';
const E_ACUTE = '\u{e9}';
const E_GRAVE = '\u{e8}';
const N_TILDE = '\u{f1}';
const U_UML = '\u{fc}';
const C_CED = '\u{e7}';

const LETTERS = 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ'.split('');
const DIGITS = '0123456789'.split('');
const OTHER_CHARS = [
  ' ', TAB, NBSP, BOM,
  '.', ',', '-', EN_DASH, EM_DASH, MINUS, '/', '(', ')', "'", '"',
  LSQUO, RSQUO, LDQUO, RDQUO, ':', ';', '!', '?', '+', '%', '<', '>', '=',
  E_ACUTE, N_TILDE, U_UML, C_CED,
];

const TS_STOPWORDS = [
  'a', 'an', 'the', 'of', 'to', 'in', 'on', 'for', 'and', 'or', 'is', 'are',
  'was', 'were', 'that', 'this', 'it', 'its', 'as', 'at', 'by', 'with', 'from',
];

const CONTENT_WORDS = [
  'cat', 'river', 'tree', 'walk', 'heart', 'blood', 'pump', 'cell', 'energy', 'tissue',
  'valve', 'artery', 'vein', 'muscle', 'lung', 'kidney', 'box', 'church', 'run', 'make',
  'use', 'inflammation', 'stomach', 'joint', 'pressure', 'rate', 'normal', 'range', 'acid',
  'oxygen', 'glucose', 'membrane', 'water', 'move', 'flow', 'slow', 'fast', 'large',
  'green', 'quiet', 'Heart', 'BLOOD', 'Paris', 'not', 'never', 'caf' + E_ACUTE,
  'M' + E_ACUTE + 'ni' + E_GRAVE + 're', 'ni' + N_TILDE + 'o', U_UML + 'ber', 'fa' + C_CED + 'ade',
];

const SPECIAL_TOKENS = [
  'cardi/o', '-itis', '-emia', 'brady-', 'pre-op', 'and/or', 'Na+', 'K+', '7.4', '7,4',
  '7.35-7.45', '-5', '+2', '<60', '>100', '5%', '10mg', '10-20', '10' + EN_DASH + '20',
  MINUS + '5', 'x', 'pH', "don't", 'don' + RSQUO + 't', 'M' + E_ACUTE + 'ni' + E_GRAVE + "re's",
  '(fast)', '"quoted"', LDQUO + 'quoted' + RDQUO, LSQUO + 'single' + RSQUO, 'e.g.', 'end.',
  'why?', 'stop!', '1.2.3', '1,000.50', '.5', '5.', '--5', 'a--5', '(-5)', '=',
];

const SEPARATORS = [' ', ' ', ' ', ' ', ' ', '  ', TAB, NBSP, ' - ', ', ', '/', ' (', ') ', '. ', ' ' + BOM, ': '];

function randomToken(r: ReturnType<typeof makeRng>): string {
  const len = r.int(1, 7);
  let s = '';
  for (let i = 0; i < len; i++) {
    const roll = r.next();
    s += roll < 0.6 ? r.pick(LETTERS) : roll < 0.75 ? r.pick(DIGITS) : r.pick(OTHER_CHARS);
  }
  return s;
}

function randomWord(r: ReturnType<typeof makeRng>): string {
  const roll = r.next();
  if (roll < 0.35) return r.pick(CONTENT_WORDS);
  if (roll < 0.55) return r.pick(TS_STOPWORDS);
  if (roll < 0.7) return r.pick(SPECIAL_TOKENS);
  return randomToken(r);
}

function randomText(r: ReturnType<typeof makeRng>, minWords = 1, maxWords = 10): string {
  const n = r.int(minWords, maxWords);
  let s = '';
  for (let i = 0; i < n; i++) {
    if (i) s += r.pick(SEPARATORS);
    s += randomWord(r);
  }
  if (r.chance(0.1)) s = r.pick([' ', TAB, NBSP, BOM, '  ']) + s;
  if (r.chance(0.1)) s += r.pick(['.', '!', '?', ' ', TAB, NBSP, BOM, '...', ')']);
  if (r.chance(0.05)) s = '(' + s + ')';
  return s;
}

const ACCENTS: Record<string, string> = { e: E_ACUTE, n: N_TILDE, u: U_UML, c: C_CED };
const PUNCT_SWAPS = ['', '.', ',', '-', EN_DASH, EM_DASH, MINUS, '/', "'", RSQUO, '"', LDQUO, ':', ';', '!', '?', '+', '%'];

type Mutation = (s: string, r: ReturnType<typeof makeRng>) => string;

function onWords(s: string, f: (words: string[]) => string[]): string {
  return f(s.split(' ')).join(' ');
}

const MUTATIONS: Mutation[] = [
  // drop a word
  (s, r) => onWords(s, w => (w.length > 1 ? w.filter((_, i) => i !== r.int(0, w.length - 1)) : w)),
  // add a stopword
  (s, r) =>
    onWords(s, w => {
      const at = r.int(0, w.length);
      return [...w.slice(0, at), r.pick(TS_STOPWORDS), ...w.slice(at)];
    }),
  // remove a stopword
  s => onWords(s, w => {
    const idx = w.findIndex(x => TS_STOPWORDS.includes(x.toLowerCase()));
    return idx === -1 ? w : w.filter((_, i) => i !== idx);
  }),
  // add s / ed / ing / es
  (s, r) => onWords(s, w => {
    const i = r.int(0, w.length - 1);
    const out = w.slice();
    out[i] = out[i] + r.pick(['s', 'ed', 'ing', 'es']);
    return out;
  }),
  // remove a trailing s
  s => onWords(s, w => w.map(x => (x.length > 2 && x.endsWith('s') ? x.slice(0, -1) : x))),
  // change punctuation
  (s, r) => s.replace(/[.,\-/'":;!?+%()\u{2013}\u{2014}\u{2212}\u{2018}\u{2019}\u{201c}\u{201d}]/gu, () => r.pick(PUNCT_SWAPS)),
  // strip all punctuation
  s => s.replace(/[^\p{L}\p{N}\s]/gu, ''),
  // insert punctuation
  (s, r) => {
    const at = r.int(0, s.length);
    return s.slice(0, at) + r.pick(PUNCT_SWAPS) + s.slice(at);
  },
  // change case
  (s, r) => r.pick([s.toUpperCase(), s.toLowerCase(), s.charAt(0).toUpperCase() + s.slice(1)]),
  // add accents
  s => s.replace(/[enuc]/g, ch => ACCENTS[ch]),
  // swap two adjacent words
  (s, r) => onWords(s, w => {
    if (w.length < 2) return w;
    const i = r.int(0, w.length - 2);
    const out = w.slice();
    [out[i], out[i + 1]] = [out[i + 1], out[i]];
    return out;
  }),
  // replace a word
  (s, r) => onWords(s, w => {
    const out = w.slice();
    out[r.int(0, w.length - 1)] = randomWord(r);
    return out;
  }),
  // insert a content word
  (s, r) => onWords(s, w => {
    const at = r.int(0, w.length);
    return [...w.slice(0, at), r.pick(CONTENT_WORDS), ...w.slice(at)];
  }),
  // change whitespace
  (s, r) => s.replace(/ /g, () => r.pick([' ', '  ', TAB, NBSP, ' ' + BOM, ' '])),
  // pad the ends
  (s, r) => r.pick([' ', TAB, NBSP, BOM, '\n']) + s + r.pick(['', ' ', TAB, NBSP, BOM, '\n']),
  // truncate
  (s, r) => s.slice(0, r.int(0, s.length)),
];

function mutate(s: string, r: ReturnType<typeof makeRng>): string {
  const count = r.pick([0, 1, 1, 1, 2, 2, 3]);
  let out = s;
  for (let i = 0; i < count; i++) out = r.pick(MUTATIONS)(out, r);
  return out;
}

// Long answers for the similarity >= 0.9 boundary: n words with one
// stem-level slip give similarity (n-1)/n, so 9 words is below and 10 above.
function nearBoundaryPair(r: ReturnType<typeof makeRng>): [string, string] {
  const n = r.int(8, 14);
  const words: string[] = [];
  for (let i = 0; i < n; i++) words.push(r.chance(0.25) ? r.pick(TS_STOPWORDS) : r.pick(CONTENT_WORDS));
  const target = words.join(' ');
  const typedWords = words.slice();
  const i = r.int(0, n - 1);
  const kind = r.int(0, 5);
  if (kind === 0) typedWords[i] = typedWords[i] + r.pick(['s', 'ed', 'ing', 'es']);
  else if (kind === 1) typedWords[i] = typedWords[i].endsWith('s') ? typedWords[i].slice(0, -1) : typedWords[i] + 's';
  else if (kind === 2) typedWords[i] = r.pick(CONTENT_WORDS);
  else if (kind === 3) typedWords.splice(i, 0, r.pick(CONTENT_WORDS));
  else if (kind === 4) typedWords.splice(i, 1);
  else typedWords.splice(i, 0, r.pick(TS_STOPWORDS));
  return r.chance(0.5) ? [typedWords.join(' '), target] : [target, typedWords.join(' ')];
}

// ---------------------------------------------------------------------------
// Hand-picked grading cases

const SPEC_PAIRS: [string, string][] = [
  // grade.spec.ts
  ['the cat sat on the mat', 'the cat sat on the mat'],
  ['wait for bus', 'wait for the bus'],
  ['wait for the bus', 'wait for bus'],
  ['large green trees grow slowly near the quiet flowing river', 'large green trees grow slowly near the quiet flowing rivers'],
  ['large green trees grow slowly near the quiet flowing streams', 'large green trees grow slowly near the quiet flowing rivers'],
  ['energy makes cell the mitochondria', 'the mitochondria makes cell energy'],
  ['', 'the mitochondria makes cell energy'],
  ['dog', 'cat'],
  ['pre op', 'pre-op'],
  ['and or', 'and/or'],
  ['10 mg', '10mg'],
  ['Menieres disease', 'M' + E_ACUTE + 'ni' + E_GRAVE + "re's disease"],
  ['Na +', 'Na+'],
  ['5 %', '5%'],
  ['itis', '-itis'],
  ['dont', "don't"],
  ['7.4', '7.4'],
  ['-5', MINUS + '5'],
  ['- 5', '-5'],
  ['10 20', '10-20'],
  ['10 - 20', '10-20'],
  ['tachycardia fast heart rate', 'tachycardia (fast heart rate)'],
  ['74', '7.4'],
  ['60', '<60'],
  ['Na', 'Na+'],
  ['5', '-5'],
  ['BE 2 to 2', 'BE -2 to +2'],
  ['tachycardia', 'tachycardia (fast heart rate)'],
  // strictPunctuation.spec.ts
  ['the fight or flight response', 'the "fight or flight" response'],
  ['normal range 7.35-7.45', 'normal range: 7.35-7.45'],
  ['heart lungs kidneys', 'heart, lungs, kidneys'],
  ['the end', 'The end.'],
  ['dont', 'don' + RSQUO + 't'],
  ['pre-op', 'pre' + EM_DASH + 'op'],
  ['Menieres disease', 'M' + E_ACUTE + 'ni' + E_GRAVE + 're' + RSQUO + 's disease'],
  ['Meni' + E_GRAVE + 're', 'Meni' + E_GRAVE + 're'],
  ['inflammation of stomach', 'inflammation of the stomach'],
  ['inflammation of the joint', 'inflammation of the joints'],
];

const ARABIC_3 = '\u{663}';
const ARABIC_4 = '\u{664}';
const ARABIC_5 = '\u{665}';
const FULLWIDTH_7 = '\u{ff17}';
const FULLWIDTH_4 = '\u{ff14}';
const DEVANAGARI_5 = '\u{96b}';

const EDGE_PAIRS: [string, string][] = [
  // decimals, negatives and ranges
  ['7,4', '7.4'], ['7. 4', '7.4'], ['7 .4', '7.4'], ['1.2.3', '1.2.3'], ['123', '1.2.3'],
  ['1,000.50', '1000.50'], ['.5', '0.5'], ['5.', '5'], ['-0.5', '-.5'],
  ['x -5', 'x 5'], ['x -5', 'x-5'], ['x-5', 'x 5'], ['x - 5', 'x -5'], ['type-2', 'type 2'],
  ['BE 2 to +2', 'BE -2 to +2'], ['temperature -5', 'temperature 5'], ['(-5)', '-5'], ['[-5]', '5'],
  ['--5', '-5'], ['- -5', '-5'], ['+-5', '+5'], ['a--5', 'a5'], ['5 -5', '5 5'], ['5-5', '55'],
  [TAB + '-5', '-5'], [NBSP + '-' + NBSP + '5', '-5'], ['-' + TAB + '5', '-5'], ['10' + EN_DASH + '20', '10-20'],
  [MINUS + MINUS + '5', '-5'], ['-' + BOM + '5', '-5'], ['.-5', '-5'], ['7.4-5', '7.45'],
  ['-itis', 'itis'], ['- itis', '-itis'], ['-emia', 'emia'], ['brady-', 'brady'],
  ['cardi/o', 'cardio'], ['cardi/o', 'cardi o'], ['cardi / o', 'cardi/o'],
  ['a b', 'ab'], ['a b', 'a  b'], ['a b', 'a' + TAB + 'b'], ['a b', 'a' + NBSP + 'b'],
  // empty and whitespace-only
  ['', ''], ['', 'x'], ['x', ''], [' ', ''], [TAB, NBSP], [BOM, ''], ['  ', ' '], ['', '-'], ['-', ''],
  [BOM + 'a', 'a'], ['a' + BOM, 'a'], ['a' + BOM + 'b', 'a b'],
  // quotes and apostrophes
  [LDQUO + 'quoted' + RDQUO, '"quoted"'], [LSQUO + 'single' + RSQUO, "'single'"],
  ['don' + RSQUO + 't', "don't"], ["don't", 'dont'],
  // punctuation-only tokens
  ['the cat sat', 'the cat ' + EM_DASH + ' sat'], ['cat sat', 'the cat ' + EM_DASH + ' sat'],
  ['cat sat', 'the cat - sat'], ['a b c', 'a / b / c'],
  // strict-only shapes
  ['end', 'end...'], ['end', 'end?!'], ['eg this', 'e.g. this'], ['7.35', '7.35.'], ['ab', 'a.b'],
  ['a b', 'a. b'], ['hello', 'Hello!\n'], ['a b', '(a) [b]'], ['a b', '{a}; b:'],
  // extra content word in a long answer
  ['the heart does not pump blood to the lungs and the body', 'the heart does pump blood to the lungs and the body'],
  ['large green trees never grow slowly near the quiet flowing rivers', 'large green trees grow slowly near the quiet flowing rivers'],
  // stem slips at the 0.9 boundary (9, 10 and 11 words)
  ['one two three four five six seven eight river', 'one two three four five six seven eight rivers'],
  ['one two three four five six seven eight nine river', 'one two three four five six seven eight nine rivers'],
  ['one two three four five six seven eight nine ten river', 'one two three four five six seven eight nine ten rivers'],
  ['one two three four five six seven eight nine walk', 'one two three four five six seven eight nine walked'],
  ['one two three four five six seven eight nine walk', 'one two three four five six seven eight nine walking'],
  ['one two three four five six seven eight nine box', 'one two three four five six seven eight nine boxes'],
  ['one two three four five six seven eight nine tissue', 'one two three four five six seven eight nine tissues'],
  ['one two three four five six seven eight nine valve', 'one two three four five six seven eight nine valves'],
  ['one two three four five six seven eight nine use', 'one two three four five six seven eight nine used'],
  ['one two three four five six seven eight nine make', 'one two three four five six seven eight nine making'],
  ['one two three four five six seven eight nine is', 'one two three four five six seven eight nine was'],
  // Unicode digits: JS \d is ASCII-only
  [ARABIC_3 + '.' + ARABIC_4, '3.4'], [ARABIC_3 + '.' + ARABIC_4, '.'], ['-' + ARABIC_5, '-5'], ['-' + ARABIC_5, '-'],
  [FULLWIDTH_7 + '.' + FULLWIDTH_4, '7.4'], ['-' + DEVANAGARI_5, '-5'], ['x' + DEVANAGARI_5, 'x'],
  // the private-use markers typed by the user
  ['\u{e000}', '.'], ['a\u{e001}5', 'a-5'], ['7\u{e000}4', '7.4'],
  // toLowerCase and NFKD corners
  ['\u{130}stanbul', 'istanbul'], ['\u{39f}\u{394}\u{39f}\u{3a3}', '\u{3bf}\u{3b4}\u{3bf}\u{3c2}'],
  ['\u{3a3}\u{391}\u{3a3} \u{3a3}', '\u{3c3}\u{3b1}\u{3c2} \u{3c3}'], ['Stra\u{df}e', 'STRASSE'], ['\u{1e9e}', '\u{df}'],
  ['\u{1c5}', '\u{1c6}'], ['\u{212a}elvin', 'kelvin'], ['\u{212b}ngstr\u{f6}m', 'angstrom'],
  ['\u{fb01}ne', 'fine'], ['\u{bd}', '1/2'], ['x\u{b2}', 'x2'], ['\u{2460}', '1'], ['\u{2026}', '...'],
  ['\u{216b}', 'xii'], ['\u{ff46}\u{ff55}\u{ff4c}\u{ff4c}', 'full'], ['na\u{ef}ve', 'naive'],
  ['e\u{301}', E_ACUTE], ['\u{1e9b}\u{323}', 's'],
  // Python-only whitespace and other near-whitespace
  ['a\u{1c}b', 'a b'], ['a\u{1f}b', 'a b'], ['a\u{85}b', 'a b'], ['a\u{180e}b', 'a b'],
  ['a\u{200b}b', 'a b'], ['a\u{2028}b', 'a b'], ['a\u{2029}b', 'a b'], ['a\u{3000}b', 'a b'],
  ['\u{1c}a\u{1c}', 'a'], ['\u{85}a', 'a'], ['a\u{200b}', 'a'],
  // astral characters
  ['a \u{1f600} b', 'a b'], ['\u{1f600}', ''], ['\u{1f600}', '\u{1f600}'], ['caf\u{e9} \u{1f600}', 'cafe'],
];

function stopwordPairs(): [string, string][] {
  const pairs: [string, string][] = [];
  for (const w of TS_STOPWORDS) {
    pairs.push(['alpha beta gamma', `alpha ${w} beta gamma`]);
    pairs.push([`alpha ${w.toUpperCase()} beta gamma`, 'alpha beta gamma']);
  }
  return pairs;
}

function gradingPairs(): [string, string][] {
  const r = makeRng('golden:grading');
  const pairs: [string, string][] = [...SPEC_PAIRS, ...EDGE_PAIRS, ...stopwordPairs()];
  const RANDOM_CASES = 1700;
  for (let i = 0; i < RANDOM_CASES; i++) {
    const roll = r.next();
    if (roll < 0.6) {
      const target = randomText(r);
      pairs.push([mutate(target, r), target]);
    } else if (roll < 0.7) {
      const target = randomText(r);
      pairs.push([target, mutate(target, r)]);
    } else if (roll < 0.78) {
      pairs.push([randomText(r), randomText(r)]);
    } else if (roll < 0.9) {
      pairs.push(nearBoundaryPair(r));
    } else {
      const target = randomText(r);
      pairs.push(r.pick([['', target], [target, ''], [r.pick([' ', TAB, NBSP, BOM]), target]] as [string, string][]));
    }
  }
  return pairs;
}

// ---------------------------------------------------------------------------
// prng.json

function exportPrng(): void {
  const labels = [
    '',
    'a',
    'current:shortDeck:realistic',
    'current:shortDeck:perfect',
    'current:proseDeck:struggling',
    'current:mediumDeck:realistic',
    'legacy:shortDeck:realistic',
    'golden:grading',
    'golden:items',
    'Recall Drill',
    'x'.repeat(1000),
    'caf' + E_ACUTE,
    'M' + E_ACUTE + 'ni' + E_GRAVE + 're',
    '\u{1f600}',
    'deck \u{1f600} ok \u{10ffff}',
    '\u{0}',
    'tab' + TAB + 'here',
    NBSP + BOM,
    '\u{d800}', // lone surrogate: charCodeAt still sees one code unit
    '\u{dfff}x\u{d83d}',
  ];
  const seeds = [hashSeed('current:shortDeck:realistic'), 0, 2 ** 32 + 41];
  writeGolden('prng.json', {
    hashSeed: labels.map(label => ({ label, value: hashSeed(label) })),
    mulberry32: seeds.map(seed => {
      const next = mulberry32(seed);
      return { seed, outputs: Array.from({ length: 1000 }, () => next()) };
    }),
  });
}

// ---------------------------------------------------------------------------
// jscompat.json: JS built-ins whose Python counterparts differ (or might)

const CHUNK_PERCENTS = [10, 15, 20, 25, 30, 35, 40, 50, 60, 75, 99, 100];
const MIN_WORDS = [4, 6, 8, 10];

function exportJscompat(): void {
  const roundInputs = [
    0, 0.5, 1.5, 2.5, 3.5, 4.5, -0.5, -1.5, -2.5, 0.49999999999999994, 1.4999999999999998,
    2 ** 52 - 0.5, 2 ** 52 + 1, 2 ** 53, 7.000000000000001, 4.199999999999999, 1e-300, -1e-300,
  ];
  // Every value chunkText rounds over the items.json grid.
  for (let n = 1; n <= 40; n++) {
    for (const p of CHUNK_PERCENTS) {
      const pct = Math.max(15, Math.min(100, p));
      roundInputs.push(n * (pct / 100));
    }
  }
  const wsProbe = [
    TAB, '\n', '\u{b}', '\u{c}', '\r', ' ', NBSP, '\u{1680}', '\u{2000}', '\u{2005}', '\u{200a}',
    '\u{2028}', '\u{2029}', '\u{202f}', '\u{205f}', '\u{3000}', BOM,
    // not JS whitespace (some are Python whitespace)
    '\u{1c}', '\u{1d}', '\u{1e}', '\u{1f}', '\u{85}', '\u{180e}', '\u{200b}', '\u{2060}', '\u{0}', 'x',
  ];
  const lowerInputs = [
    'ABC', '\u{130}', '\u{3a3}', '\u{3a3}\u{391}\u{3a3}', '\u{39f}\u{394}\u{39f}\u{3a3} \u{3a3}.', '\u{1e9e}',
    '\u{1c4}\u{1c5}\u{1c6}', '\u{212a}', '\u{212b}', '\u{3d2}', '\u{10400}', 'I\u{307}', '\u{1f88}',
    '\u{24b6}', '\u{ff21}',
  ];
  const nfkdInputs = [
    E_ACUTE, '\u{fb01}', '\u{bd}', '\u{b2}', '\u{2460}', '\u{2026}', '\u{216b}', '\u{ff46}', '\u{1e9b}\u{323}',
    '\u{2126}', '\u{fdfa}', '\u{3300}', '\u{1d400}', '\u{2163}', '\u{ac00}', '\u{e000}', MINUS, RSQUO,
  ];
  const truthyInputs: unknown[] = [[], {}, 0, '', null, false, true, 'a', 1, -1, 0.5, [0], { a: 0 }, ' '];
  writeGolden('jscompat.json', {
    mathRound: roundInputs.map(x => ({ x, out: Math.round(x) })),
    whitespace: wsProbe.map(c => ({
      ch: c,
      trim: (c + 'a' + c + 'b' + c).trim(),
      split: ('a' + c + 'b' + c + c + 'c').split(/\s+/),
      splitEdges: (c + 'a' + c).split(/\s+/),
      isWs: /\s/.test(c),
    })),
    toLowerCase: lowerInputs.map(s => ({ s, out: s.toLowerCase() })),
    nfkd: nfkdInputs.map(s => ({ s, out: s.normalize('NFKD') })),
    truthy: truthyInputs.map(v => ({ value: v, out: !!v })),
  });
}

// ---------------------------------------------------------------------------
// grading.json

type GradeCombo = { lenient?: boolean; stemTolerance?: boolean; strictPunctuation?: boolean };

const GRADE_COMBOS: [string, GradeCombo | undefined][] = [['default', undefined]];
for (const lenient of [false, true]) {
  for (const stemTolerance of [false, true]) {
    for (const strictPunctuation of [false, true]) {
      GRADE_COMBOS.push([
        `L${+lenient}S${+stemTolerance}P${+strictPunctuation}`,
        { lenient, stemTolerance, strictPunctuation },
      ]);
    }
  }
}

// Size: to stay small, a case stores a diff once when the lenient and strict
// diffs are equal ({both}), and stores each distinct grade() result once,
// without `diff`, with `grade` listing the result index per GRADE_COMBOS entry.
// grade()'s diff is computeWordDiff(typed, target, strict) (checked here), and
// the tests put it back before comparing, so they still compare whole results.
function exportGrading(pairs: [string, string][]): void {
  const cases = pairs.map(([typed, target]) => {
    const lenientDiff = computeWordDiff(typed, target, false);
    const strictDiff = computeWordDiff(typed, target, true);
    const sameDiff = JSON.stringify(lenientDiff) === JSON.stringify(strictDiff);
    const results: string[] = [];
    const gradeIdx: number[] = [];
    for (const [key, opts] of GRADE_COMBOS) {
      const { diff, ...rest } = grade(typed, target, opts);
      const expectedDiff = opts?.strictPunctuation ? strictDiff : lenientDiff;
      if (JSON.stringify(diff) !== JSON.stringify(expectedDiff)) {
        throw new Error(`grade() diff != computeWordDiff for ${JSON.stringify([typed, target, key])}`);
      }
      const encoded = compact(rest);
      let idx = results.indexOf(encoded);
      if (idx === -1) idx = results.push(encoded) - 1;
      gradeIdx.push(idx);
    }
    return {
      typed,
      target,
      norm: [norm(typed), norm(target)],
      exactMatch: { lenient: exactMatch(typed, target), strict: exactMatch(typed, target, true) },
      wordDiff: sameDiff ? { both: lenientDiff } : { lenient: lenientDiff, strict: strictDiff },
      grade: gradeIdx,
      gradeResults: results.map(s => JSON.parse(s)),
    };
  });
  writeGolden('grading.json', {
    gradeCombos: GRADE_COMBOS.map(([key, opts]) => ({ key, opts: opts ?? null })),
    cases,
  });
}

// ---------------------------------------------------------------------------
// items.json

function words36(n: number): string {
  return Array.from({ length: n }, (_, i) => i.toString(36)).join(' ');
}

const LADDER_MODES: (LadderMode | undefined)[] = ['cumulative', 'exhaustive', undefined];

function exportItems(gradingTargets: string[]): void {
  // chunkText grid
  const gridTexts = Array.from({ length: 40 }, (_, i) => words36(i + 1));
  const chunkTextGrid: unknown[] = [];
  for (let n = 1; n <= 40; n++) {
    for (const pct of CHUNK_PERCENTS) {
      for (const min of MIN_WORDS) {
        chunkTextGrid.push({ n, pct, min, out: chunkText(gridTexts[n - 1], pct, min) });
      }
    }
  }
  const chunkTextDefaults = [...gridTexts, FOUR_CHUNK_BACK, TWO_CHUNK_BACK, ...proseDeck.map(c => c.back)].map(
    text => ({ text, out: chunkText(text), out50: chunkText(text, 50) })
  );

  // Grading-corpus targets: the cue for each, and chunking (irregular
  // whitespace between words) for the first 200 with 5+ words.
  const uniqueTargets = [...new Set(gradingTargets)];
  const targets = uniqueTargets.map(text => ({ text, cue: renderFirstLetterCue(text) }));
  const chunkTextIrregular = uniqueTargets
    .filter(text => text.split(/\s+/).filter(w => w).length >= 5)
    .slice(0, 200)
    .map(text => ({ text, out: chunkText(text, 20, 4) }));

  // Combine ladder
  const combine: unknown[] = [];
  for (let n = 0; n <= 8; n++) {
    for (const mode of LADDER_MODES) {
      const seq = mode === undefined ? buildCombineSequence(n) : buildCombineSequence(n, mode);
      combine.push({
        n,
        mode: mode ?? null,
        seq,
        reps: [1, 2, 3, 5].map(encodeReps => ({
          encodeReps,
          out: seq.map(w => requiredRepsForWindow(w, n, encodeReps)),
        })),
      });
    }
  }

  // Remediation helpers over chunked prose
  const r = makeRng('golden:items:remediation');
  const proseTexts = [
    ...proseDeck.map(c => c.back),
    ...mediumDeck.map(c => c.back),
    FOUR_CHUNK_BACK,
    TWO_CHUNK_BACK,
    'Tachycardia (fast heart rate) is a resting rate above 100 bpm, often with palpitations and dizziness.',
    'Normal arterial pH is 7.35-7.45; below 7.35 is acidosis, and above 7.45 is alkalosis in adults.',
    'The suffix -itis means inflammation, as in arthritis, gastritis, and cardi/o-related carditis today.',
    'Base excess ranges from -2 to +2 mEq/L, and a value below -2 suggests a metabolic acidosis.',
  ];
  const typedVariants: ((w: string[]) => string)[] = [
    w => w.join(' '),
    w => w.filter((_, i) => i !== r.int(0, w.length - 1)).join(' '),
    w => { const o = w.slice(); o[r.int(0, o.length - 1)] = r.pick(CONTENT_WORDS); return o.join(' '); },
    w => { const o = w.slice(); const i = r.int(0, Math.max(0, o.length - 2)); [o[i], o[i + 1]] = [o[i + 1], o[i]]; return o.join(' '); },
    w => { const o = w.slice(); o.splice(r.int(0, o.length), 0, r.pick(TS_STOPWORDS)); return o.join(' '); },
    w => w.map(x => x + (r.chance(0.2) ? 's' : '')).join(' '),
    w => w.join(' ').replace(/[^\p{L}\p{N}\s]/gu, '').toLowerCase(),
    () => '',
    w => w.slice(0, Math.ceil(w.length / 2)).join(TAB),
    w => w.join(' ') + ' extra words',
    w => ' ' + w.join(NBSP) + ' ',
  ];
  // chunkings: a prose text chunked at a percent. windows: a [startIdx, endIdx]
  // span of one chunking, with splitInHalf of its text. remediation: a typed
  // variant of one window, with findAllCulpritChunks and culpritHalf (over the
  // window's halves) in both punctuation modes.
  const chunkings: unknown[] = [];
  const windows: unknown[] = [];
  const remediation: unknown[] = [];
  const splitInHalfCases: unknown[] = [];
  for (const text of proseTexts) {
    for (const pct of [20, 35, 50]) {
      const chunks = chunkText(text, pct);
      if (!chunks) continue;
      const chunkingIdx = chunkings.push({ text, pct, chunks }) - 1;
      const exhaustive = buildCombineSequence(chunks.length, 'exhaustive');
      const spans = [
        { start: 1, end: 1 },
        { start: chunks.length, end: chunks.length },
        r.pick(exhaustive),
        ...buildCombineSequence(chunks.length, 'cumulative'),
      ];
      for (const w of spans.slice(0, 6)) {
        const startIdx = w.start - 1;
        const endIdx = w.end - 1;
        const windowText = chunks.slice(startIdx, endIdx + 1).join(' ');
        const halves = splitInHalf(windowText);
        const windowIdx = windows.push({ chunking: chunkingIdx, startIdx, endIdx, text: windowText, halves }) - 1;
        const [left, right] = halves;
        for (let v = 0; v < 2; v++) {
          const typed = r.pick(typedVariants)(windowText.split(' '));
          remediation.push({
            window: windowIdx,
            typed,
            findAllCulpritChunks: {
              lenient: findAllCulpritChunks(typed, chunks, startIdx, endIdx),
              strict: findAllCulpritChunks(typed, chunks, startIdx, endIdx, true),
            },
            culpritHalf: {
              lenient: culpritHalf(typed, left, right),
              strict: culpritHalf(typed, left, right, true),
            },
          });
        }
      }
      for (const c of chunks) splitInHalfCases.push({ text: c, out: splitInHalf(c) });
    }
  }
  for (const text of ['', 'a', 'a b', ' a', 'a  b', 'a b c', 'a' + TAB + 'b c', ' ', 'one two three four five']) {
    splitInHalfCases.push({ text, out: splitInHalf(text) });
  }
  const culpritHalfEdges = [
    ['', 'a', 'b'], ['  ', 'a b', 'c'], ['a b', 'a', 'b'], ['a' + TAB + 'b c', 'a b', 'c'],
    ['pre op x', 'pre-op', 'x'], ['b a', 'a', 'b'],
  ].map(([typed, left, right]) => ({
    typed, left, right,
    lenient: culpritHalf(typed, left, right),
    strict: culpritHalf(typed, left, right, true),
  }));

  // parseDeck
  const randomDeck = (rr: ReturnType<typeof makeRng>) => {
    const lines: string[] = [];
    for (let i = 0; i < rr.int(1, 8); i++) {
      const sep = rr.pick([TAB, '::', ' :: ', ' - ', ' -> ', '\t\t', '-', ': ']);
      const parts = [randomText(rr, 1, 3), randomText(rr, 0, 4)];
      if (rr.chance(0.4)) parts.push(randomText(rr, 0, 4));
      if (rr.chance(0.1)) parts.push(randomText(rr, 1, 2));
      let line = parts.join(sep);
      if (rr.chance(0.1)) line = rr.pick(['#', '//', '  #', ' ']) + line;
      lines.push(line);
    }
    return lines.join(rr.pick(['\n', '\r\n', '\n\n']));
  };
  const deckRng = makeRng('golden:items:parseDeck');
  const parseDeckInputs = [
    'mitochondria\tpowerhouse of the cell\talso does aerobic respiration',
    'front\tback',
    'Capital of France :: Paris :: Also the seat of the EU parliament sometimes',
    'Capital of France :: Paris',
    'f\tb\tpart one\tpart two',
    'f\tb\t   ',
    '# a comment\n\nf1\tb1\te1\n// another comment\nf2 :: b2',
    [
      'tab front\ttab back',
      'colon front::colon back::colon extra::more extra',
      'hyphen front - hyphen back - more back',
      'arrow -> not a card - really',
      'front only',
      '\tback only',
      'f\t\tb',
      'f ::  :: e',
      'f\tb :: x',
      'x - ',
      ' - y',
      '  // indented comment',
      '  # indented hash',
      'crlf front\tcrlf back\r',
      BOM + 'bom front\tbom back' + BOM,
      NBSP + 'nbsp front :: nbsp back' + NBSP,
      '\u{1c}fs front\tfs back\u{1c}',
      '\u{85}nel front\tnel back',
      'ls\u{2028}front\tback\u{2028}',
      'a - b',
      'a-b',
      'a :: b - c',
      'Ch. 5 - Cardio - Resp',
      'extra only\t\tthe extra',
    ].join('\n'),
    '',
    '\n\n\n',
  ];
  for (let i = 0; i < 30; i++) parseDeckInputs.push(randomDeck(deckRng));
  const parseDeckCases = parseDeckInputs.map(text => ({ text, out: parseDeck(text) }));

  // normalizeItem
  const [modernItem] = buildItems([{ front: 'Q', back: FOUR_CHUNK_BACK }], 20, 'cumulative', undefined, undefined, false);
  const fourChunks = modernItem.chunks;
  const legacyItems: Record<string, unknown>[] = [
    { ...modernItem },
    { ...modernItem, extra: 'note', finalDone: true, finalMisses: 2, attempts: 7, misses: 1, reveals: 1, nearMisses: 2, hardSpans: ['large green'] },
    { ...modernItem, extra: null, finalDone: null },
    // pre-C8a chunkStreak
    { id: 0, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', encodeStreak: 0, cycleStreak: 0, chunks: fourChunks, chunkIndex: 1, chunkStreak: 2, combineSeq: null, combineSeqIdx: 0, combineStreak: 0, combineMissCount: 0, remediateStack: [], remediateQueue: [], remediateReturnSeqIdx: 0, stage: 'chunks' },
    { id: 0, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, chunkIndex: 1, chunkStreak: 3, stage: 'chunks' },
    { id: 0, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, chunkIndex: 1, chunkStreak: 1, stage: 'chunks' },
    { id: 0, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, chunkIndex: 1, chunkStreak: 0, stage: 'chunks' },
    { id: 0, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, chunkStreak: 2, stage: 'combine', combineSeqIdx: 2 },
    // remediate with an empty stack
    { id: 1, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, chunkIndex: 3, chunkStreak: 1, stage: 'remediate', remediateStack: [] },
    { id: 1, front: 'Q', back: 'cats sleep often', status: 'encoding', chunks: null, chunkIndex: 2, chunkStreak: 2, stage: 'remediate', remediateStack: [] },
    { id: 1, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, chunkIndex: 3, chunkStreak: 2, stage: 'remediate' },
    { id: 1, front: 'Q', back: FOUR_CHUNK_BACK, status: 'ready', chunks: fourChunks, chunkIndex: 3, stage: 'remediate', remediateStack: [] },
    { id: 1, front: 'Q', back: FOUR_CHUNK_BACK, status: 'encoding', chunks: fourChunks, stage: 'remediate', remediateStack: [{ text: 'large green', streak: 0, missCount: 1 }] },
    // missing optional fields, and JS-falsy/truthy values
    { id: 0, front: 'f', back: 'b', status: 'new' },
    { id: 0, front: 'f', back: 'b' },
    { front: 'f', back: 'b' },
    { id: 3 },
    {},
    { id: 0, front: 'f', back: 'b', status: '', stage: '', chunks: [], combineSeq: [], remediateStack: null, remediateQueue: null },
    { id: 0, front: 'f', back: 'b', chunks: [], stage: 'chunks', chunkStreak: 5 },
    { id: 0, front: 'f', back: 'b', chunks: fourChunks, combineSeq: [] },
    { id: 0, front: 'f', back: 'b', chunks: fourChunks, encodeStreak: null, cycleStreak: null, chunkIndex: null, chunkStreak: null, combineSeqIdx: null, combineStreak: null, combineMissCount: null, remediateReturnSeqIdx: null },
    { id: 0, front: 'f', back: 'b', chunks: fourChunks, encodeStreak: 0, chunkIndex: 0, status: 'mastered', stage: 'full' },
    { id: 0, front: 'f', back: 'b', chunks: ['a b', 'c d', 'e f'], combineSeq: [{ start: 1, end: 3 }], combineSeqIdx: 0 },
  ];
  for (const item of buildItems(proseDeck.slice(0, 3), 35, 'exhaustive', undefined, undefined, false)) {
    legacyItems.push(JSON.parse(JSON.stringify(item)));
  }
  const normalizeCases = legacyItems.map(it => ({
    it,
    out: normalizeItem(JSON.parse(JSON.stringify(it))), // default ladderMode: 'cumulative'
    outExhaustive: normalizeItem(JSON.parse(JSON.stringify(it)), 'exhaustive'),
  }));

  // partitionIntoBatches
  const partitionCases: unknown[] = [];
  for (const n of [0, 1, 3, 4, 5, 7, 13]) {
    const items = Array.from({ length: n }, (_, i) => i);
    for (const size of [undefined, 0, -1, 1, 3, 5, n, n + 1, 100]) {
      partitionCases.push({ n, size: size ?? null, out: partitionIntoBatches(items, size) });
    }
  }

  // buildItems / shuffle under a seed
  const decks: Record<string, DeckItem[]> = {
    shortDeck,
    mediumDeck,
    proseDeck,
    characterizationDeck,
    extras: parseDeck('f1\tb1\te1\nf2 :: one two three four five six seven eight nine ten :: e2\nf3 - b3'),
    empty: [],
  };
  type BuildArgs = {
    chunkPercent?: number;
    ladderMode?: LadderMode;
    batchSize?: number;
    minWordsToChunk?: number;
    shuffleWithinBatch?: boolean;
  };
  const buildArgs: BuildArgs[] = [
    {},
    { chunkPercent: 35, ladderMode: 'cumulative', batchSize: 5, minWordsToChunk: 8, shuffleWithinBatch: true },
    { chunkPercent: 20, ladderMode: 'exhaustive', batchSize: 3, minWordsToChunk: 4, shuffleWithinBatch: true },
    { chunkPercent: 35, ladderMode: 'cumulative', batchSize: 5, shuffleWithinBatch: false },
    { chunkPercent: 100, ladderMode: 'cumulative', batchSize: 0, minWordsToChunk: 8, shuffleWithinBatch: true },
    { chunkPercent: 25, batchSize: 1 },
  ];
  const buildItemsCases: unknown[] = [];
  for (const deckName of Object.keys(decks)) {
    buildArgs.forEach((args, k) => {
      const seed = hashSeed(`golden:buildItems:${deckName}:${k}`);
      const [out, nextRandom] = withSeededRandom(seed, () => {
        const built = buildItems(
          decks[deckName],
          args.chunkPercent,
          args.ladderMode,
          args.batchSize,
          args.minWordsToChunk,
          args.shuffleWithinBatch
        );
        return [built, Math.random()] as const;
      });
      buildItemsCases.push({ deck: deckName, args, seed, out, nextRandom });
    });
  }
  const shuffleCases = [0, 1, 2, 3].map(k => {
    const seed = hashSeed(`golden:shuffle:${k}`);
    const inputs: unknown[][] = [[], [7], [1, 2], Array.from({ length: 10 }, (_, i) => i), ['a', 'b', 'c', 'd', 'e']];
    return withSeededRandom(seed, () => {
      const outs = inputs.map(a => shuffle(a));
      return { seed, inputs, outs, nextRandom: Math.random() };
    });
  });
  const buildItemCases = [
    [{ front: 'f', back: FOUR_CHUNK_BACK }, 4, 20, 'cumulative', 8],
    [{ front: 'f', back: FOUR_CHUNK_BACK, extra: 'x' }, 0, 20, 'exhaustive', 8],
    [{ front: 'f', back: FOUR_CHUNK_BACK }, 9, 50, 'cumulative', 10],
    [{ front: 'f', back: 'short' }, 1, 35, 'cumulative', 8],
  ].map(([p, id, pct, mode, min]) => ({
    p, id, pct, mode, min,
    out: buildItem(p as DeckItem, id as number, pct as number, mode as LadderMode, min as number),
  }));

  // selectNextEncodeItem (returns the batch's own object: recorded as its index)
  const statusSets = [
    ['new', 'new', 'new'],
    ['new', 'ready', 'encoding'],
    ['ready', 'ready', 'ready'],
    ['mastered', 'mastered', 'mastered', 'encoding', 'mastered'],
    ['mastered', 'ready', 'new'],
    ['encoding'],
    [],
    ['ready', 'new', 'ready', 'new'],
  ];
  const selectCases: unknown[] = [];
  statusSets.forEach((statuses, k) => {
    const batch = statuses.map((status, i) => ({ id: k === 7 ? [5, 5, 9, 2][i] : 10 + i, status }));
    const lastIds = [-1, 99, ...batch.map(b => b.id)];
    for (const lastItemId of lastIds) {
      const picked = selectNextEncodeItem(batch as unknown as DrillItem[], lastItemId);
      selectCases.push({ batch, lastItemId, out: picked === null ? null : batch.indexOf(picked as never) });
    }
  });

  const slugCases = [
    'Med Term', '  M' + E_ACUTE + 'ni' + E_GRAVE + 're' + RSQUO + 's Disease!! ', '---', '', '   ', 'Ch. 5: Cardio/Resp',
    '\u{c0}\u{c9}\u{ce}\u{d5}\u{dc}', '\u{130}stanbul', '123', 'a__b', NBSP + 'x' + BOM, '\u{1c}name\u{1c}',
    '\u{65e5}\u{672c}', '\u{1f600} deck', 'UPPER lower', 'Stra\u{df}e', '\u{fb01}le',
  ].map(name => ({ name, out: slugify(name) }));

  const resolveCases = [
    {}, { batchIndex: 2 }, { batchSize: 5 }, { batchIndex: 0, batchSize: 0 }, { batchIndex: null, batchSize: null },
    { batchIndex: 3, batchSize: 4 },
  ].flatMap(saved =>
    [0, 3].map(n => ({
      saved,
      n,
      out: resolveBatchConfig(saved as never, Array.from({ length: n }, () => ({}) as DrillItem)),
    }))
  );
  const sourceEditableCases = [{}, { sourceDeckEditable: true }, { sourceDeckEditable: false }, { sourceDeckEditable: null }].map(
    saved => ({ saved, out: resolveSourceDeckEditable(saved as never) })
  );

  writeGolden('items.json', {
    constants: { MIN_WORDS_TO_CHUNK },
    chunkTextGridTexts: gridTexts,
    chunkTextGrid,
    chunkTextDefaults,
    targets,
    chunkTextIrregular,
    combine,
    chunkings,
    windows,
    remediation,
    splitInHalf: splitInHalfCases,
    culpritHalfEdges,
    parseDeck: parseDeckCases,
    normalizeItem: normalizeCases,
    partitionIntoBatches: partitionCases,
    decks,
    buildItems: buildItemsCases,
    buildItem: buildItemCases,
    shuffle: shuffleCases,
    selectNextEncodeItem: selectCases,
    slugify: slugCases,
    resolveBatchConfig: resolveCases,
    resolveSourceDeckEditable: sourceEditableCases,
  });
}

// ---------------------------------------------------------------------------

const pairs = gradingPairs();
exportPrng();
exportJscompat();
exportGrading(pairs);
exportItems(pairs.map(([, target]) => target));
console.log(`golden data written to ${OUT_DIR}`);
