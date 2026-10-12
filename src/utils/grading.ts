// Answer normalization, word-level diffing, and grading (exact / near / wrong).

// Phase 1 (punctuation normalization): forgives punctuation that never
// changes meaning (commas, parens, quotes, slashes, hyphens between letters,
// accents, etc.) while still protecting the two places a symbol carries real
// content -- a decimal point between digits (7.4) and a leading minus sign
// on a number (-5, not a word-prefix hyphen like "-itis" or a range like
// 10-20). Those are shielded behind private-use placeholders before the
// generic punctuation strip runs, then restored.
const DECIMAL_MARKER = '';
const NEGATIVE_MARKER = '';

export function norm(s: string): string {
  return s
    .normalize('NFKD').replace(/[̀-ͯ]/g, '') // é -> e
    .toLowerCase()
    .replace(/[−–—]/g, '-') // minus/en/em dash -> -
    .replace(/(\d)[.,](?=\d)/g, `$1${DECIMAL_MARKER}`) // protect decimals: 7.4
    .replace(/(?<![a-z0-9]\s*)-\s*(?=\d)/g, NEGATIVE_MARKER) // protect negatives: -5 (not ranges 10-20)
    .replace(new RegExp(`[^a-z0-9 ${DECIMAL_MARKER}${NEGATIVE_MARKER}+%<>=]`, 'g'), '')
    .split(DECIMAL_MARKER).join('.')
    .split(NEGATIVE_MARKER).join('-')
    .replace(/\s+/g, ' ').trim();
}

// C2/Phase 1: the exact-match check grading and remediation both rely on --
// spacing-insensitive on top of norm() (see grade() and culpritHalf() below)
// so a card's own spacing habits never separately decide correctness on top
// of what norm() already forgives.
export function exactMatch(a: string, b: string, strict: boolean = false): boolean {
  const n = strict ? normStrict : norm;
  return n(a).replace(/ /g, '') === n(b).replace(/ /g, '');
}

// Phase 2 (per-deck strict punctuation): unlike norm(), this only ignores
// accents, decorative/structural punctuation (brackets, quotes, apostrophes,
// commas, colons, semicolons) and sentence-ending . ! ? -- every other
// symbol (hyphens, slashes, +, %, <, >, =, a digit-internal period like
// 7.35) must match literally, and grade() disables the near-miss tier
// entirely under strict, so every word is required too. Used for both the
// whole-string exact check (exactMatch) and, per-word, by alignWords/
// wordNorm below (for diff highlighting), so a strict deck's diff view never
// shows a symbol as mismatched that its exact check already forgave.
function normStrict(s: string): string {
  return s
    .normalize('NFKD').replace(/[̀-ͯ]/g, '') // accents ignored: é -> e
    .toLowerCase()
    .replace(/[‘’“”]/g, "'") // curly quotes -> '
    .replace(/[−–—]/g, '-') // minus/en/em dash -> -
    .replace(/[()\[\]{}"',:;]/g, '') // brackets, quotes, apostrophes, commas, colons, semicolons ignored
    .replace(/[.!?]+(?=\s|$)/g, '') // sentence-ending . ! ? ignored; 7.35 kept
    .replace(/\s+/g, ' ').trim();
}

// Per-word normalizer alignWords/grade() use for the near-miss word
// alignment -- norm() in lenient mode, normStrict() in strict mode, so the
// word-level comparison a "near" verdict depends on never disagrees with
// what the deck's exact check would forgive.
function wordNorm(w: string, strict: boolean): string {
  return strict ? normStrict(w) : norm(w);
}

export interface WordDiffResult {
  word: string;
  matched: boolean;
}

interface WordAlignment {
  matchedTypedIdx: boolean[];
  matchedTargetIdx: boolean[];
  lcsLength: number;
}

// Shared LCS (longest common subsequence) alignment between two word lists,
// order-preserving. Used by computeWordDiff (target-side match flags, for the
// red/green diff UI) and grade() (both-side match flags + similarity, for C2
// lenient grading) -- extracted once so both stay in sync rather than
// duplicating the DP.
function alignWords(typedWords: string[], targetWords: string[], strict: boolean = false): WordAlignment {
  const tN = typedWords.map(w => wordNorm(w, strict));
  const gN = targetWords.map(w => wordNorm(w, strict));
  const n = tN.length;
  const m = gN.length;

  const dp: number[][] = [];
  for (let i = 0; i <= n; i++) {
    dp.push(new Array(m + 1).fill(0));
  }

  for (let i = 1; i <= n; i++) {
    for (let j = 1; j <= m; j++) {
      if (tN[i - 1] === gN[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  const matchedTyped = new Array(n).fill(false);
  const matchedTarget = new Array(m).fill(false);
  let i = n;
  let jj = m;
  while (i > 0 && jj > 0) {
    if (tN[i - 1] === gN[jj - 1]) {
      matchedTyped[i - 1] = true;
      matchedTarget[jj - 1] = true;
      i--;
      jj--;
    } else if (dp[i - 1][jj] >= dp[i][jj - 1]) {
      i--;
    } else {
      jj--;
    }
  }

  return { matchedTypedIdx: matchedTyped, matchedTargetIdx: matchedTarget, lcsLength: dp[n][m] };
}

export function computeWordDiff(typedStr: string, targetStr: string, strict: boolean = false): WordDiffResult[] {
  const typedWords = typedStr.trim().length ? typedStr.trim().split(/\s+/) : [];
  const targetWords = targetStr.trim().split(/\s+/);
  const { matchedTargetIdx } = alignWords(typedWords, targetWords, strict);

  return targetWords.map((word, idx) => ({
    word,
    matched: matchedTargetIdx[idx],
  }));
}

// C2: stopwords whose omission/insertion alone shouldn't fail a trial.
const STOPWORDS = new Set([
  'a', 'an', 'the', 'of', 'to', 'in', 'on', 'for', 'and', 'or', 'is', 'are',
  'was', 'were', 'that', 'this', 'it', 'its', 'as', 'at', 'by', 'with', 'from',
]);

// C2: strips a light inflectional suffix so "cats"~"cat", "walking"~"walk",
// "walked"~"walk" compare equal. Deliberately shallow -- not a real stemmer.
function lightStem(word: string): string {
  if (word.endsWith('ing') && word.length > 4) return word.slice(0, -3);
  if (word.endsWith('ed') && word.length > 3) return word.slice(0, -2);
  if (word.endsWith('es') && word.length > 3) return word.slice(0, -2);
  if (word.endsWith('s') && word.length > 2) return word.slice(0, -1);
  return word;
}

// List items (2026-10-12), the core of items.ts's listItems: the text split
// on , and ; outside () and [], each part trimmed and stripped of a leading
// "and " / "or ", empty parts dropped. `part` is each kept item's index among
// the raw parts, so a word can be traced back to its item (see
// anyOrderGrade). Any number of items, unlike listItems (3 or more).
interface SplitItems {
  items: string[];
  // Raw part index of each item in `items`.
  part: number[];
}

function splitItemsWithParts(text: string): SplitItems {
  const parts: string[] = [];
  let depth = 0;
  let current = '';
  for (const ch of text) {
    if (ch === '(' || ch === '[') depth++;
    else if ((ch === ')' || ch === ']') && depth > 0) depth--;
    if ((ch === ',' || ch === ';') && depth === 0) {
      parts.push(current);
      current = '';
    } else {
      current += ch;
    }
  }
  parts.push(current);
  const items: string[] = [];
  const part: number[] = [];
  parts.forEach((p, i) => {
    const item = p.trim().replace(/^(?:and|or)\s+/i, '').trim();
    if (item.length > 0) {
      items.push(item);
      part.push(i);
    }
  });
  return { items, part };
}

export function splitListItems(text: string): string[] {
  return splitItemsWithParts(text).items;
}

// For each whitespace-separated word of text.trim() (computeWordDiff's
// words), the raw part (see splitItemsWithParts) its first character is in.
// A separator character belongs to the part it ends.
function wordParts(text: string): number[] {
  const t = text.trim();
  const out: number[] = [];
  let depth = 0;
  let partIdx = 0;
  let inWord = false;
  for (const ch of t) {
    const ws = /\s/.test(ch);
    if (!ws && !inWord) out.push(partIdx);
    inWord = !ws;
    if (ch === '(' || ch === '[') depth++;
    else if ((ch === ')' || ch === ']') && depth > 0) depth--;
    if ((ch === ',' || ch === ';') && depth === 0) partIdx++;
  }
  return out;
}

export interface GradeResult {
  verdict: 'exact' | 'near' | 'wrong';
  diff: WordDiffResult[];
  missingWords: string[];
  extraWords: string[];
  similarity: number; // 0..1
}

// C2: lenient grading. Exact match always wins; otherwise a near-miss tier
// forgives stopword-only differences outright, and forgives a light-stem
// difference (e.g. a dropped plural) too, but only when the rest of the
// answer is otherwise very close (similarity >= 0.9) -- a single stem-level
// slip in a short answer is still `wrong`, since it's too large a fraction of
// the content to wave through; the same slip in a long answer is `near`.
export interface GradeOptions {
  lenient?: boolean;
  stemTolerance?: boolean;
  strictPunctuation?: boolean;
  // 2026-10-12: the target is an unordered list (DrillItem.anyOrder), so its
  // items may be typed in any order. See anyOrderGrade.
  anyOrder?: boolean;
}

export function grade(typed: string, target: string, opts?: GradeOptions): GradeResult {
  const lenient = opts?.lenient ?? true;
  const stemTolerance = opts?.stemTolerance ?? true;
  const strict = opts?.strictPunctuation ?? false;

  const diff = computeWordDiff(typed, target, strict);

  if (exactMatch(typed, target, strict)) {
    return { verdict: 'exact', diff, missingWords: [], extraWords: [], similarity: 1 };
  }

  if (opts?.anyOrder) {
    const unordered = anyOrderGrade(typed, target, { lenient, stemTolerance, strictPunctuation: strict });
    if (unordered) return unordered;
  }

  const typedWords = typed.trim().length ? typed.trim().split(/\s+/) : [];
  const targetWords = target.trim().split(/\s+/);
  const { matchedTypedIdx, matchedTargetIdx, lcsLength } = alignWords(typedWords, targetWords, strict);

  const missingWords = targetWords.filter((_, idx) => !matchedTargetIdx[idx]);
  const extraWords = typedWords.filter((_, idx) => !matchedTypedIdx[idx]);
  const totalLen = typedWords.length + targetWords.length;
  const similarity = totalLen > 0 ? (2 * lcsLength) / totalLen : 0;

  // Phase 2: a strict deck has no near-miss tier at all -- every word is
  // required and no stopword/stem forgiveness applies, same as lenient:
  // false, just for a different reason (punctuation strictness, not a
  // caller opting out of leniency).
  if (!lenient || strict) {
    return { verdict: 'wrong', diff, missingWords, extraWords, similarity };
  }

  const isStopword = (w: string) => STOPWORDS.has(norm(w));

  const stopwordOnlyDifference =
    missingWords.every(isStopword) && extraWords.every(isStopword);

  if (stopwordOnlyDifference) {
    return { verdict: 'near', diff, missingWords, extraWords, similarity };
  }

  if (similarity >= 0.9) {
    const everyMissingIsStopwordOrStemMatch = missingWords.every(w => {
      if (isStopword(w)) return true;
      if (!stemTolerance) return false;
      const stemmed = lightStem(norm(w));
      return extraWords.some(e => lightStem(norm(e)) === stemmed);
    });
    if (everyMissingIsStopwordOrStemMatch) {
      return { verdict: 'near', diff, missingWords, extraWords, similarity };
    }
  }

  return { verdict: 'wrong', diff, missingWords, extraWords, similarity };
}

// Any-order grading of a list target (2026-10-12). Returns null, so grade()
// goes on exactly as for an ordered answer, when the target has fewer than 2
// items (a full answer only gets anyOrder when it is a list of 3+; a combine
// window or a chunk of one is 2+ items) or when the typed text can't be split
// into items (multi-word items typed without separators).
//
// The typed text is split the same way. When that gives fewer items than the
// target and every target item is one word, it is split on whitespace
// instead, dropping "and" and "or". Items are then matched one to one: first
// every exact pair, then near ones, a pair matching when grade() with the same
// options (in order) is exact or near. Every target item matched and no typed
// item left over: "exact" if every pair is exact, else "near"; otherwise
// "wrong". The diff marks every word of a matched target item as matched (a
// dropped "and" counts with its item, a word outside every item counts as
// matched), and missingWords lists the unmatched items' words, so the feedback
// and remediation's culprit search point at the missing items.
function anyOrderGrade(
  typed: string,
  target: string,
  opts: { lenient: boolean; stemTolerance: boolean; strictPunctuation: boolean }
): GradeResult | null {
  const tgt = splitItemsWithParts(target);
  if (tgt.items.length < 2) return null;
  let typedItems = splitListItems(typed);
  const oneWordItems = tgt.items.every(i => i.split(/\s+/).length === 1);
  if (typedItems.length < tgt.items.length && oneWordItems) {
    typedItems = typed
      .trim()
      .split(/\s+/)
      .filter(w => w.length > 0 && !/^(?:and|or)$/i.test(w));
  } else if (typedItems.length < 2) {
    return null;
  }

  // matchOf[i]: the typed item paired with target item i, or -1.
  const matchOf: number[] = tgt.items.map(() => -1);
  const exactPair: boolean[] = tgt.items.map(() => false);
  const used: boolean[] = typedItems.map(() => false);
  const verdicts = tgt.items.map(t => typedItems.map(ty => grade(ty, t, opts).verdict));
  for (const wanted of ['exact', 'near'] as const) {
    tgt.items.forEach((_, i) => {
      if (matchOf[i] !== -1) return;
      const j = typedItems.findIndex((_, k) => !used[k] && verdicts[i][k] === wanted);
      if (j === -1) return;
      matchOf[i] = j;
      used[j] = true;
      exactPair[i] = wanted === 'exact';
    });
  }

  const matchedParts = new Set(tgt.part.filter((_, i) => matchOf[i] !== -1));
  const itemParts = new Set(tgt.part);
  const targetWords = target.trim().split(/\s+/);
  const parts = wordParts(target);
  const diff = targetWords.map((word, idx) => ({
    word,
    matched: !itemParts.has(parts[idx]) || matchedParts.has(parts[idx]),
  }));
  const missingWords = tgt.items.filter((_, i) => matchOf[i] === -1).flatMap(i => i.split(/\s+/));
  const extraWords = typedItems.filter((_, k) => !used[k]).flatMap(i => i.split(/\s+/));
  const matched = matchOf.filter(j => j !== -1).length;
  const similarity = (2 * matched) / (tgt.items.length + typedItems.length);

  let verdict: GradeResult['verdict'] = 'wrong';
  if (matched === tgt.items.length && used.every(u => u)) {
    verdict = exactPair.every(e => e) ? 'exact' : 'near';
  }
  return { verdict, diff, missingWords, extraWords, similarity };
}
