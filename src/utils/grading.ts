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
export function grade(
  typed: string,
  target: string,
  opts?: { lenient?: boolean; stemTolerance?: boolean; strictPunctuation?: boolean }
): GradeResult {
  const lenient = opts?.lenient ?? true;
  const stemTolerance = opts?.stemTolerance ?? true;
  const strict = opts?.strictPunctuation ?? false;

  const diff = computeWordDiff(typed, target, strict);

  if (exactMatch(typed, target, strict)) {
    return { verdict: 'exact', diff, missingWords: [], extraWords: [], similarity: 1 };
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
