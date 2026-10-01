/// <reference types="node" />
// Records the TS engine's outputs as golden data for the Python port's parity
// tests (anki-addon/tests/engine/test_*_golden.py). The TS engine is the
// reference: the Python engine must reproduce every value here exactly.
//
// Run from the repo root:  npx tsx anki-addon/tools/export_golden.ts
//
// Debugging a session mismatch: `npx tsx anki-addon/tools/export_golden.ts
// --full <deck>:<learner>[:<run>]` (e.g. --full proseDeck:realistic:7) writes
// that seeded simulate() run's full state after every step to the gitignored
// anki-addon/tests/golden/_debug/ and nothing else. `python
// anki-addon/tools/simulate.py --full <same>` writes the Python side next to
// it; diff the two files.
//
// Output is deterministic: every input comes from a seeded mulberry32, keys
// are sorted, there are no timestamps, and the files are ASCII-only (every
// non-ASCII UTF-16 code unit is written as a \u escape, so invisible
// characters survive editors). Re-running it must give no diff.
//
// Non-ASCII characters in this file are written as \u{...} escapes for the
// same reason.

import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdirSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import type {
  DeckItem,
  DrillItem,
  Feedback,
  LadderMode,
  SavedSessionState,
  SessionConfig,
  SessionState,
  SessionStats,
  Trial,
  Verdict,
} from '../../src/types';
import {
  computeColdStartEstimate,
  computeCumulativeColdStartMultiplier,
  computeMinimumTrials,
  computeRemainingColdStartRange,
  estimateColdStartSeconds,
  formatColdStartRange,
  pickColdStartDeckShape,
  type ExposureLevel,
} from '../../src/utils/estimate';
import { buildHistoryCard, buildHistoryEntry, cardTroubleScore, rankHardestCards } from '../../src/utils/history';
import { computeItemProgress, computeSessionProgress } from '../../src/utils/progress';
import {
  advanceToNextBatch,
  applyAnswer,
  applyNext,
  computeAccuracyPercent,
  computeBatchSummary,
  DWELL_MS,
  editCurrentItem,
  emptyStats,
  initSession,
  orderCycleQueue,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../../src/utils/session';
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
import {
  characterizationDeck,
  CHUNK_DIFFICULTY,
  FOUR_CHUNK_BACK,
  FOUR_CHUNK_CHUNKS,
  FULL_STAGE_BACK,
  TWO_CHUNK_BACK,
  TWO_CHUNK_CHUNKS,
  TWO_CHUNK_DIFFICULTY,
} from '../../src/test/fixtures/deck';
import { mediumDeck } from '../../test/fixtures/mediumDeck';
import { proseDeck } from '../../test/fixtures/proseDeck';
import { shortDeck } from '../../test/fixtures/shortDeck';
import { hashSeed, mulberry32, withSeededRandom } from '../../test/prng';
import {
  perfectLearner,
  realisticLearner,
  simulate,
  strugglingLearner,
  type LearnerModel,
} from '../../test/simulate';

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

  // toFixed: exact ties (k/8), near-ties, signs, -0, the 1e21 cutoff, and
  // random doubles at several scales. JSON can't hold NaN/Infinity/-0, so
  // those inputs are written as strings and parsed back by the test.
  const fixedSpecial = ['NaN', 'Infinity', '-Infinity', '-0'];
  const fixedInputs: number[] = [
    0, 1, -1, 0.05, 0.15, 0.25, 0.35, 0.45, 0.5, 1.5, 2.5, -0.25, -0.04, -0.05, 1.005, 1.45, 2.675,
    4.35, 72, 72.04999999999999, 72.05, 999.95, 999.9500000000001, 123.456, 1234.5678, 0.000001,
    5e-7, 1e-10, 1e20, 999999999999999900000, 1e21, -1e21, 1.5e300, 2 ** 53, 2 ** 53 + 2,
    Number.MIN_VALUE, Number.MAX_VALUE, 210.66666666666666, 2729.0666666666666, 6.912928496213862,
  ];
  for (let k = -40; k <= 40; k++) fixedInputs.push(k / 8, k / 16 + 100);
  const fixedRng = makeRng('golden:jscompat:toFixed');
  for (let i = 0; i < 300; i++) {
    const scale = 10 ** fixedRng.int(-3, 6);
    fixedInputs.push((fixedRng.next() - 0.3) * scale);
  }
  const toFixed = [
    ...fixedSpecial.map(x => ({ x, digits: [0, 1, 2].map(d => (x === '-0' ? -0 : Number(x)).toFixed(d)) })),
    ...fixedInputs.map(x => ({ x, digits: [0, 1, 2, 3, 20].map(d => x.toFixed(d)) })),
  ];

  // toISOString: the epoch, both sides of it, leap days, the 4/6-digit year
  // switch, TimeClip's limits, and fractions (truncated toward zero).
  const isoInputs: (number | string)[] = [
    0, -1, 1, 999, 1000, 86399999, 86400000, -86400000, -86400001, 951782400000, 951868799999,
    4107542400000, 1727740800123, Date.UTC(2026, 8, 30, 9), Date.UTC(2026, 9, 1, 10, 5, 42, 7),
    253402300799999, 253402300800000, -62167219200000, -62167219200001, -62198755200000,
    8.64e15, -8.64e15, 1.5, -1.5, 0.9, -0.9, 1e12 + 0.9999, 'NaN', 'Infinity', '8640000000000001',
    '-8640000000000001',
  ];
  const isoRng = makeRng('golden:jscompat:toISOString');
  for (let i = 0; i < 60; i++) isoInputs.push(Math.floor((isoRng.next() * 2 - 1) * 8.64e15));
  const toISOString = isoInputs.map(x => {
    const ms = typeof x === 'string' ? Number(x) : x;
    try {
      return { ms: x, out: new Date(ms).toISOString() };
    } catch (e) {
      return { ms: x, out: null, error: (e as Error).name };
    }
  });

  const lengthInputs = ['', 'abc', E_ACUTE, '\u{1f600}', 'a\u{1f600}b\u{10ffff}', NBSP + BOM, 'M' + E_ACUTE + 'ni' + E_GRAVE + 're'];
  const sumRng = makeRng('golden:jscompat:sum');
  const sumInputs: number[][] = [[], [0.1, 0.2, 0.3], [1e16, 1, -1e16], [0.7, 0.7, 0.7, 0.35]];
  for (let i = 0; i < 20; i++) sumInputs.push(Array.from({ length: sumRng.int(2, 40) }, () => sumRng.next() * 0.7));

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
    toFixed,
    toISOString,
    length: lengthInputs.map(text => ({ text, out: text.length })),
    reduceSum: sumInputs.map(values => ({ values, out: values.reduce((a, b) => a + b, 0) })),
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

// ---------------------------------------------------------------------------
// Session engine (Phase 1b): session_sim.json, session_seed0.json,
// session_scenarios.json
//
// State hashes are SHA-256 over canonical JSON of the whole SessionState:
// sorted keys, no whitespace, non-ASCII characters unescaped, UTF-8. In
// Python: json.dumps(state, sort_keys=True, separators=(',', ':'),
// ensure_ascii=False). SessionState holds only integers, strings, booleans,
// null, lists and objects; stateHash() throws on anything else, so a float
// can't slip in and hash differently in the two languages.

const REPO_ROOT = join(dirname(fileURLToPath(import.meta.url)), '..', '..');
const DEBUG_DIR = join(OUT_DIR, '_debug');

function sha256(text: string): string {
  return createHash('sha256').update(text, 'utf8').digest('hex');
}

function assertIntegerJson(value: unknown, path: string): void {
  if (typeof value === 'number') {
    if (!Number.isInteger(value)) throw new Error(`float in SessionState at ${path}: ${value}`);
  } else if (Array.isArray(value)) {
    value.forEach((v, i) => assertIntegerJson(v, `${path}[${i}]`));
  } else if (value !== null && typeof value === 'object') {
    for (const [k, v] of Object.entries(value)) assertIntegerJson(v, `${path}.${k}`);
  } else if (value !== null && typeof value !== 'string' && typeof value !== 'boolean' && value !== undefined) {
    throw new Error(`unexpected ${typeof value} in SessionState at ${path}`);
  }
}

function stateHash(state: SessionState): string {
  assertIntegerJson(state, 'state');
  return sha256(JSON.stringify(sortKeys(state)));
}

// A JSON-shaped copy, taken when a step is recorded.
function snapshot<T>(value: T): T {
  return JSON.parse(JSON.stringify(value)) as T;
}

// ---------------------------------------------------------------------------
// session_sim.json / session_seed0.json: the simulate() scoreboard, run for run

// test/simulate.report.ts's config, decks and learners, in its order.
const SIM_CONFIG: SessionConfig = { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' };
const RUNS_PER_CONFIG = 50;
const SIM_DECKS: [string, DeckItem[]][] = [
  ['shortDeck', shortDeck],
  ['proseDeck', proseDeck],
  ['mediumDeck', mediumDeck],
];
// coldStartEstimate.consistency.spec.ts's mixed deck.
const MIXED_DECK: DeckItem[] = [...shortDeck.slice(0, 6), ...proseDeck.slice(0, 6)];
const SIM_LEARNERS: [string, LearnerModel][] = [
  ['perfect', perfectLearner],
  ['realistic', realisticLearner],
  ['struggling', strugglingLearner],
];

// test/simulate.ts's tunables.
const TYPING_CPS = 4.5;
const PER_TRIAL_OVERHEAD_SEC = 1.5;
const MAX_TRIALS = 20000;

interface SimStep {
  step: number;
  trial: Trial;
  typed: string;
  verdict: Verdict;
  feedback: Feedback;
  advance: 'auto' | 'manual';
  stateHash: string;
  state?: SessionState;
}

interface TracedRun {
  totalTrials: number;
  // Insertion order, which the report's tie-break on equal counts depends on.
  trialsByStage: [string, number][];
  keystrokes: number;
  wallClockEstimate: number;
  attempts: number;
  traceHash: string;
  initialStateHash: string;
  initialState?: SessionState;
  steps: SimStep[];
}

// A copy of test/simulate.ts's simulate() loop that also records each trial.
// Every run is cross-checked against the real simulate() (checkRealSimulate),
// so this copy can't drift from it unnoticed. traceHash is SHA-256 over one
// line per trial, `itemId|stage|cue.kind|target|typed|verdict|advance|dwellKey`,
// each ending in '\n'.
function simulateTraced(
  deck: DeckItem[],
  config: SessionConfig,
  learner: LearnerModel,
  minWordsToChunk: number = MIN_WORDS_TO_CHUNK,
  record: 'none' | 'hash' | 'full' = 'none'
): TracedRun {
  const items = buildItems(deck, config.chunkDifficulty, config.ladderMode, undefined, minWordsToChunk);
  let state: SessionState = initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    config,
  });
  const initialState = state;
  const initialStateHash = stateHash(state);
  const exposureCounts = new Map<string, number>();
  const trialsByStage: Record<string, number> = {};
  const lines: string[] = [];
  const steps: SimStep[] = [];
  let totalTrials = 0;
  let keystrokes = 0;

  while (totalTrials < MAX_TRIALS) {
    const trial = selectTrial(state);
    if (!trial) break;

    const key = `${trial.itemId}:${trial.stage}:${trial.target}`;
    const priorExposures = exposureCounts.get(key) ?? 0;
    exposureCounts.set(key, priorExposures + 1);

    const p = learner.pCorrect(priorExposures, trial.cue, priorExposures);
    const correct = Math.random() < p;
    const typed = correct ? trial.target : '';

    const result = applyAnswer(state, typed, { revealed: false });
    totalTrials++;
    trialsByStage[trial.stage] = (trialsByStage[trial.stage] ?? 0) + 1;
    keystrokes += trial.cue.kind === 'present' ? 0 : trial.target.length;

    state = result.state;
    if (result.advance === 'manual' && (state.phase === 'cycle' || state.phase === 'final')) {
      state = applyNext(state);
    }

    lines.push(
      [trial.itemId, trial.stage, trial.cue.kind, trial.target, typed, result.verdict, result.advance, result.feedback.dwellKey].join('|')
    );
    if (record !== 'none') {
      steps.push({
        step: totalTrials,
        trial: snapshot(trial),
        typed,
        verdict: result.verdict,
        feedback: snapshot(result.feedback),
        advance: result.advance,
        stateHash: stateHash(state),
        ...(record === 'full' ? { state: snapshot(state) } : {}),
      });
    }
  }

  if (totalTrials >= MAX_TRIALS) throw new Error(`simulateTraced(): exceeded MAX_TRIALS (${MAX_TRIALS})`);

  return {
    totalTrials,
    trialsByStage: Object.entries(trialsByStage),
    keystrokes,
    wallClockEstimate: keystrokes / TYPING_CPS + totalTrials * PER_TRIAL_OVERHEAD_SEC,
    attempts: state.stats.attempts,
    traceHash: sha256(lines.map(line => line + '\n').join('')),
    initialStateHash,
    ...(record === 'full' ? { initialState: snapshot(initialState) } : {}),
    steps,
  };
}

function checkRealSimulate(
  label: string,
  seed: number,
  deck: DeckItem[],
  config: SessionConfig,
  learner: LearnerModel,
  minWordsToChunk: number,
  traced: TracedRun
): void {
  const real = withSeededRandom(seed, () => simulate(deck, config, learner, minWordsToChunk));
  const same =
    real.totalTrials === traced.totalTrials &&
    real.keystrokes === traced.keystrokes &&
    real.wallClockEstimate === traced.wallClockEstimate &&
    real.attempts === traced.attempts &&
    JSON.stringify(Object.entries(real.trialsByStage)) === JSON.stringify(traced.trialsByStage);
  if (!same) throw new Error(`the traced simulate() copy drifted from test/simulate.ts on ${label}`);
}

function runNumbers(run: TracedRun) {
  return {
    totalTrials: run.totalTrials,
    trialsByStage: run.trialsByStage,
    keystrokes: run.keystrokes,
    attempts: run.attempts,
    wallClockEstimate: run.wallClockEstimate,
    traceHash: run.traceHash,
  };
}

// The "Current engine" section of `npm run simulate`, exactly as it prints:
// everything before the Phase 0 baseline section.
function captureCurrentEngineReport(): string {
  const out = execFileSync(process.execPath, ['--import', 'tsx', 'test/simulate.report.ts'], {
    cwd: REPO_ROOT,
    encoding: 'utf8',
  });
  const end = out.indexOf('\n=== Phase 0 baseline');
  if (!out.startsWith('\n=== Current engine') || end < 0) {
    throw new Error('test/simulate.report.ts output changed shape; update captureCurrentEngineReport()');
  }
  return out.slice(0, end);
}

interface ExtraRunSpec {
  label: string;
  spec: string;
  deck: string;
  config: SessionConfig;
  learner: string;
  minWordsToChunk: number;
}

// Seeded twins of the simulate() calls in test/simulate.spec.ts,
// test/coldStartEstimate.consistency.spec.ts and c8b.spec.ts.
function extraRunSpecs(): ExtraRunSpec[] {
  const specs: ExtraRunSpec[] = [];
  const cumulative = (encodeReps: number, extra: Partial<SessionConfig> = {}): SessionConfig => ({
    encodeReps,
    chunkDifficulty: 35,
    stemTolerance: true,
    ladderMode: 'cumulative',
    ...extra,
  });
  for (const deck of ['shortDeck', 'mediumDeck', 'proseDeck', 'mixedDeck']) {
    for (const encodeReps of [1, 3, 5]) {
      for (const minWordsToChunk of [3, 8]) {
        specs.push({
          label: `consistency:${deck}:reps${encodeReps}:min${minWordsToChunk}`,
          spec: 'coldStartEstimate.consistency.spec.ts',
          deck,
          config: cumulative(encodeReps),
          learner: 'perfect',
          minWordsToChunk,
        });
      }
    }
    specs.push({
      label: `consistency-inOrder:${deck}`,
      spec: 'coldStartEstimate.consistency.spec.ts',
      deck,
      config: cumulative(3, { cycleOrder: 'inOrder' }),
      learner: 'perfect',
      minWordsToChunk: 8,
    });
  }
  for (const deck of ['shortDeck', 'proseDeck']) {
    for (const [learner] of SIM_LEARNERS) {
      specs.push({ label: `simulate:${deck}:${learner}`, spec: 'simulate.spec.ts', deck, config: SIM_CONFIG, learner, minWordsToChunk: 8 });
    }
  }
  for (const ladderMode of ['exhaustive', 'cumulative'] as const) {
    specs.push({
      label: `simulate-ladder:${ladderMode}`,
      spec: 'simulate.spec.ts',
      deck: 'proseDeck',
      config: { encodeReps: 3, chunkDifficulty: 25, stemTolerance: true, ladderMode },
      learner: 'perfect',
      minWordsToChunk: 8,
    });
  }
  specs.push({
    label: 'c8b:twoChunk',
    spec: 'c8b.spec.ts',
    deck: 'twoChunkDeck',
    config: { encodeReps: 2, chunkDifficulty: TWO_CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
    learner: 'perfect',
    minWordsToChunk: 8,
  });
  return specs;
}

const NAMED_DECKS: Record<string, DeckItem[]> = {
  shortDeck,
  proseDeck,
  mediumDeck,
  mixedDeck: MIXED_DECK,
  twoChunkDeck: [{ front: 'Q', back: TWO_CHUNK_BACK }],
};
const NAMED_LEARNERS: Record<string, LearnerModel> = Object.fromEntries(SIM_LEARNERS);

function exportSessionSim(): void {
  const runs: unknown[] = [];
  const seed0: unknown[] = [];
  for (const [deckName, deck] of SIM_DECKS) {
    for (const [learnerName, learner] of SIM_LEARNERS) {
      const config = `${deckName}:${learnerName}`;
      const baseSeed = hashSeed(`current:${config}`);
      for (let i = 0; i < RUNS_PER_CONFIG; i++) {
        // Can pass 2**32; mulberry32 takes it `>>> 0`, and so must Python.
        const seed = baseSeed + i;
        const run = withSeededRandom(seed, () => simulateTraced(deck, SIM_CONFIG, learner, MIN_WORDS_TO_CHUNK, i === 0 ? 'hash' : 'none'));
        checkRealSimulate(`${config}:${i}`, seed, deck, SIM_CONFIG, learner, MIN_WORDS_TO_CHUNK, run);
        runs.push({ deck: deckName, learner: learnerName, run: i, seed, ...runNumbers(run) });
        if (i === 0) {
          seed0.push({ config, seed, step: 0, stateHash: run.initialStateHash });
          for (const st of run.steps) seed0.push({ config, ...st });
        }
      }
    }
  }

  const extraRuns = extraRunSpecs().map(spec => {
    const seed = hashSeed(`golden:extra:${spec.label}`);
    const deck = NAMED_DECKS[spec.deck];
    const learner = NAMED_LEARNERS[spec.learner];
    const run = withSeededRandom(seed, () => simulateTraced(deck, spec.config, learner, spec.minWordsToChunk));
    checkRealSimulate(spec.label, seed, deck, spec.config, learner, spec.minWordsToChunk, run);
    // The consistency spec's floor. buildItems shuffles, so it gets a seed of
    // its own; the count doesn't depend on the order.
    const predictedFloor = withSeededRandom(seed + 1, () =>
      computeMinimumTrials(
        buildItems(deck, spec.config.chunkDifficulty, spec.config.ladderMode, undefined, spec.minWordsToChunk),
        spec.config.encodeReps,
        spec.config.ladderMode
      )
    );
    return { ...spec, seed, predictedFloor, ...runNumbers(run) };
  });

  writeGolden('session_sim.json', {
    config: SIM_CONFIG,
    decks: Object.fromEntries(Object.entries(NAMED_DECKS)),
    deckOrder: SIM_DECKS.map(([name]) => name),
    learnerOrder: SIM_LEARNERS.map(([name]) => name),
    runsPerConfig: RUNS_PER_CONFIG,
    runs,
    extraRuns,
    report: captureCurrentEngineReport(),
  });
  writeGolden('session_seed0.json', { steps: seed0 });
}

// --full <deck>:<learner>[:<run>]: every step's full state for one seeded run.
function exportFullDebug(arg: string): void {
  const [deckName, learnerName, runText] = arg.split(':');
  const deck = SIM_DECKS.find(([name]) => name === deckName)?.[1];
  const learner = NAMED_LEARNERS[learnerName ?? ''];
  const i = runText === undefined ? 0 : Number(runText);
  if (!deck || !learner || !Number.isInteger(i) || i < 0 || i >= RUNS_PER_CONFIG) {
    throw new Error(`--full takes <deck>:<learner>[:<run>], e.g. proseDeck:realistic:7 (got '${arg}')`);
  }
  const seed = hashSeed(`current:${deckName}:${learnerName}`) + i;
  const run = withSeededRandom(seed, () => simulateTraced(deck, SIM_CONFIG, learner, MIN_WORDS_TO_CHUNK, 'full'));
  const lines = [compact({ step: 0, seed, stateHash: run.initialStateHash, state: run.initialState }), ...run.steps.map(compact)];
  mkdirSync(DEBUG_DIR, { recursive: true });
  const file = join(DEBUG_DIR, `${deckName}.${learnerName}.${i}.ts.jsonl`);
  writeFileSync(file, lines.join('\n') + '\n', 'utf8');
  console.log(`wrote ${file}`);
}
// ---------------------------------------------------------------------------
// session_scenarios.json: scripted sessions with the full state after every step
//
// A scenario builds a session (inside withSeededRandom(seed), which also
// covers every later step), then runs a list of actions. Scripts are written
// below with helpers that loop until a condition holds; the golden records
// the expanded action list, so Python replays it action by action
// (tests/engine/session_runner.py). The actions, mirroring SessionView and
// App.tsx:
//
//   correct            type the current trial's target and Check
//   wrong:<text>       type <text> and Check (near:<text> and type:<text> are
//                      the same action; the exporter fails unless wrong: grades
//                      'wrong' and near: grades 'near')
//   reveal[:<text>]    Show answer, then type <text> (default: the target)
//   override           "Count as correct": re-apply the trial answered wrong,
//                      with override: true, to the state from BEFORE that
//                      answer (SessionView's preWrongStateRef)
//   override-now       applyAnswer(state, target, { override: true }) on the
//                      current state (the c2 spec's direct call, and the
//                      pre-2026-09-26 post-miss route)
//   edit:<json>        editCurrentItem; like SessionView, a pending override's
//                      pre-answer state gets the same edit (dropped on restart)
//   next               Continue: applyNext in 'cycle'/'final', "Next batch"
//                      (advanceToNextBatch) in 'batch-done', nothing in 'encode'
//   save-resume[:<json>]  SessionView's save, a JSON round trip, then
//                      App.handleResumeSession + SessionView's initSession.
//                      <json> edits the saved object first, to make old save
//                      shapes: {drop, dropItemKeys, dropStatsKeys, set,
//                      patchItems}
//   probe              buildHistoryEntry, rankHardestCards, cardTroubleScore
//
// Every step records the state, selectTrial(state) and `metrics` (accuracy,
// batch summary, progress, cold-start multiplier and remaining range).

// App.tsx's settings defaults (src/utils/settings.ts), used when a save lacks
// the field.
const APP_DEFAULTS = { chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' as LadderMode };
const FIXED_SAVE_TIMESTAMP = Date.UTC(2026, 9, 1, 11, 0, 0, 0);
const FIXED_START_TIME = Date.UTC(2026, 9, 1, 9, 30, 15, 250);
const FIXED_FINISHED_AT = Date.UTC(2026, 9, 1, 10, 5, 42, 7);
const ZERO_STATS: SessionStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function currentBatchItems(state: SessionState): DrillItem[] {
  return partitionIntoBatches(state.items, state.config.batchSize ?? state.items.length)[state.batchIndex] ?? [];
}

// `full` adds the batch summary, the remaining range and per-item progress.
// The golden carries those only at init, probes, phase or batch changes and
// every 10th step, to keep the file small.
function metricsOf(state: SessionState, full: boolean) {
  const multiplier = computeCumulativeColdStartMultiplier(state);
  const light = {
    accuracyPercent: computeAccuracyPercent(state.stats),
    progress: computeSessionProgress(state.items, state.config.encodeReps, currentBatchItems(state)),
    multiplier,
  };
  if (!full) return light;
  return {
    ...light,
    batchSummary: computeBatchSummary(state),
    itemProgress: state.items.map(i => computeItemProgress(i, state.config.encodeReps)),
    remaining: computeRemainingColdStartRange(state, multiplier ?? 1.8),
  };
}

// SessionView's persistState, with fixed deckName/timestamp.
function persistShape(state: SessionState): SavedSessionState {
  return {
    deckName: 'golden',
    phase: state.phase,
    queue: state.queue,
    stats: state.stats,
    items: state.items,
    encodeReps: state.config.encodeReps,
    chunkDifficulty: state.config.chunkDifficulty,
    stemTolerance: state.config.stemTolerance,
    ladderMode: state.config.ladderMode,
    strictPunctuation: state.config.strictPunctuation,
    cycleOrder: state.config.cycleOrder,
    batchIndex: state.batchIndex,
    batchSize: state.config.batchSize,
    batchStartStats: state.batchStartStats,
    finalCheckStartAttempts: state.finalCheckStartAttempts,
    currentId: state.currentId,
    sourceDeckEditable: true,
    timestamp: FIXED_SAVE_TIMESTAMP,
  };
}

interface SaveEdits {
  drop?: string[];
  dropItemKeys?: string[];
  dropStatsKeys?: string[];
  set?: Record<string, unknown>;
  patchItems?: ({ id: number } & Record<string, unknown>)[];
}

function applySaveEdits(saved: Record<string, any>, e: SaveEdits): void {
  for (const k of e.drop ?? []) delete saved[k];
  for (const it of saved.items) for (const k of e.dropItemKeys ?? []) delete it[k];
  for (const k of e.dropStatsKeys ?? []) {
    delete saved.stats[k];
    if (saved.batchStartStats) delete saved.batchStartStats[k];
  }
  Object.assign(saved, e.set ?? {});
  for (const patch of e.patchItems ?? []) Object.assign(saved.items.find((i: DrillItem) => i.id === patch.id), patch);
}

// App.handleResumeSession, then SessionView's initial initSession.
function resumeSaved(saved: SavedSessionState): SessionState {
  const mode = saved.ladderMode ?? APP_DEFAULTS.ladderMode;
  const items = saved.items.map(it => normalizeItem(it, mode));
  const { batchIndex, batchSize } = resolveBatchConfig(saved, items);
  const stats = { ...emptyStats(), ...saved.stats };
  return initSession({
    items,
    phase: saved.phase,
    queue: saved.queue || [],
    stats,
    currentId: saved.currentId ?? SESSION_COMPLETE_ID,
    batchIndex,
    batchStartStats: { ...emptyStats(), ...(saved.batchStartStats ?? saved.stats) },
    finalCheckStartAttempts: saved.finalCheckStartAttempts,
    config: {
      encodeReps: saved.encodeReps || 3,
      chunkDifficulty: saved.chunkDifficulty ?? APP_DEFAULTS.chunkDifficulty,
      stemTolerance: saved.stemTolerance ?? APP_DEFAULTS.stemTolerance,
      ladderMode: saved.ladderMode ?? APP_DEFAULTS.ladderMode,
      strictPunctuation: saved.strictPunctuation ?? false,
      batchSize,
      cycleOrder: saved.cycleOrder ?? 'shuffled',
    },
  });
}

type Pred = (s: SessionState, d: Driver) => boolean;

class Driver {
  state: SessionState;
  // SessionView's preWrongStateRef, and whether a Continue is pending.
  private preWrong: SessionState | null = null;
  needsNext = false;
  readonly records: Record<string, unknown>[] = [];

  constructor(readonly name: string, initial: SessionState) {
    this.state = initial;
    this.record('init', {});
  }

  private lastPhase: string | null = null;
  private lastBatchIndex = -1;

  private record(action: string, extra: Record<string, unknown>): void {
    const step = this.records.length;
    assertIntegerJson(this.state, `${this.name} step ${step}`);
    const fullMetrics =
      action === 'init' ||
      action === 'probe' ||
      step % 10 === 0 ||
      this.state.phase !== this.lastPhase ||
      this.state.batchIndex !== this.lastBatchIndex;
    this.lastPhase = this.state.phase;
    this.lastBatchIndex = this.state.batchIndex;
    this.records.push(
      snapshot({
        scenario: this.name,
        step,
        action,
        ...extra,
        state: this.state,
        trial: selectTrial(this.state),
        metrics: metricsOf(this.state, fullMetrics),
      })
    );
  }

  item(id: number): DrillItem {
    return this.state.items.find(i => i.id === id)!;
  }

  get cur(): DrillItem {
    return this.item(this.state.currentId);
  }

  trial(): Trial {
    const t = selectTrial(this.state);
    if (!t) throw new Error(`${this.name}: no trial at step ${this.records.length}`);
    return t;
  }

  done(): boolean {
    return this.state.phase !== 'batch-done' && this.state.currentId === SESSION_COMPLETE_ID;
  }

  do(action: string): this {
    const colon = action.indexOf(':');
    const verb = colon < 0 ? action : action.slice(0, colon);
    const arg = colon < 0 ? undefined : action.slice(colon + 1);
    switch (verb) {
      case 'correct':
        return this.answer(action, this.trial().target, false);
      case 'wrong':
      case 'near':
      case 'type':
        this.answer(action, arg ?? '', false);
        if (verb !== 'type' && this.lastVerdict !== verb) {
          throw new Error(`${this.name} step ${this.records.length - 1}: '${action}' graded ${this.lastVerdict}`);
        }
        return this;
      case 'reveal':
        return this.answer(action, arg ?? this.trial().target, true);
      case 'override': {
        const pre = this.preWrong;
        if (!pre) throw new Error(`${this.name}: override with no pending wrong answer`);
        const r = applyAnswer(pre, selectTrial(pre)!.target, { revealed: false, override: true });
        return this.commit(action, r, null);
      }
      case 'override-now': {
        const r = applyAnswer(this.state, this.trial().target, { revealed: false, override: true });
        return this.commit(action, r, null);
      }
      case 'edit': {
        const edit = JSON.parse(arg!);
        const before = this.state;
        const { state, restarted } = editCurrentItem(before, edit);
        this.state = state;
        if (this.preWrong) this.preWrong = restarted ? null : editCurrentItem(this.preWrong, edit).state;
        if (restarted) this.needsNext = false;
        this.record(action, { edit: { restarted, unchanged: state === before } });
        return this;
      }
      case 'next':
        if (this.state.phase === 'batch-done') this.state = advanceToNextBatch(this.state);
        else if (this.state.phase === 'cycle' || this.state.phase === 'final') this.state = applyNext(this.state);
        this.preWrong = null;
        this.needsNext = false;
        this.record(action, {});
        return this;
      case 'save-resume': {
        const saved = snapshot(persistShape(this.state)) as SavedSessionState;
        applySaveEdits(saved as unknown as Record<string, any>, arg ? JSON.parse(arg) : {});
        this.state = resumeSaved(snapshot(saved));
        this.preWrong = null;
        this.needsNext = false;
        this.record(action, { saved });
        return this;
      }
      case 'probe':
        this.record(action, {
          probe: {
            history: buildHistoryEntry(this.state, new Date(FIXED_FINISHED_AT)),
            hardest: rankHardestCards(this.state.items).map(i => i.id),
            hardestTop2: rankHardestCards(this.state.items, 2).map(i => i.id),
            trouble: this.state.items.map(cardTroubleScore),
          },
        });
        return this;
      default:
        throw new Error(`${this.name}: unknown action ${action}`);
    }
  }

  private answer(action: string, typed: string, revealed: boolean): this {
    const pre = this.state;
    const r = applyAnswer(pre, typed, { revealed });
    return this.commit(action, r, r.verdict === 'wrong' ? pre : null);
  }

  lastVerdict: Verdict | null = null;

  private commit(action: string, r: ReturnType<typeof applyAnswer>, preWrong: SessionState | null): this {
    this.lastVerdict = r.verdict;
    this.state = r.state;
    this.preWrong = preWrong;
    this.needsNext = r.advance === 'manual';
    this.record(action, { result: { verdict: r.verdict, feedback: r.feedback, advance: r.advance } });
    return this;
  }

  // What a learner who always answers correctly does next.
  auto(): this {
    return this.do(this.state.phase === 'batch-done' || this.needsNext ? 'next' : 'correct');
  }

  until(pred: Pred, limit = 600): this {
    for (let n = 0; !pred(this.state, this); n++) {
      if (n >= limit || this.done()) throw new Error(`${this.name}: condition never reached`);
      this.auto();
    }
    return this;
  }

  steps(n: number): this {
    for (let k = 0; k < n && !this.done(); k++) this.auto();
    return this;
  }

  // Answers the current trial, then Continue when the answer needs one.
  answerAndContinue(action: string): this {
    this.do(action);
    if (this.needsNext) this.do('next');
    return this;
  }

  finish(): this {
    return this.until((_s, d) => d.done());
  }
}

interface ScenarioSetup {
  deck: DeckItem[];
  config: SessionConfig;
  // buildItems arguments; chunkPercent/ladderMode/batchSize default to the config's.
  chunkPercent?: number;
  ladderMode?: LadderMode;
  batchSize?: number;
  minWordsToChunk?: number;
  shuffleWithinBatch?: boolean;
  // 'zero' = the specs' { attempts, misses, nearMisses, overrides }, 'empty' =
  // emptyStats(), 'app' = App.handleStartSession's (emptyStats + startTime).
  stats?: 'zero' | 'empty' | 'app';
  // cycleGap/cycleOrder specs: every item 'ready', session starts in 'cycle'.
  startInCycle?: boolean;
}

interface Scenario {
  name: string;
  covers: string[];
  setup: ScenarioSetup;
  script: (d: Driver) => void;
}

const EXPOSURES: (ExposureLevel | number)[] = ['fresh', 'once', 'familiar', 1, 2.37];

function runScenario(sc: Scenario): { header: unknown; steps: Record<string, unknown>[] } {
  const { setup } = sc;
  const build = {
    chunkPercent: setup.chunkPercent ?? setup.config.chunkDifficulty,
    ladderMode: setup.ladderMode ?? setup.config.ladderMode,
    batchSize: setup.batchSize ?? setup.config.batchSize ?? null,
    minWordsToChunk: setup.minWordsToChunk ?? MIN_WORDS_TO_CHUNK,
    shuffleWithinBatch: setup.shuffleWithinBatch ?? true,
    allReady: setup.startInCycle ?? false,
  };
  const statsKind = setup.stats ?? 'zero';
  const stats: SessionStats =
    statsKind === 'zero' ? { ...ZERO_STATS } : statsKind === 'empty' ? emptyStats() : { ...emptyStats(), startTime: FIXED_START_TIME };
  const batchStartStats: SessionStats = statsKind === 'zero' ? { ...ZERO_STATS } : emptyStats();
  const phase = build.allReady ? ('cycle' as const) : ('encode' as const);

  // computeColdStartEstimate shuffles (buildItems), so it runs on a seed of
  // its own, outside the scenario's stream. Its result doesn't depend on order.
  const estimates = withSeededRandom(hashSeed(`golden:estimate:${sc.name}`), () => ({
    deckShape: pickColdStartDeckShape(setup.deck),
    byExposure: EXPOSURES.map(m => {
      const e = computeColdStartEstimate(setup.deck, setup.config.encodeReps, setup.config.chunkDifficulty, setup.config.ladderMode, m);
      return { multiplier: m, estimate: e, range: formatColdStartRange(e.floorSeconds, e.ceilingSeconds) };
    }),
  }));

  const seed = hashSeed(`golden:scenario:${sc.name}`);
  const steps = withSeededRandom(seed, () => {
    let items = buildItems(setup.deck, build.chunkPercent, build.ladderMode, build.batchSize ?? undefined, build.minWordsToChunk, build.shuffleWithinBatch);
    if (build.allReady) items = items.map(it => ({ ...it, status: 'ready' as const }));
    const d = new Driver(
      sc.name,
      initSession({
        items,
        phase,
        queue: [],
        stats,
        currentId: SESSION_COMPLETE_ID,
        batchIndex: 0,
        batchStartStats,
        config: setup.config,
      })
    );
    sc.script(d);
    return d.records;
  });

  const header = {
    name: sc.name,
    covers: sc.covers,
    seed,
    deck: setup.deck,
    build,
    initial: { phase, stats, batchStartStats, config: setup.config },
    estimates,
    stepCount: steps.length,
  };
  return { header, steps };
}
// --- Scenario decks (copies of the specs' own fixtures) ---

// overrideCredit.spec.ts / history.spec.ts
const OC_DECK: DeckItem[] = [
  { front: 'Tachy', back: 'fast heart rate' },
  { front: 'Hyper', back: 'blood pressure that stays above the normal range for a long time' },
  { front: 'itis', back: 'inflammation' },
];
// telemetry.spec.ts
const TELEMETRY_DECK: DeckItem[] = OC_DECK.slice(0, 2);
// editCurrentItem.spec.ts
const EDIT_DECK: DeckItem[] = [
  { front: 'Tachycardia', back: 'fast heart rate' },
  { front: 'Inner ear disorder', back: 'Menieres disease' },
  { front: 'Before surgery', back: 'pre op' },
  { front: 'Describe where the trees grow', back: FOUR_CHUNK_BACK },
];
const [TACHY, MENIERES, PRE_OP, TREES] = [0, 1, 2, 3];
// resumePosition.spec.ts
const RESUME_DECK: DeckItem[] = [
  { front: 'short A', back: 'alpha one' },
  { front: 'short B', back: 'beta two' },
  { front: 'long', back: FOUR_CHUNK_BACK },
  { front: 'short C', back: 'gamma three' },
];
// chainContiguity.spec.ts
const LONG_DECK: DeckItem[] = [
  { front: 'Short A', back: 'answer alpha' },
  { front: 'Trees', back: FOUR_CHUNK_BACK },
  { front: 'Short B', back: 'answer beta' },
];
const C2_PROSE = 'large green trees grow slowly near the quiet flowing rivers';
const C2_BUS = 'wait for the bus at the station today please';
const STOMACH = 'inflammation of the stomach';
const shortDeckOf = (n: number): DeckItem[] => Array.from({ length: n }, (_, i) => ({ front: `Q${i}`, back: `answer${i}` }));
const chunkedDeckOf = (n: number): DeckItem[] =>
  Array.from({ length: n }, (_, i) => ({
    front: `Q${i}`,
    back: `alpha${i} beta${i} gamma${i} delta${i} epsilon${i} zeta${i} eta${i} theta${i} iota${i}`,
  }));
const one = (back: string, front = 'Q'): DeckItem[] => [{ front, back }];

const cfg = (encodeReps: number, chunkDifficulty: number, extra: Partial<SessionConfig> = {}): SessionConfig => ({
  encodeReps,
  chunkDifficulty,
  stemTolerance: true,
  ladderMode: 'cumulative',
  ...extra,
});

const enc = (s: SessionState) => s.phase === 'encode';
const on = (id: number) => (s: SessionState) => s.currentId === id;
const itemIn = (s: SessionState, id: number) => s.items.find(i => i.id === id)!;
const curIn = (s: SessionState) => s.items.find(i => i.id === s.currentId);
const edit = (front: string, back: string, extra?: string) =>
  `edit:${JSON.stringify(extra === undefined ? { front, back } : { front, back, extra })}`;
const saveResume = (e?: SaveEdits) => (e ? `save-resume:${JSON.stringify(e)}` : 'save-resume');
const TELEMETRY_KEYS = ['attempts', 'misses', 'reveals', 'nearMisses', 'hardSpans'];

// Plays a perfect learner, and the first time each named condition holds on a
// fresh trial, answers wrong and then "Count as correct".
function overrideAtEach(d: Driver, stops: [string, Pred][], wrong = 'zzz wrong'): void {
  const used = new Set<string>();
  while (!d.done()) {
    const hit = d.needsNext || d.state.phase === 'batch-done' ? undefined : stops.find(([n, p]) => !used.has(n) && p(d.state, d));
    if (hit) {
      used.add(hit[0]);
      d.do(`wrong:${wrong}`).do('override');
      if (d.needsNext) d.do('next');
    } else {
      d.auto();
    }
  }
  if (used.size !== stops.length) throw new Error(`${d.name}: not every override stop was reached`);
}

const SCENARIOS: Scenario[] = [
  // ----- 1. A reveal at every stage -----
  {
    name: 'reveal-at-every-stage',
    covers: ['required: reveal at chunk presentation, chunk blind, combine, remediate (depth 1 and 2), full, cycle, final'],
    setup: { deck: OC_DECK, config: cfg(2, 35), shuffleWithinBatch: false, stats: 'app' },
    script: d => {
      d.do('reveal'); // full stage, attempt 0 (Tachy)
      d.until(on(1)); // the long card's first chunk presentation
      d.do('reveal').do('reveal'); // presentation (stays 'presented'), then the blind attempt
      d.until(s => s.currentId === 1 && itemIn(s, 1).stage === 'combine');
      d.do('reveal'); // combine window 1-2
      d.do('wrong:blood pressure zzz').do('next'); // 2-chunk window: straight to remediation
      d.do('reveal'); // remediate, depth 1
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next'); // 2nd miss splits the piece
      d.do('reveal'); // remediate, depth 2
      d.until(s => s.phase === 'cycle');
      d.do('reveal').do('next');
      d.until(s => s.phase === 'final');
      d.do('reveal').do('next');
      d.finish().do('probe');
    },
  },
  {
    name: 'reveal-inorder-cycle-and-final',
    covers: ['cycleOrder.spec.ts: a revealed answer also waits for the next pass (driven session)'],
    setup: { deck: shortDeckOf(3), config: cfg(1, 35, { cycleOrder: 'inOrder' }), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.phase === 'cycle');
      d.do('reveal:').do('next');
      d.until(s => s.phase === 'final');
      d.do('reveal:nope').do('next').do('wrong:nope').do('next');
      d.finish().do('probe');
    },
  },

  // ----- 2. Override after a wrong answer at every stage -----
  {
    name: 'override-at-every-stage',
    covers: [
      'overrideCredit.spec.ts: full-stage card, 2nd rep',
      'overrideCredit.spec.ts: chunk, blind attempt',
      'overrideCredit.spec.ts: first 2-part combination (a miss would isolate)',
      'overrideCredit.spec.ts: whole-answer window, 2nd rep',
      'overrideCredit.spec.ts: review, the answer that would master',
      'overrideCredit.spec.ts: final check',
      'required: override stats count no attempt and +1 override; the card attempts +1',
    ],
    setup: { deck: OC_DECK, config: cfg(3, 35, { cycleOrder: 'inOrder' }), shuffleWithinBatch: false },
    script: d => {
      const LONG = 1;
      overrideAtEach(d, [
        ['full 2nd rep', s => enc(s) && s.currentId === 0 && itemIn(s, 0).encodeStreak === 1],
        ['chunk blind', s => enc(s) && s.currentId === LONG && itemIn(s, LONG).stage === 'chunks' && itemIn(s, LONG).chunkStreak === 1],
        ['first combination', s => enc(s) && s.currentId === LONG && itemIn(s, LONG).stage === 'combine' && itemIn(s, LONG).combineSeqIdx === 0],
        [
          'whole-answer 2nd rep',
          s => enc(s) && s.currentId === LONG && itemIn(s, LONG).stage === 'combine' && itemIn(s, LONG).combineSeqIdx === 1 && itemIn(s, LONG).combineStreak === 1,
        ],
        ['cycle mastering answer', s => s.phase === 'cycle' && curIn(s)!.cycleStreak === 1],
        ['final check', s => s.phase === 'final'],
      ]);
      d.do('probe');
    },
  },
  {
    name: 'override-remediate-and-cycle-shuffled',
    covers: ['required: override in remediate (retry and split) and in a shuffled cycle'],
    setup: { deck: one(FOUR_CHUNK_BACK, 'Trees'), config: cfg(2, CHUNK_DIFFICULTY), stats: 'empty' },
    script: d => {
      d.until(s => curIn(s)!.stage === 'combine');
      d.do('wrong:large green zzz zzz').do('next'); // remediate 'trees grow'
      d.do('wrong:zzz').do('override'); // remediate retry
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('override'); // the would-be split
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next'); // a real split
      d.do('wrong:zzz').do('override');
      d.until(s => s.phase === 'cycle');
      d.do('wrong:zzz').do('override').do('next');
      d.finish().do('probe');
    },
  },
  {
    name: 'override-now-post-miss-chunk',
    covers: ['overrideCredit.spec.ts: the old post-miss route (override on the post-miss state); session.ts !isOverride guard'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY) },
    script: d => {
      d.do('correct').do('wrong:nonsense').do('next'); // blind miss: chunkStreak back to 0
      d.do('override-now'); // counts as a real answer, not a presentation
      d.do('override-now'); // the next chunk's presentation, overridden
      d.steps(3);
    },
  },
  {
    name: 'c2-override-direct',
    covers: [
      'c2.spec.ts: override does not double-count the attempt, decrements nothing (miss was never committed), and increments overrides',
    ],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, 35) },
    script: d => {
      d.do('correct'); // presentation
      d.do('wrong:nonsense answer').do('override');
    },
  },
  {
    name: 'c2-override-final-rep',
    covers: ['c2.spec.ts: override on the final rep of a stage-unit advances the item exactly like a genuine correct answer'],
    setup: { deck: one('run fast today'), config: cfg(1, 100) },
    script: d => {
      d.do('override-now');
    },
  },

  // ----- 3. Near verdicts and strict punctuation -----
  {
    name: 'c2-near-stopword-full',
    covers: [
      'c2.spec.ts: dropping a stopword from an otherwise-exact long answer counts as near and advances the streak',
      'required: near in encode (full), cycle and final',
    ],
    setup: { deck: one(C2_BUS), config: cfg(2, 100) },
    script: d => {
      d.do('near:wait for bus at the station today please');
      d.do('correct');
      d.do('near:wait for bus at the station today please').do('next');
      d.do('correct').do('next');
      d.do('near:wait for the bus at station today please').do('next');
      d.finish().do('probe');
    },
  },
  {
    name: 'c2-near-stem-on',
    covers: ['c2.spec.ts: a plural-only difference on a long answer counts as near when stemTolerance is on'],
    setup: { deck: one(C2_PROSE), config: cfg(1, 100) },
    script: d => {
      d.do('near:large green trees grow slowly near the quiet flowing river');
    },
  },
  {
    name: 'c2-near-stem-off',
    covers: ['c2.spec.ts: the same plural difference counts as wrong when stemTolerance is off'],
    setup: { deck: one(C2_PROSE), config: cfg(1, 100, { stemTolerance: false }) },
    script: d => {
      d.do('wrong:large green trees grow slowly near the quiet flowing river');
    },
  },
  {
    name: 'c2-near-cycle',
    covers: ['c2.spec.ts: a near-miss in the cycle phase advances cycleStreak and does not increment misses'],
    setup: { deck: one(C2_BUS), config: cfg(1, 100) },
    script: d => {
      d.do('correct');
      d.do('near:wait for bus at the station today please');
    },
  },
  {
    name: 'near-chunked-stages',
    covers: ['required: near in chunks, combine and remediate, with stemTolerance on'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY), stats: 'app' },
    script: d => {
      d.do('correct').do('near:mitochondria produces most of'); // stopword dropped on a chunk
      d.do('correct').do('correct');
      d.do('near:mitochondria produces most of the cells energy supply'); // combine
      d.do('wrong:the mitochondria produces zzz').do('next'); // 2-chunk window: remediate
      d.do('near:mitochondria produces most of'); // remediate
      d.do('near:the mitochondria produces most of'.replace('the ', 'the the '));
      d.finish().do('probe');
    },
  },
  {
    name: 'near-stem-off-chunked',
    covers: ['required: stemTolerance off on chunk, combine, cycle and final answers'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(1, TWO_CHUNK_DIFFICULTY, { stemTolerance: false }) },
    script: d => {
      d.do('correct').do('wrong:the mitochondria produce most of').do('next');
      d.do('correct').do('near:mitochondria produces most of');
      d.until(s => s.phase === 'cycle');
      d.do('wrong:the mitochondria produces most of the cell energy supply').do('next');
      d.until(s => s.phase === 'final');
      d.do('wrong:the mitochondria produces most of the cell energy supply').do('next');
      d.finish();
    },
  },
  {
    name: 'strict-stopword-wrong',
    covers: ['strictPunctuation.spec.ts: strictPunctuation: true grades a dropped-stopword difference wrong (near-miss tier disabled)'],
    setup: { deck: one(STOMACH), config: cfg(1, 100, { strictPunctuation: true }) },
    script: d => {
      d.do('wrong:inflammation of stomach');
    },
  },
  {
    name: 'strict-off-near',
    covers: ['strictPunctuation.spec.ts: strictPunctuation: false grades the same difference near (stopword forgiveness applies)'],
    setup: { deck: one(STOMACH), config: cfg(1, 100, { strictPunctuation: false }) },
    script: d => {
      d.do('near:inflammation of stomach');
    },
  },
  {
    name: 'strict-undefined-near',
    covers: ['strictPunctuation.spec.ts: an old config with strictPunctuation undefined (pre-Phase-2 session) behaves like false'],
    setup: { deck: one(STOMACH), config: cfg(1, 100) },
    script: d => {
      d.do('near:inflammation of stomach');
    },
  },
  {
    name: 'strict-punctuation-deck',
    covers: ['required: a strict-punctuation deck through every phase (punctuation misses, culprits, remediation split)'],
    setup: {
      deck: [
        { front: 'Before surgery', back: 'pre-op' },
        { front: 'Ions', back: 'Na+ and K+' },
        { front: 'pH', back: 'Normal arterial pH is 7.35-7.45; below 7.35 is acidosis, (above) is alkalosis.' },
      ],
      config: cfg(1, 35, { strictPunctuation: true }),
      shuffleWithinBatch: false,
    },
    script: d => {
      d.do('wrong:pre op').do('next').do('correct');
      d.do('wrong:Na and K').do('next').do('correct');
      d.until(s => curIn(s)!.stage === 'combine');
      d.do('wrong:Normal arterial pH is 7.35-7.45 below 7.35 is acidosis').do('next');
      d.do('wrong:Normal arterial pH is 7.35 7.45; below').do('next').do('wrong:Normal arterial').do('next');
      d.until(s => s.phase === 'cycle');
      d.do('wrong:pre-op.').do('next');
      d.finish().do('probe');
    },
  },
];

SCENARIOS.push(
  // ----- 4. Deep remediation -----
  {
    name: 'remediation-deep',
    covers: [
      'required: a miss on a window of <= 2 chunks remediates at once; > 2 chunks on the 2nd miss; recursive halving after 2 further misses',
      'telemetry.spec.ts: hardSpans keep the narrowest spans',
    ],
    setup: { deck: one(FOUR_CHUNK_BACK, 'Trees'), config: cfg(2, CHUNK_DIFFICULTY), stats: 'app' },
    script: d => {
      const combineAt = (idx: number) => (s: SessionState) => curIn(s)!.stage === 'combine' && curIn(s)!.combineSeqIdx === idx;
      d.until(combineAt(0));
      d.do('wrong:large green zzz grow').do('next'); // window 1-2: remediate on the first miss
      d.until(combineAt(1));
      d.do('wrong:zzz green trees grow zzz near').do('next'); // window 1-3: retry
      d.do('wrong:zzz green trees grow zzz near').do('next'); // 2nd miss: two culprit chunks
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next'); // split 'large green'
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next'); // one word: never split
      d.until(combineAt(2));
      d.do('wrong:large green trees grow slowly near zzz zzz zzz').do('next');
      d.do('wrong:large green trees grow slowly near zzz zzz zzz').do('next'); // culprit 'the quiet river'
      d.do('wrong:the zzz zzz').do('next').do('wrong:the zzz zzz').do('next'); // split -> 'the quiet'
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next'); // split again -> depth 3
      d.do('wrong:the quiet').do('next'); // right half wrong at depth 3
      d.until(s => s.phase === 'cycle');
      d.finish().do('probe');
    },
  },
  {
    name: 'remediation-exhaustive-b1',
    covers: [
      'characterization.engine.spec.ts: flags only the chunks that actually mismatch, not the whole window (B1 fixed)',
      'c1.spec.ts: a genuinely wrong combine answer on the final window still enters remediate and B1 attributes correctly',
    ],
    setup: { deck: one(FOUR_CHUNK_BACK, 'Q3'), config: cfg(1, CHUNK_DIFFICULTY, { ladderMode: 'exhaustive' }) },
    script: d => {
      d.until(s => curIn(s)!.stage === 'combine' && curIn(s)!.combineSeqIdx === 5);
      const dropped = 'large trees grow slowly the quiet river';
      d.do(`wrong:${dropped}`).do('next').do(`wrong:${dropped}`).do('next');
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next');
      d.until(s => s.phase === 'cycle');
    },
  },
  {
    name: 'c1-remediation-cumulative',
    covers: ['c1.spec.ts: a genuinely wrong combine answer on the final window still enters remediate and B1 attributes correctly'],
    setup: { deck: one(FOUR_CHUNK_BACK), config: cfg(1, CHUNK_DIFFICULTY) },
    script: d => {
      d.until(s => curIn(s)!.stage === 'combine' && curIn(s)!.combineSeqIdx === 2);
      const dropped = 'large trees grow slowly near the quiet river';
      d.do(`wrong:${dropped}`).do('next').do(`wrong:${dropped}`).do('next');
      d.until(s => s.phase === 'cycle');
    },
  },

  // ----- 5. editCurrentItem -----
  {
    name: 'edit-prompt-only',
    covers: ['editCurrentItem.spec.ts: a prompt-only edit keeps every progress field'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === TACHY && itemIn(s, TACHY).encodeStreak === 1);
      d.do(edit('Rapid heartbeat', 'fast heart rate')).steps(2);
    },
  },
  {
    name: 'edit-equivalent-answer',
    covers: ["editCurrentItem.spec.ts: an equivalent answer edit on a normal deck keeps progress (Menieres -> M\u{e9}ni\u{e8}re's)"],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === MENIERES && itemIn(s, MENIERES).encodeStreak === 1);
      d.do(edit('Inner ear disorder', "M\u{e9}ni\u{e8}re's disease")).steps(1);
    },
  },
  {
    name: 'edit-same-chunk-count',
    covers: ['editCurrentItem.spec.ts: an equivalent edit with the same chunk count swaps in the new chunk text'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === TREES && itemIn(s, TREES).stage === 'combine');
      d.do(edit('Trees', 'Large green trees grow slowly near the quiet river.')).steps(2);
    },
  },
  {
    name: 'edit-legacy-chunks-prompt-only',
    covers: ['editCurrentItem.spec.ts: a prompt-only edit keeps stored chunks even when chunkText would now produce different ones'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(on(TACHY));
      d.do(saveResume({ patchItems: [{ id: TACHY, chunks: ['fast heart', 'rate'], combineSeq: [{ start: 1, end: 2 }], stage: 'chunks' }] }));
      d.do(edit('Rapid heartbeat', 'fast heart rate'));
    },
  },
  {
    name: 'edit-trims-and-noop-empty',
    covers: ['editCurrentItem.spec.ts: trims both fields', 'editCurrentItem.spec.ts: is a no-op on an empty front or back'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.do(edit('   ', 'fast heart rate')).do(edit('Tachycardia', ''));
      d.do(edit('  Rapid heartbeat  ', ' fast heart rate\n'));
    },
  },
  {
    name: 'edit-pre-op-normal',
    covers: ["editCurrentItem.spec.ts: 'pre op' -> 'pre-op' keeps progress on a normal deck"],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === PRE_OP && itemIn(s, PRE_OP).encodeStreak === 1);
      d.do(edit('Before surgery', 'pre-op'));
    },
  },
  {
    name: 'edit-pre-op-strict',
    covers: ["editCurrentItem.spec.ts: 'pre op' -> 'pre-op' restarts on a strict deck"],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY, { strictPunctuation: true }), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === PRE_OP && itemIn(s, PRE_OP).encodeStreak === 1);
      d.do(edit('Before surgery', 'pre-op')).steps(1);
    },
  },
  {
    name: 'edit-restart-mid-combine',
    covers: ['editCurrentItem.spec.ts: a real answer change mid-combine fully resets the item and nothing else'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === TREES && itemIn(s, TREES).stage === 'combine' && itemIn(s, TREES).combineSeqIdx === 1);
      d.do(edit('Describe where the trees grow', 'tall oak trees grow quickly beside the busy highway')).steps(2);
    },
  },
  {
    name: 'edit-chunk-count-change',
    covers: ['editCurrentItem.spec.ts: an equivalent edit that changes the chunk count restarts'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === TREES && itemIn(s, TREES).stage === 'combine');
      d.do(edit('Describe where the trees grow', 'large green trees grow slowly near the quiet-river')).steps(1);
    },
  },
  {
    name: 'edit-restart-with-extra',
    covers: ['required: answer changed so it restarts in encode, with an Extra note on the rebuilt card'],
    setup: { deck: one(FULL_STAGE_BACK, 'Cats'), config: cfg(2, 35), shuffleWithinBatch: false },
    script: d => {
      d.do('correct').do(edit('Cats', 'dogs bark loudly', '  seen at the park  ')).steps(1);
    },
  },
  {
    name: 'edit-during-remediate',
    covers: ["editCurrentItem.spec.ts: an equivalent edit during 'remediate' restarts", 'required: edit during remediate'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === TREES && itemIn(s, TREES).stage === 'combine');
      d.do('wrong:wrong words entirely');
      d.do(edit('Describe where the trees grow', 'Large green trees grow slowly near the quiet river.')).steps(1);
    },
  },
  ...(['inOrder', 'shuffled'] as const).map(
    (cycleOrder): Scenario => ({
      name: `edit-restart-from-cycle-${cycleOrder}`,
      covers: [
        `editCurrentItem.spec.ts: a real answer change in cycle (${cycleOrder}) goes back to encode and never re-serves mastered cards`,
        'required: restart from cycle (drops to encode)',
      ],
      setup: { deck: EDIT_DECK, config: cfg(1, CHUNK_DIFFICULTY, { cycleOrder }), shuffleWithinBatch: false },
      script: d => {
        d.until((s, dr) => {
          if (s.phase !== 'cycle' || dr.needsNext) return false;
          const others = s.items.filter(i => i.id !== s.currentId);
          return (
            curIn(s)!.status !== 'mastered' &&
            others.some(i => i.status === 'mastered') &&
            others.some(i => i.status === 'ready' && i.cycleStreak === 1)
          );
        });
        d.do(edit(d.cur.front, 'the period of time just before a surgical operation begins'));
        d.until(s => s.phase === 'final');
      },
    })
  ),
  {
    name: 'edit-cycle-prompt-only-and-final-noop',
    covers: [
      'editCurrentItem.spec.ts: does not mutate a deep-frozen input, on either path, in either phase',
      'required: edit during final (no-op)',
    ],
    setup: { deck: EDIT_DECK, config: cfg(1, CHUNK_DIFFICULTY, { cycleOrder: 'inOrder' }), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.phase === 'cycle');
      d.do(edit('edited prompt', d.cur.back));
      d.do('correct').do(edit('edited again', d.cur.back)).do('next');
      d.until(s => s.phase === 'final');
      d.do(edit('x', 'y')).do('correct').do(edit('x', 'y'));
    },
  },
  {
    name: 'edit-noop-batch-done',
    covers: ["editCurrentItem.spec.ts: is a no-op on 'batch-done'"],
    setup: { deck: EDIT_DECK, config: cfg(1, CHUNK_DIFFICULTY, { batchSize: 2 }), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.phase === 'batch-done');
      d.do(edit('x', 'y')).do('next');
    },
  },
  ...[false, true].map(
    (strict): Scenario => ({
      name: `edit-extra-only-strict-${strict}`,
      covers: [`extraField.spec.ts: keeps every progress field and the chunk array (strictPunctuation=${strict})`, 'required: Extra-only edit'],
      setup: {
        deck: one(FOUR_CHUNK_BACK, 'Describe where the trees grow'),
        config: cfg(3, CHUNK_DIFFICULTY, { strictPunctuation: strict }),
        shuffleWithinBatch: false,
      },
      script: d => {
        d.do('type:').do('correct');
        d.do(edit(d.cur.front, d.cur.back, 'a new trouble-spot note'));
      },
    })
  ),
  {
    name: 'edit-extra-never-changes-answer',
    covers: ['extraField.spec.ts: extra never influences whether the answer counted as changed'],
    setup: { deck: one(FOUR_CHUNK_BACK, 'Describe where the trees grow'), config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.do(edit(d.cur.front, d.cur.back, 'note one')).do(edit(d.cur.front, d.cur.back, ''));
      d.do(edit(d.cur.front, d.cur.back, '  padded note  ')).do(edit(d.cur.front, d.cur.back + ' ', '   '));
    },
  },
  {
    name: 'edit-with-pending-override',
    covers: ['SessionView handleSaveEdit: a pending "Count as correct" credits the edited card; a restart drops it'],
    setup: { deck: EDIT_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.do('wrong:slow heart').do(edit('Rapid heartbeat', 'fast heart rate')).do('override');
      d.until(on(MENIERES));
      d.do('wrong:zzz').do(edit('Inner ear disorder', 'vertigo and tinnitus')).do('next');
      d.steps(2);
    },
  },

  // ----- 6. Save and resume -----
  {
    name: 'resume-mid-chunks',
    covers: [
      'resumePosition.spec.ts: resumes a mid-chunks card on the same chunk',
      'resumePosition.spec.ts: currentId survives the storage round-trip (the save shape; localStorage itself is N/A)',
      'required: save and resume mid-encode',
    ],
    setup: { deck: RESUME_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => itemIn(s, 2).stage === 'chunks' && itemIn(s, 2).chunkIndex === 1);
      d.do(saveResume()).steps(2);
    },
  },
  {
    name: 'resume-mid-remediation',
    covers: [
      'resumePosition.spec.ts: resumes a mid-remediation card on the same card and piece',
      'required: old save shape without currentId',
    ],
    setup: { deck: RESUME_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === 2 && itemIn(s, 2).stage === 'combine');
      d.do('wrong:large green zzz').do('next');
      d.until(s => itemIn(s, 2).stage === 'remediate' && itemIn(s, 2).remediateStack[0]?.streak === 1);
      d.do(saveResume());
      d.do(saveResume({ drop: ['currentId'] })).steps(2);
    },
  },
  {
    name: 'resume-fallback-rotation',
    covers: [
      'resumePosition.spec.ts: falls back to rotation when the saved card is no longer unfinished',
      'resumePosition.spec.ts: a fresh start is unchanged: first card in deck order',
    ],
    setup: { deck: RESUME_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => itemIn(s, 2).status === 'ready' && s.phase === 'encode');
      d.do(saveResume({ set: { currentId: 2 } })).steps(1);
    },
  },
  {
    name: 'resume-mid-cycle',
    covers: ['required: save and resume mid-cycle (the in-flight card is not in the saved queue)'],
    setup: { deck: OC_DECK, config: cfg(1, 35), stats: 'app' },
    script: d => {
      d.until(s => s.phase === 'cycle').steps(3);
      d.do('wrong:zzz').do(saveResume());
      d.until((s, dr) => s.phase === 'cycle' && !dr.needsNext && s.queue.length > 0);
      d.do(saveResume({ drop: ['cycleOrder', 'strictPunctuation', 'ladderMode', 'chunkDifficulty', 'stemTolerance'] }));
      d.finish().do('probe');
    },
  },
  {
    name: 'resume-batch-done',
    covers: [
      'c3.spec.ts: round-tripping through a SavedSessionState-shaped save reproduces the interstitial exactly',
      'c3.spec.ts: migrates a pre-C3 save (no batchIndex/batchSize) to batchIndex 0, batchSize items.length',
      'required: save and resume at batch-done',
    ],
    setup: { deck: shortDeckOf(5), config: cfg(1, CHUNK_DIFFICULTY, { batchSize: 3 }), batchSize: 3, stats: 'app' },
    script: d => {
      d.until(s => s.phase === 'batch-done');
      d.do(saveResume()).do(saveResume({ drop: ['currentId'] })).do('next');
      d.steps(2).do(saveResume({ drop: ['batchIndex', 'batchSize', 'batchStartStats'] })).steps(2);
    },
  },
  {
    name: 'resume-mid-final',
    covers: [
      'finalCheck.spec.ts: a mid-Final-check resume preserves finalDone and still tests the card that was in flight at save time',
      'required: save and resume mid-final',
    ],
    setup: { deck: shortDeckOf(5), config: cfg(1, 35) },
    script: d => {
      d.until(s => s.phase === 'final');
      d.answerAndContinue('correct').answerAndContinue('correct');
      d.do(saveResume());
      d.finish().do('probe');
    },
  },
  {
    name: 'resume-old-save-shapes',
    covers: [
      'finalCheck.spec.ts: an old save with no finalDone/finalMisses on any item resumes fine',
      'telemetry.spec.ts: survives normalizeItem (a save/resume round trip)',
      'required: old save shapes (no finalDone, no telemetry, no currentId, no stats.reveals, no finalCheckStartAttempts)',
    ],
    setup: { deck: shortDeckOf(3), config: cfg(1, 35), stats: 'app' },
    script: d => {
      d.do('wrong:zzz').do('next').do(saveResume({ dropItemKeys: TELEMETRY_KEYS, dropStatsKeys: ['reveals'] }));
      d.until(s => s.phase === 'final');
      d.do('reveal').do('next');
      d.do(saveResume({ dropItemKeys: ['finalDone', 'finalMisses'], drop: ['finalCheckStartAttempts'] }));
      d.do(saveResume({ drop: ['currentId'], dropItemKeys: TELEMETRY_KEYS }));
      d.finish().do('probe');
    },
  },
  {
    name: 'resume-pre-c8a-and-empty-remediation',
    covers: [
      'c8a.spec.ts: normalizeItem clamp exercised through a resume (pre-C8a chunkStreak 2)',
      'items.ts normalizeItem: a remediate card with an empty stack restarts its chunks on resume',
    ],
    setup: { deck: RESUME_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === 2 && itemIn(s, 2).stage === 'chunks' && itemIn(s, 2).chunkIndex === 1);
      d.do(saveResume({ patchItems: [{ id: 2, chunkStreak: 2 }] })).steps(1);
      d.do(saveResume({ patchItems: [{ id: 2, stage: 'remediate', remediateStack: [] }] })).steps(2);
    },
  },

  // ----- 7. Config variety -----
  {
    name: 'config-batch-0',
    covers: ['required: batchSize 0 (one whole-deck batch)', 'c3.spec.ts: batchSize 0 (or omitted) is a single whole-deck batch (driven)'],
    setup: { deck: shortDeckOf(4), config: cfg(1, 35, { batchSize: 0 }), batchSize: 0 },
    script: d => {
      d.finish().do('probe');
    },
  },
  {
    name: 'config-batch-3-inorder',
    covers: ['required: batchSize 3, cycleOrder inOrder, misses and reveals in a batched cycle', 'cycleOrder.spec.ts: is scoped to the current batch (driven)'],
    setup: { deck: shortDeckOf(7), config: cfg(1, 35, { batchSize: 3, cycleOrder: 'inOrder' }), shuffleWithinBatch: false, stats: 'app' },
    script: d => {
      d.until(s => s.phase === 'cycle');
      d.do('wrong:zzz').do('next').do('reveal').do('next');
      d.until(s => s.phase === 'batch-done').do('probe').do('next');
      d.until(s => s.phase === 'cycle' && s.batchIndex === 1);
      d.answerAndContinue('wrong:zzz');
      d.finish().do('probe');
    },
  },
  {
    name: 'config-batch-5-shuffled',
    covers: ['required: batchSize 5, shuffled cycle, buildItems shuffling within batches (default)'],
    setup: { deck: shortDeckOf(6), config: cfg(1, 35, { batchSize: 5, cycleOrder: 'shuffled' }), stats: 'app' },
    script: d => {
      d.do('wrong:zzz').do('next').do('reveal');
      d.until(s => s.phase === 'cycle');
      d.answerAndContinue('wrong:zzz').answerAndContinue('correct').answerAndContinue('reveal');
      d.until(s => s.phase === 'batch-done').do('next');
      d.finish().do('probe');
    },
  },
  {
    name: 'config-exhaustive-reps-2',
    covers: ['required: ladderMode exhaustive', 'chainContiguity.spec.ts: exhaustive ladder: short-of-criterion reps on intermediate windows stay on the card too'],
    setup: { deck: one(FOUR_CHUNK_BACK), config: cfg(2, CHUNK_DIFFICULTY, { ladderMode: 'exhaustive' }) },
    script: d => {
      d.until(s => curIn(s)!.stage === 'combine' && curIn(s)!.combineSeqIdx === 2);
      d.do('wrong:large green trees grow slowly zzz').do('next');
      d.finish();
    },
  },
  {
    name: 'config-encode-reps-5',
    covers: ['required: encodeReps 5'],
    setup: { deck: [{ front: 'a', back: 'alpha' }, ...one(TWO_CHUNK_BACK)], config: cfg(5, TWO_CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.phase === 'cycle');
    },
  },
  {
    name: 'config-chunk-difficulty-15',
    covers: ['required: chunkDifficulty 15'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(1, 15) },
    script: d => {
      d.until(s => s.phase === 'cycle');
    },
  },
  {
    name: 'config-chunk-difficulty-100',
    covers: ['required: chunkDifficulty 100 (every card whole)'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, 100) },
    script: d => {
      d.finish();
    },
  },
  {
    name: 'config-min-words-3',
    covers: ['required: buildItems minWordsToChunk 3'],
    setup: { deck: OC_DECK.slice(0, 2), config: cfg(1, 35), minWordsToChunk: 3, shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.phase === 'cycle');
    },
  },
  {
    name: 'empty-deck',
    covers: ['finalCheck.spec.ts: starts complete: the Final check with no card to serve and currentId SESSION_COMPLETE_ID'],
    setup: { deck: [], config: cfg(3, 35) },
    script: d => {
      d.do('next').do('probe');
    },
  }
);

// ----- Spec twins: the vitest specs' own sessions, step for step -----
SCENARIOS.push(
  {
    name: 'c1-e2e-four-chunk-reps-3',
    covers: [
      "c1.spec.ts: 4-chunk answer, encodeReps=3: 8 chunk trials (4 presented + 4 blind, C8a/C8b) + (1+1+3) combine + 2 cycle = 15 trials, 11 counted attempts, 0 misses",
      'c8a.spec.ts: the final combine window still needs encodeReps consecutive blind successes',
    ],
    setup: { deck: one(FOUR_CHUNK_BACK), config: cfg(3, CHUNK_DIFFICULTY) },
    script: d => {
      d.until(s => s.phase === 'cycle').do('correct').do('next').do('correct').do('next');
      d.finish();
    },
  },
  {
    name: 'c3-interleave-five-chunked',
    covers: ['c3.spec.ts: visits more than one distinct item before the first item reaches ready'],
    setup: { deck: chunkedDeckOf(5), config: cfg(1, CHUNK_DIFFICULTY, { batchSize: 5 }), batchSize: 5 },
    script: d => {
      d.until(s => s.items.some(it => it.status === 'ready'));
    },
  },
  {
    name: 'c3-single-item-massed',
    covers: ['c3.spec.ts: is fully massed (one item at a time) when there is only a single item -- batching never changes single-item behavior'],
    setup: { deck: chunkedDeckOf(1), config: cfg(1, CHUNK_DIFFICULTY, { batchSize: 5 }), batchSize: 5 },
    script: d => {
      d.steps(10);
    },
  },
  {
    name: 'c4-progress-perfect-session',
    covers: [
      'c4.spec.ts: never decreases, starts > 0 after the first correct chunk, and reaches exactly 1.0 only once every item is mastered',
    ],
    setup: { deck: one(FOUR_CHUNK_BACK), config: cfg(2, CHUNK_DIFFICULTY) },
    script: d => {
      d.finish();
    },
  },
  {
    name: 'c5-full-stage-cue',
    covers: [
      'c5.spec.ts: full stage: firstLetter cue on the first attempt, none once a streak starts',
      'c5.spec.ts: an exact answer still auto-advances (only wrong verdicts became manual)',
      'c5.spec.ts: chunks/combine/full misses return advance: manual instead of auto-retrying on a timer',
    ],
    setup: { deck: one(FULL_STAGE_BACK), config: cfg(2, CHUNK_DIFFICULTY) },
    script: d => {
      d.do('wrong:nonsense').do('next').do('correct');
    },
  },
  {
    name: 'c5-chunks-presentation-cue',
    covers: ['c5.spec.ts: chunks stage: each chunk starts with a presentation, not firstLetter (C8b)'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY) },
    script: d => {
      d.do('type:anything').do('wrong:wrong').do('next').do('type:anything').do(`type:${TWO_CHUNK_CHUNKS[0]}`);
    },
  },
  {
    name: 'c5-cycle-blind',
    covers: ['c5.spec.ts: cycle stage: always fully blind, same as before C5 (no copy-typing attempt existed there)'],
    setup: { deck: one(FULL_STAGE_BACK), config: cfg(1, CHUNK_DIFFICULTY) },
    script: d => {
      d.do('correct');
    },
  },
  {
    name: 'c5-no-graded-full-cue',
    covers: ['c5.spec.ts: walking a full session (chunks -> combine -> cycle) never yields a graded cue that reveals the full text pre-attempt'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY) },
    script: d => {
      d.finish();
    },
  },
  ...[1, 2, 3, 5].map(
    (encodeReps): Scenario => ({
      name: `c8a-chunk-cued-plus-blind-reps-${encodeReps}`,
      covers: [`c8a.spec.ts: a chunk needs exactly 1 cued + 1 blind at encodeReps=${encodeReps} (does not advance on the cued attempt alone, and does not need more than one blind success)`],
      setup: { deck: one(FOUR_CHUNK_BACK), config: cfg(encodeReps, CHUNK_DIFFICULTY) },
      script: d => {
        d.do(`type:${FOUR_CHUNK_CHUNKS[0]}`).do(`type:${FOUR_CHUNK_CHUNKS[0]}`);
      },
    })
  ),
  {
    name: 'c8a-full-stage-reps-3',
    covers: ['c8a.spec.ts: the full stage still needs encodeReps consecutive blind successes'],
    setup: { deck: one(FULL_STAGE_BACK), config: cfg(3, CHUNK_DIFFICULTY) },
    script: d => {
      d.do('correct').do('correct').do('correct');
    },
  },
  ...['', 'anything', 'nonsense that would fail grading'].map(
    (typed, k): Scenario => ({
      name: `c8b-presentation-${k}`,
      covers: [
        'c8b.spec.ts: cue is { kind: "present" } with no payload -- the text to show is Trial.target',
        'c8b.spec.ts: advances chunkStreak from 0 to 1 regardless of what is "typed", never counts as an attempt or a miss',
        ...(k === 0 ? ['c8b.spec.ts: the subsequent blind attempt (chunkStreak 1) is the first one that can actually be wrong'] : []),
      ],
      setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY) },
      script: d => {
        d.do(`type:${typed}`);
        if (k === 0) d.do('wrong:nonsense');
      },
    })
  ),
  ...(['cumulative', 'exhaustive'] as const).map(
    (ladderMode): Scenario => ({
      name: `chain-contiguity-${ladderMode}`,
      covers: [
        ladderMode === 'cumulative'
          ? 'chainContiguity.spec.ts: cumulative ladder: chunks and intermediate windows run back to back, then the final window rotates'
          : 'chainContiguity.spec.ts: exhaustive ladder: short-of-criterion reps on intermediate windows stay on the card too',
      ],
      setup: { deck: LONG_DECK, config: cfg(3, CHUNK_DIFFICULTY, { ladderMode }), shuffleWithinBatch: false },
      script: d => {
        d.until(s => s.phase !== 'encode');
      },
    })
  ),
  {
    name: 'chain-contiguity-remediation',
    covers: ['chainContiguity.spec.ts: remediation stays on the card and contiguity holds up to the final window'],
    setup: { deck: LONG_DECK, config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.currentId === 1 && itemIn(s, 1).stage === 'combine');
      d.do('wrong:large green trees').do('next');
      d.until(s => s.phase !== 'encode');
    },
  },
  {
    name: 'chain-contiguity-full-stage-only',
    covers: ['chainContiguity.spec.ts: full-stage only: consecutive graded trials alternate cards while more than one is encoding (Phase 2 unchanged)'],
    setup: { deck: [LONG_DECK[0], LONG_DECK[2]], config: cfg(3, CHUNK_DIFFICULTY), shuffleWithinBatch: false },
    script: d => {
      d.until(s => s.phase !== 'encode');
    },
  },
  {
    name: 'characterization-full-stage-walk',
    covers: [
      'characterization.engine.spec.ts (shared suite): full-stage card: encode -> cycle -> mastered > walks the exact (stage,target,streak,status) sequence',
      "characterization.engine.spec.ts: one shuffled Final-check trial over the single item, then the session finishes",
    ],
    setup: { deck: one(FULL_STAGE_BACK, 'Q1'), config: cfg(2, 35) },
    script: d => {
      d.do('correct').do('correct').do('wrong:nope').do('next').do('correct').do('next').do('correct').do('next');
      d.do('correct').do('next');
    },
  },
  {
    name: 'characterization-two-chunk-walk',
    covers: [
      'characterization.engine.spec.ts (shared suite): two-chunk card: chunks -> combine miss -> remediate -> combine -> ready > walks the exact (stage,target,streak,status) sequence, correctly attributing the miss to only the culprit chunk (post-B1-fix)',
    ],
    setup: { deck: one(TWO_CHUNK_BACK, 'Q2'), config: cfg(2, TWO_CHUNK_DIFFICULTY, { ladderMode: 'exhaustive' }) },
    script: d => {
      d.do(`type:${TWO_CHUNK_CHUNKS[0]}`).do(`type:${TWO_CHUNK_CHUNKS[0]}`);
      d.do(`type:${TWO_CHUNK_CHUNKS[1]}`).do(`type:${TWO_CHUNK_CHUNKS[1]}`);
      d.do(`type:${TWO_CHUNK_CHUNKS[1]}`).do('next');
      d.do(`type:${TWO_CHUNK_CHUNKS[0]}`).do(`type:${TWO_CHUNK_CHUNKS[0]}`);
      d.do(`type:${TWO_CHUNK_BACK}`).do(`type:${TWO_CHUNK_BACK}`);
    },
  },
  {
    name: 'characterization-cycle-walk',
    covers: ['characterization.engine.spec.ts (shared suite): cycle phase: miss resets streak, reinsertion keeps the item in the queue > walks miss -> correct -> correct -> mastered'],
    setup: { deck: one(FULL_STAGE_BACK, 'Q5'), config: cfg(1, 35) },
    script: d => {
      d.do('correct').do('wrong:wrong').do('next').do('correct').do('next').do('correct');
    },
  },
  {
    name: 'characterization-purity-remediate',
    covers: ['characterization.engine.spec.ts: a remediate-stage answer leaves the original state.items entry untouched (Python: every step deep-copies the input and checks it after)'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY) },
    script: d => {
      d.do(`type:${TWO_CHUNK_CHUNKS[0]}`).do(`type:${TWO_CHUNK_CHUNKS[0]}`);
      d.do(`type:${TWO_CHUNK_CHUNKS[1]}`).do(`type:${TWO_CHUNK_CHUNKS[1]}`);
      d.do(`type:${TWO_CHUNK_CHUNKS[1]}`).do('next');
      d.do(`type:${TWO_CHUNK_CHUNKS[0]}`);
    },
  },
  {
    name: 'characterization-b2-encode',
    covers: [
      'characterization.engine.spec.ts: encode phase: reveal then type the now-visible answer correctly -- streak resets, no miss counted',
      'characterization.engine.spec.ts: encode phase: reveal then type something wrong -- still resets to 0, still no miss counted',
    ],
    setup: { deck: one(FULL_STAGE_BACK), config: cfg(2, 35) },
    script: d => {
      d.do('correct').do('reveal').do('correct').do('reveal:nonsense');
    },
  },
  {
    name: 'characterization-b2-combine',
    covers: ['characterization.engine.spec.ts: combine stage: reveal resets combineStreak, not combineMissCount'],
    setup: { deck: one(TWO_CHUNK_BACK), config: cfg(2, TWO_CHUNK_DIFFICULTY) },
    script: d => {
      d.steps(4).do('correct').do('reveal');
    },
  },
  {
    name: 'characterization-b2-cycle',
    covers: ['characterization.engine.spec.ts: cycle phase: reveal resets cycleStreak, reinserts into queue, no miss counted, still manual advance'],
    setup: { deck: one(FULL_STAGE_BACK), config: cfg(1, 35) },
    script: d => {
      d.do('correct').do('reveal');
    },
  },
  {
    name: 'cycle-gap-shuffled',
    covers: ['cycleGap.spec.ts: every first-correct card is not served again until every other queued card has been served (perfect learner)'],
    setup: { deck: shortDeckOf(5), config: cfg(1, 35, { batchSize: 5, cycleOrder: 'shuffled' }), batchSize: 5, startInCycle: true },
    script: d => {
      d.until(s => s.phase === 'final');
    },
  },
  {
    name: 'cycle-order-inorder-perfect',
    covers: ['cycleOrder.spec.ts: a perfect run is two full passes in deck order'],
    setup: { deck: shortDeckOf(5), config: cfg(1, 35, { batchSize: 5, cycleOrder: 'inOrder' }), batchSize: 5, startInCycle: true },
    script: d => {
      for (let n = 0; n < 10; n++) d.answerAndContinue('correct');
    },
  },
  {
    name: 'cycle-order-inorder-miss',
    covers: ['cycleOrder.spec.ts: a miss does not break order: the card returns on the next pass'],
    setup: { deck: shortDeckOf(5), config: cfg(1, 35, { batchSize: 5, cycleOrder: 'inOrder' }), batchSize: 5, startInCycle: true },
    script: d => {
      for (let n = 0; n < 11; n++) d.answerAndContinue(n < 5 && d.state.currentId === 1 ? 'wrong:zzzz wrong' : 'correct');
    },
  },
  {
    name: 'cycle-order-inorder-reveal',
    covers: ['cycleOrder.spec.ts: a revealed answer also waits for the next pass'],
    setup: { deck: shortDeckOf(4), config: cfg(1, 35, { batchSize: 4, cycleOrder: 'inOrder' }), batchSize: 4, startInCycle: true },
    script: d => {
      d.do('reveal:');
    },
  },
  {
    name: 'cycle-order-inorder-batch-scope',
    covers: ['cycleOrder.spec.ts: is scoped to the current batch'],
    setup: { deck: shortDeckOf(8), config: cfg(1, 35, { batchSize: 5, cycleOrder: 'inOrder' }), batchSize: 5, startInCycle: true },
    script: () => {},
  },
  ...(['shuffled', undefined] as const).map(
    (cycleOrder): Scenario => ({
      name: `cycle-order-${String(cycleOrder)}-first-correct`,
      covers: [`cycleOrder.spec.ts: cycleOrder=${String(cycleOrder)}: a first correct is reinserted into the current pass`],
      setup: { deck: shortDeckOf(5), config: cfg(1, 35, { batchSize: 5, ...(cycleOrder ? { cycleOrder } : {}) }), batchSize: 5, startInCycle: true },
      script: d => {
        d.do('correct');
      },
    })
  ),
  {
    name: 'cycle-order-encode-deck-order',
    covers: ['cycleOrder.spec.ts: keeps deck order and the first encode trial is the first card'],
    setup: { deck: shortDeckOf(12), config: cfg(1, 35, { batchSize: 5 }), batchSize: 5, shuffleWithinBatch: false },
    script: d => {
      d.steps(5);
    },
  },
  {
    name: 'final-check-perfect-six',
    covers: ['finalCheck.spec.ts: a shuffled, cue-free pass serves each item exactly once, then the session completes'],
    setup: { deck: shortDeckOf(6), config: cfg(1, 35) },
    script: d => {
      d.finish().do('probe');
    },
  },
  {
    name: 'final-check-counter',
    covers: ["finalCheck.spec.ts: the \"k of N\" counter reads N of N right after the last card's correct answer, before Continue is clicked"],
    setup: { deck: shortDeckOf(3), config: cfg(1, 35) },
    script: d => {
      d.until(s => s.phase === 'final').answerAndContinue('correct').answerAndContinue('correct').do('correct');
    },
  },
  {
    name: 'final-check-miss-requeue',
    covers: ['finalCheck.spec.ts: a wrong answer comes back only after every other pending card, and the session waits for it'],
    setup: { deck: shortDeckOf(4), config: cfg(1, 35) },
    script: d => {
      d.until(s => s.phase === 'final').do('wrong:totally wrong').do('next');
      d.finish().do('probe');
    },
  },
  {
    name: 'final-check-reveal',
    covers: ['finalCheck.spec.ts: increments finalMisses, leaves stats.misses alone, and requeues to the end'],
    setup: { deck: shortDeckOf(3), config: cfg(1, 35) },
    script: d => {
      d.until(s => s.phase === 'final').do('reveal:');
    },
  },
  {
    name: 'final-check-multiplier',
    covers: ['finalCheck.spec.ts: reads exactly 1 for a perfect learner throughout -- at the start of the Final check, partway through it, and once it completes'],
    setup: { deck: shortDeckOf(4), config: cfg(1, 35) },
    script: d => {
      d.finish();
    },
  },
  {
    name: 'rep-rotation-full-stage',
    covers: [
      'repRotation.spec.ts: no two consecutive graded encode trials are on the same card while more than one card is still encoding',
      'repRotation.spec.ts: a wrong answer serves the same card next',
    ],
    setup: {
      deck: [
        { front: 'Q0', back: 'answer zero' },
        { front: 'Q1', back: 'answer one' },
        { front: 'Q2', back: 'answer two' },
      ],
      config: cfg(3, CHUNK_DIFFICULTY),
      shuffleWithinBatch: false,
    },
    script: d => {
      d.do('wrong:nonsense wrong answer').do('next');
      d.until(s => s.phase !== 'encode');
    },
  },
  {
    name: 'rep-rotation-presentation-adjacent',
    covers: ['repRotation.spec.ts: a presentation trial and its blind attempt stay adjacent, and final-window reps rotate while another card is still encoding'],
    setup: {
      deck: [
        { front: 'Trees', back: FOUR_CHUNK_BACK },
        { front: 'Filler', back: 'a filler answer' },
      ],
      config: cfg(8, CHUNK_DIFFICULTY),
      shuffleWithinBatch: false,
    },
    script: d => {
      d.until(s => s.phase !== 'encode');
    },
  },
  {
    name: 'telemetry-answers',
    covers: [
      'telemetry.spec.ts: counts a correct answer as an attempt on that card only',
      'telemetry.spec.ts: records a wrong answer as a miss on the card',
      'telemetry.spec.ts: records a reveal on the card and in stats.reveals, never as a miss',
      'telemetry.spec.ts: records a near-miss',
      'telemetry.spec.ts: is what the batch summary reports',
    ],
    setup: { deck: TELEMETRY_DECK, config: cfg(3, 35, { cycleOrder: 'inOrder' }), shuffleWithinBatch: false, stats: 'empty' },
    script: d => {
      d.do('reveal').do('wrong:slow heart').do('next').do('near:the fast heart rate').do('correct');
    },
  },
  {
    name: 'telemetry-presentation-and-hard-span',
    covers: [
      'telemetry.spec.ts: does not count a chunk presentation',
      'telemetry.spec.ts: records the chunk that broke while combining as a hard span',
    ],
    setup: { deck: TELEMETRY_DECK, config: cfg(3, 35, { cycleOrder: 'inOrder' }), shuffleWithinBatch: false, stats: 'empty' },
    script: d => {
      d.until(on(1));
      d.until(s => s.currentId === 1 && itemIn(s, 1).stage === 'combine' && itemIn(s, 1).combineSeqIdx === 0);
      d.do(`wrong:${d.cur.chunks![0]} zzz qqq`).do('next');
      d.do('wrong:zzz').do('next').do('wrong:zzz').do('next');
      d.finish().do('probe');
    },
  }
);

// ----- Pure functions: history, accuracy, progress, estimates -----
function exportPureCases() {
  return withSeededRandom(hashSeed('golden:session:pure'), pureCases);
}

function pureCases() {
  const items = buildItems(OC_DECK, 35, 'cumulative', undefined, undefined, false);
  const doneState = (its: DrillItem[], startTime?: number, batchSize?: number): SessionState => ({
    items: its,
    phase: 'final',
    queue: [],
    stats: { ...emptyStats(), attempts: 12, misses: 2, reveals: 1, ...(startTime === undefined ? {} : { startTime }) },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: emptyStats(),
    config: { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative', ...(batchSize === undefined ? {} : { batchSize }) },
  });
  const scoredItems = items.map((it, k) =>
    k === 1 ? { ...it, attempts: 9, misses: 2, reveals: 1, finalMisses: 1, hardSpans: ['normal range'] } : it
  );
  const historyEntries = [
    { state: doneState(scoredItems, Date.UTC(2026, 8, 30, 9)), finishedAt: Date.UTC(2026, 8, 30, 10) },
    { state: doneState(items), finishedAt: FIXED_FINISHED_AT },
    { state: doneState(items, 0, 5), finishedAt: 0 },
    { state: doneState(scoredItems, -1, 2), finishedAt: 253402300800000 },
  ].map(({ state, finishedAt }) => ({ state, finishedAt, out: buildHistoryEntry(state, new Date(finishedAt)) }));

  const rng = makeRng('golden:session:rank');
  const maybe = (p: number, v: number) => (rng.chance(p) ? v : undefined);
  const rankCases: unknown[] = [
    [
      { ...items[0], misses: 1, attempts: 4 },
      { ...items[1], misses: 1, reveals: 1, attempts: 9 },
      { ...items[2], finalMisses: 1, attempts: 6 },
    ],
    [{ ...items[0], attempts: 5 }, { ...items[1], misses: 3 }, { ...items[2], misses: 1 }],
  ].map(list => ({ items: list, limits: [5, 1, 0, -1, 10].map(limit => ({ limit, ids: rankHardestCards(list, limit).map(i => i.id) })) }));
  for (let k = 0; k < 40; k++) {
    const n = rng.int(0, 9);
    const ids = shuffle(Array.from({ length: n }, (_, i) => i * 3 + rng.int(0, 2)));
    const list = ids.map(id => {
      const it: DrillItem = { ...items[0], id };
      const fields: [keyof DrillItem, number | undefined][] = [
        ['misses', maybe(0.6, rng.int(0, 2))],
        ['reveals', maybe(0.4, rng.int(0, 2))],
        ['finalMisses', maybe(0.3, rng.int(0, 1))],
        ['attempts', maybe(0.8, rng.int(0, 4))],
      ];
      for (const [key, v] of fields) if (v !== undefined) (it as unknown as Record<string, number>)[key] = v;
      return it;
    });
    rankCases.push({
      items: list,
      trouble: list.map(cardTroubleScore),
      limits: [5, 1, 3, 0, -1, -3, 20].map(limit => ({ limit, ids: rankHardestCards(list, limit).map(i => i.id) })),
    });
  }

  const accuracyInputs = [
    { attempts: 10, misses: 2, reveals: 3 },
    { attempts: 4, misses: 1 },
    { attempts: 0, misses: 0, reveals: 0 },
    { attempts: 1, misses: 1, reveals: 1 },
    { attempts: -2, misses: 0 },
    { attempts: 8, misses: 1, reveals: 0 },
    { attempts: 200, misses: 1 },
    { attempts: 200, misses: 3 },
    { attempts: 7, misses: 9, reveals: 2 },
  ];
  for (let a = 1; a <= 12; a++) for (let m = 0; m <= a; m += 3) accuracyInputs.push({ attempts: a, misses: m, reveals: a - m > 1 ? 1 : 0 });

  // computeItemProgress over every stage, position and encodeReps.
  const [four] = buildItems(one(FOUR_CHUNK_BACK), CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
  const [full] = buildItems(one(FULL_STAGE_BACK), CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
  const progressItems: DrillItem[] = [
    four,
    { ...four, status: 'ready' },
    { ...four, status: 'mastered' },
    { ...four, combineSeq: null, status: 'encoding' },
    { ...four, chunks: [], combineSeq: [], status: 'encoding' },
    { ...full, status: 'encoding', encodeStreak: 7 },
  ];
  for (const stage of ['chunks', 'combine', 'remediate'] as const) {
    for (let idx = 0; idx <= 4; idx++) {
      for (const streak of [0, 1, 2, 4]) {
        progressItems.push({ ...four, status: 'encoding', stage, chunkIndex: idx, chunkStreak: streak, combineSeqIdx: Math.min(idx, 3), combineStreak: streak });
      }
    }
  }
  for (let streak = 0; streak <= 4; streak++) progressItems.push({ ...full, status: 'encoding', encodeStreak: streak });
  const itemProgress = progressItems.map(item => ({ item, out: [0, 1, 2, 3, 5].map(r => computeItemProgress(item, r)) }));
  const sessionProgress = [
    { items: progressItems.slice(0, 6), batch: null },
    { items: progressItems.slice(6, 30), batch: progressItems.slice(10, 13) },
    { items: [], batch: [] },
    { items: [four, full], batch: [] },
  ].map(({ items: its, batch }) => ({
    items: its,
    batch,
    out: [1, 2, 3].map(r => (batch === null ? computeSessionProgress(its, r) : computeSessionProgress(its, r, batch))),
  }));

  const rangePairs: [number, number][] = [
    [0, 0], [30, 59.9], [59.999, 60], [60, 60], [60, 89.99], [89.99, 90], [90, 149.9], [150, 150], [600, 1200], [100000, 200000], [29.99, 1e9], [-5, 0],
  ];
  const builtProse = buildItems(proseDeck, 35, 'cumulative', undefined, undefined, false);
  const builtExhaustive = buildItems(proseDeck, 35, 'exhaustive', undefined, undefined, false);
  const minimumCases: { items: DrillItem[]; ladderMode: LadderMode | null; include: boolean }[] = [
    { items: builtProse, ladderMode: 'cumulative', include: true },
    { items: builtExhaustive, ladderMode: 'exhaustive', include: true },
    { items: builtExhaustive, ladderMode: 'exhaustive', include: false },
    { items: builtProse, ladderMode: null, include: true },
    { items: buildItems(shortDeck, 35, 'cumulative', undefined, undefined, false), ladderMode: 'cumulative', include: false },
  ];
  const minimumTrials = minimumCases.map(({ items: its, ladderMode, include }) => ({
    deck: its === builtProse || its === builtExhaustive ? 'proseDeck' : 'shortDeck',
    built: ladderMode === 'exhaustive' ? 'exhaustive' : 'cumulative',
    ladderMode,
    include,
    out: [1, 3, 5].map(r => computeMinimumTrials(its, r, ladderMode ?? undefined, include)),
  }));
  const shapeDecks: DeckItem[][] = [
    [],
    [{ front: 'a', back: 'one two three four five six seven eight nine' }, { front: 'b', back: 'x' }],
    [{ front: 'a', back: 'one two three four five six seven eight nine' }],
    [{ front: 'a', back: ' one  two\tthree four five six seven eight ' }],
    [...shortDeck.slice(0, 2), ...proseDeck.slice(0, 3)],
  ];
  const estimateCases = {
    formatColdStartRange: rangePairs.map(([lo, hi]) => ({ lo, hi, out: formatColdStartRange(lo, hi) })),
    estimateColdStartSeconds: [
      { trials: 10, items: [], out: estimateColdStartSeconds(10, []) },
      { trials: 0, items: shortDeck, out: estimateColdStartSeconds(0, shortDeck) },
      { trials: 72, items: shortDeck, out: estimateColdStartSeconds(72, shortDeck) },
      { trials: 129, items: [{ back: '\u{1f600}\u{e9}' }], out: estimateColdStartSeconds(129, [{ back: '\u{1f600}\u{e9}' }]) },
    ],
    computeMinimumTrials: minimumTrials,
    pickColdStartDeckShape: shapeDecks.map(deck => ({ deck, out: pickColdStartDeckShape(deck) })),
  };

  const orderCases = [[3, 0, 4, 1, 2], [], [7], [5, 5, 1]].map((ids, k) =>
    withSeededRandom(hashSeed(`golden:orderCycleQueue:${k}`), () => ({
      ids,
      seed: hashSeed(`golden:orderCycleQueue:${k}`),
      inOrder: orderCycleQueue(ids, 'inOrder'),
      shuffled: orderCycleQueue(ids, 'shuffled'),
      byDefault: orderCycleQueue(ids),
    }))
  );

  // Hand-built states the scripted sessions can't reach.
  const [fullItem] = buildItems(one(FULL_STAGE_BACK), 35, 'cumulative', undefined, undefined, false);
  const [chunkItem] = buildItems(one(FOUR_CHUNK_BACK), CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false);
  const edgeBase: SessionState = {
    items: [fullItem],
    phase: 'encode',
    queue: [],
    stats: { ...ZERO_STATS },
    currentId: 0,
    batchIndex: 0,
    batchStartStats: { ...ZERO_STATS },
    config: cfg(2, CHUNK_DIFFICULTY),
  };
  const edgeStates: Record<string, SessionState> = {
    remediateEmptyStack: { ...edgeBase, items: [{ ...chunkItem, status: 'encoding', stage: 'remediate', remediateStack: [] }] },
    noCurrentItem: { ...edgeBase, currentId: 7 },
    noCurrentItemCycle: { ...edgeBase, phase: 'cycle', items: [{ ...fullItem, status: 'ready' }], currentId: SESSION_COMPLETE_ID },
  };
  const answerEdges = [
    { state: 'remediateEmptyStack', typed: 'large green', revealed: true },
    { state: 'noCurrentItem', typed: 'x', revealed: false },
    { state: 'noCurrentItemCycle', typed: 'x', revealed: true },
  ].map(c => {
    try {
      const r = applyAnswer(edgeStates[c.state], c.typed, { revealed: c.revealed });
      return { ...c, out: { verdict: r.verdict, feedback: r.feedback, advance: r.advance, state: r.state } };
    } catch (e) {
      return { ...c, error: (e as Error).message };
    }
  });
  const editEdges = ['noCurrentItem', 'noCurrentItemCycle'].map(state => {
    const input = edgeStates[state];
    const r = editCurrentItem(input, { front: 'x', back: 'y' });
    return { state, unchanged: r.state === input, restarted: r.restarted, trial: selectTrial(input) };
  });

  return {
    historyEntries,
    historyCards: items.map(it => ({ item: it, out: buildHistoryCard(it) })),
    rankHardestCards: rankCases,
    accuracy: accuracyInputs.map(stats => ({ stats, out: computeAccuracyPercent(stats) })),
    itemProgress,
    sessionProgress,
    estimates: estimateCases,
    orderCycleQueue: orderCases,
    dwellMs: DWELL_MS,
    sessionCompleteId: SESSION_COMPLETE_ID,
    edgeStates,
    answerEdges,
    editEdges,
  };
}

function exportSessionScenarios(): void {
  const names = new Set<string>();
  const headers: unknown[] = [];
  const steps: unknown[] = [];
  for (const sc of SCENARIOS) {
    if (names.has(sc.name)) throw new Error(`duplicate scenario name ${sc.name}`);
    names.add(sc.name);
    const run = runScenario(sc);
    headers.push(run.header);
    steps.push(...run.steps);
  }
  writeGolden('session_scenarios.json', {
    fixed: { saveTimestamp: FIXED_SAVE_TIMESTAMP, startTime: FIXED_START_TIME, finishedAt: FIXED_FINISHED_AT, appDefaults: APP_DEFAULTS },
    scenarios: headers,
    steps,
    pure: exportPureCases(),
  });
}

// ---------------------------------------------------------------------------

const fullIdx = process.argv.indexOf('--full');
if (fullIdx >= 0) {
  exportFullDebug(process.argv[fullIdx + 1] ?? '');
} else {
  const pairs = gradingPairs();
  exportPrng();
  exportJscompat();
  exportGrading(pairs);
  exportItems(pairs.map(([, target]) => target));
  exportSessionSim();
  exportSessionScenarios();
  console.log(`golden data written to ${OUT_DIR}`);
}
