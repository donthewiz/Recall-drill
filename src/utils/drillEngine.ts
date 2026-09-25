import {
  CombineSequenceItem,
  Cue,
  DeckItem,
  DrillItem,
  SavedDeckEntry,
  SavedSessionState,
  DeckFolder,
  SessionState,
  SessionStats,
  Trial,
  Feedback,
  Verdict,
  LadderMode,
  CycleOrder,
} from '../types';

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
function exactMatch(a: string, b: string, strict: boolean = false): boolean {
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

export function parseDeck(text: string): DeckItem[] {
  const lines = text.split('\n');
  const out: DeckItem[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('//') || line.startsWith('#')) continue;

    let front = '';
    let back = '';
    let extra = '';

    if (line.includes('\t')) {
      // Optional third segment ("Extra"): front[TAB]back[TAB]extra. A second
      // tab used to fold into back -- it now starts extra instead.
      const parts = line.split('\t');
      front = parts[0].trim();
      back = (parts[1] || '').trim();
      extra = parts.slice(2).join('\t').trim();
    } else if (line.includes('::')) {
      // Optional third segment: front::back::extra. A second '::' used to
      // fold into back -- it now starts extra instead.
      const parts = line.split('::');
      front = (parts[0] || '').trim();
      back = (parts[1] || '').trim();
      extra = parts.slice(2).join('::').trim();
    } else if (line.includes(' - ') && !line.includes('->')) {
      // Fallback for hyphen separator
      const parts = line.split(' - ');
      front = (parts[0] || '').trim();
      back = (parts.slice(1).join(' - ') || '').trim();
    }

    if (front && back) {
      out.push(extra ? { front, back, extra } : { front, back });
    }
  }

  return out;
}

// Answers at or under this many words skip the chunk/combine ladder
// entirely and use stage 'full' directly -- not worth the ladder's own
// overhead (a chunk now costs a presentation + a blind attempt each, per
// C8, plus a combine window) when a single full-answer recall handles it.
export const MIN_WORDS_TO_CHUNK = 8;

export function chunkText(
  text: string,
  chunkPercent: number = 35,
  minWordsToChunk: number = MIN_WORDS_TO_CHUNK
): string[] | null {
  const words = text.split(/\s+/).filter(w => w.length > 0);
  if (words.length <= minWordsToChunk) return null;

  const pct = Math.max(15, Math.min(100, chunkPercent));
  // 100% means full card at once (no chunking)
  if (pct >= 100) return null;

  // Calculate target chunk size as a percentage of total words in the card.
  // Harder = higher % = more words at once
  const targetChunkSize = Math.max(2, Math.round(words.length * (pct / 100)));

  if (targetChunkSize >= words.length) return null;

  const chunks: string[] = [];
  for (let i = 0; i < words.length; i += targetChunkSize) {
    chunks.push(words.slice(i, i + targetChunkSize).join(' '));
  }

  // Avoid leaving a lonely 1-word trailing chunk
  if (chunks.length > 1 && chunks[chunks.length - 1].split(/\s+/).length <= 1) {
    const last = chunks.pop()!;
    chunks[chunks.length - 1] = chunks[chunks.length - 1] + ' ' + last;
  }

  return chunks.length > 1 ? chunks : null;
}

// C5: attempt-0 cue for a stage-unit. Reveals the first alphanumeric
// character of each alphanumeric RUN within a word (not just index 0 of the
// word), masks the rest of that run with '_', and leaves every
// non-alphanumeric character (spaces via the outer split, apostrophes,
// hyphens, slashes, periods, ...) untouched in place -- "The heart pumps
// blood." becomes "T__ h____ p____ b_____.".
//
// Do NOT simplify this back to "reveal index 0 of the word" -- that was the
// original (buggy) rule, and it breaks medical word parts that lead with
// punctuation, e.g. combining-form suffixes like "-itis"/"-emia": index 0 is
// the hyphen, so the "revealed" character is punctuation and every suffix
// card renders an identical, uninformative "-____". Revealing the first
// alphanumeric of each run instead gives "-itis" -> "-i___" and still
// handles a mid-word boundary like "cardi/o" -> "c____/o" (the 'o' after the
// slash starts a new run and gets its own reveal).
export function renderFirstLetterCue(target: string): string {
  return target
    .split(' ')
    .map(word => {
      let inRun = false;
      return word
        .split('')
        .map(ch => {
          if (!/[a-zA-Z0-9]/.test(ch)) {
            inRun = false;
            return ch;
          }
          const reveal = !inRun;
          inRun = true;
          return reveal ? ch : '_';
        })
        .join('');
    })
    .join(' ');
}

// C1: 'exhaustive' is the original ladder (kept verbatim, deliberately -- see
// LadderMode's doc comment) -- n(n-1)/2 windows, every increasing-size window
// ending at each position. 'cumulative' (forward chaining, the new default)
// only re-verifies growing prefixes: 1-2, 1-3, ..., 1-n -- n-1 windows. It
// skips re-verifying sub-spans the learner already produced correctly inside
// a longer span; findAllCulpritChunks/remediation is what catches genuine
// weak spots, and targets better than exhaustive re-verification does.
export function buildCombineSequence(
  n: number,
  mode: LadderMode = 'cumulative'
): CombineSequenceItem[] {
  if (mode === 'exhaustive') {
    const seq: CombineSequenceItem[] = [];
    for (let e = 2; e <= n; e++) {
      for (let s = 2; s <= e; s++) {
        seq.push({ start: e - s + 1, end: e });
      }
    }
    return seq;
  }

  const seq: CombineSequenceItem[] = [];
  for (let e = 2; e <= n; e++) {
    seq.push({ start: 1, end: e });
  }
  return seq;
}

// C1: how many consecutive blind successes a given combine window needs.
// Only applies under ladderMode 'cumulative' -- 'exhaustive' keeps requiring
// encodeReps uniformly on every window (see applyAnswer's combine branch),
// so the trial-count comparison between modes isn't itself muddied by this
// rule. Intermediate windows (end < n) just need 1: the learner already
// proved they can produce this growing prefix once, and the FINAL window
// (end === n, the whole answer) is what needs to be solid, so it alone
// requires the full encodeReps streak.
export function requiredRepsForWindow(
  seqItem: CombineSequenceItem,
  n: number,
  encodeReps: number
): number {
  return seqItem.end >= n ? encodeReps : 1;
}

export function splitInHalf(text: string): [string, string] {
  const words = text.split(' ');
  const mid = Math.ceil(words.length / 2);
  return [words.slice(0, mid).join(' '), words.slice(mid).join(' ')];
}

export function culpritHalf(typed: string, left: string, right: string, strict: boolean = false): string {
  const typedWords = typed.trim().length ? typed.trim().split(/\s+/) : [];
  const leftWordCount = left.split(' ').length;
  const leftTyped = typedWords.slice(0, leftWordCount).join(' ');
  if (!exactMatch(leftTyped, left, strict)) return left;
  return right;
}

// B1 fix: attribute mismatches to chunks using the LCS alignment computeWordDiff
// already builds (order-preserving subsequence match against the combined
// target), instead of slicing typedWords by cumulative chunk word-counts. The
// old positional approach misfired catastrophically: a single dropped word
// anywhere before the end shifted every subsequent chunk's slice, so nearly
// any miss flagged the entire window for remediation regardless of where the
// actual mistake was.
export function findAllCulpritChunks(
  typed: string,
  chunks: string[],
  startIdx: number,
  endIdx: number,
  strict: boolean = false
): number[] {
  const combinedTarget = chunks.slice(startIdx, endIdx + 1).join(' ');
  const diff = computeWordDiff(typed, combinedTarget, strict);

  const culprits: number[] = [];
  let wordCursor = 0;
  for (let idx = startIdx; idx <= endIdx; idx++) {
    const chunkWordCount = chunks[idx].split(' ').length;
    const chunkDiff = diff.slice(wordCursor, wordCursor + chunkWordCount);
    if (chunkDiff.some(d => !d.matched)) {
      culprits.push(idx);
    }
    wordCursor += chunkWordCount;
  }

  if (culprits.length === 0) {
    culprits.push(endIdx);
  }

  return culprits;
}

export function shuffle<T>(arr: T[]): T[] {
  const a = arr.slice();
  for (let i = a.length - 1; i > 0; i--) {
    const j = Math.floor(Math.random() * (i + 1));
    const tmp = a[i];
    a[i] = a[j];
    a[j] = tmp;
  }
  return a;
}

// C3: round-robins over `batch` (in whatever order the array is already in
// -- see shuffleWithinBatches), returning the next item whose status isn't
// 'ready' yet. lastItemId is the SESSION_COMPLETE_ID-style sentinel
// convention already used elsewhere in this file for "no previous item" --
// there's nothing special-cased for it: batch.findIndex simply never
// matches, so it falls through to "start from the front" the same as any
// other id that isn't in this batch (e.g. the previous batch's last item,
// right after advanceToNextBatch). Returns null once every item in the
// batch is 'ready' (batch fully encoded -> time for its cycle phase).
// 'mastered' items are skipped too: on the normal path no batch item can be
// mastered during encode, but editCurrentItem can send one card of a batch
// that's mid-cycle back to encoding, and its mastered batch-mates must not
// be re-encoded along with it.
export function selectNextEncodeItem(batch: DrillItem[], lastItemId: number): DrillItem | null {
  const needsEncoding = (i: DrillItem) => i.status !== 'ready' && i.status !== 'mastered';
  const pending = batch.filter(needsEncoding);
  if (!pending.length) return null;

  const lastIdx = batch.findIndex(i => i.id === lastItemId);
  if (lastIdx === -1) return pending[0];

  for (let step = 1; step <= batch.length; step++) {
    const candidate = batch[(lastIdx + step) % batch.length];
    if (needsEncoding(candidate)) return candidate;
  }
  return null; // unreachable: pending.length > 0 guarantees a hit above
}

export function slugify(name: string): string {
  const s = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || 'deck';
}

// C3: batch membership is a contiguous deck-order slice (doc: "Partition
// items into batches in deck order"), but every item's actual array
// position still comes from this function -- so the ONE place that needs to
// shuffle "trial order within a batch" (doc's other requirement) is here,
// once, at construction. partitionIntoBatches and selectNextEncodeItem then
// just walk whatever order the array already has; nothing re-shuffles a
// batch mid-session. size <= 0 or >= items.length collapses to a single
// "whole deck" batch, which still gets this same shuffle -- "whole deck"
// only means no interstitial checkpoint, not a return to pre-C3 fully-massed
// (unshuffled, one-item-at-a-time) presentation; that's selectNextEncodeItem's
// round-robin, which applies regardless of batch size.
// NOTE: the app itself now opts out (buildItems' shuffleWithinBatch=false),
// so a live session encodes each batch in deck order starting at its first
// card. The shuffle remains the default for the harness/LegacyEngine/tests.
function shuffleWithinBatches<T>(items: T[], batchSize?: number): T[] {
  const size = batchSize && batchSize > 0 ? batchSize : items.length;
  const result: T[] = [];
  for (let i = 0; i < items.length; i += size) {
    result.push(...shuffle(items.slice(i, i + size)));
  }
  return result;
}

// C3: batch membership only, in the array's current order -- does not
// itself shuffle (see shuffleWithinBatches). size <= 0 or >= items.length
// yields a single "whole deck" batch.
export function partitionIntoBatches<T>(items: T[], batchSize?: number): T[][] {
  const size = batchSize && batchSize > 0 ? batchSize : items.length;
  if (!items.length) return [];
  const batches: T[][] = [];
  for (let i = 0; i < items.length; i += size) {
    batches.push(items.slice(i, i + size));
  }
  return batches;
}

export function buildItems(
  parsed: DeckItem[],
  chunkPercent: number = 35,
  ladderMode: LadderMode = 'cumulative',
  batchSize?: number,
  minWordsToChunk: number = MIN_WORDS_TO_CHUNK,
  // false = keep deck order within each batch, so encoding starts at the
  // first card as written and round-robins 1, 2, 3... (what the app uses).
  // Defaults to true so every existing caller -- the frozen LegacyEngine,
  // the seeded simulate() harness, and the tests -- keeps the exact
  // behavior (and PRNG draw sequence) its measurements were taken under.
  shuffleWithinBatch: boolean = true
): DrillItem[] {
  const items: DrillItem[] = parsed.map((p, i) => buildItem(p, i, chunkPercent, ladderMode, minWordsToChunk));
  return shuffleWithinBatch ? shuffleWithinBatches(items, batchSize) : items;
}

// One fresh item (status 'new', no progress) for a card. Shared by
// buildItems and editCurrentItem's restart path, so a restarted card is
// exactly what a new session would have built for it.
function buildItem(
  p: DeckItem,
  id: number,
  chunkPercent: number,
  ladderMode: LadderMode,
  minWordsToChunk: number
): DrillItem {
  const chunks = chunkText(p.back, chunkPercent, minWordsToChunk);
  return {
    id,
    front: p.front,
    back: p.back,
    extra: p.extra,
    status: 'new',
    encodeStreak: 0,
    cycleStreak: 0,
    chunks,
    chunkIndex: 0,
    chunkStreak: 0,
    combineSeq: chunks ? buildCombineSequence(chunks.length, ladderMode) : null,
    combineSeqIdx: 0,
    combineStreak: 0,
    combineMissCount: 0,
    remediateStack: [],
    remediateQueue: [],
    remediateReturnSeqIdx: 0,
    stage: chunks ? 'chunks' : 'full',
  };
}

export function normalizeItem(it: any, ladderMode: LadderMode = 'cumulative'): DrillItem {
  const item: DrillItem = {
    id: it.id,
    front: it.front,
    back: it.back,
    extra: it.extra,
    status: it.status || 'new',
    encodeStreak: it.encodeStreak ?? 0,
    cycleStreak: it.cycleStreak ?? 0,
    chunks: it.chunks || null,
    chunkIndex: it.chunkIndex ?? 0,
    chunkStreak: it.chunkStreak ?? 0,
    combineSeq: it.combineSeq || (it.chunks ? buildCombineSequence(it.chunks.length, ladderMode) : null),
    combineSeqIdx: it.combineSeqIdx ?? 0,
    combineStreak: it.combineStreak ?? 0,
    combineMissCount: it.combineMissCount ?? 0,
    remediateStack: it.remediateStack || [],
    remediateQueue: it.remediateQueue || [],
    remediateReturnSeqIdx: it.remediateReturnSeqIdx ?? 0,
    stage: it.stage || (it.chunks ? 'chunks' : 'full'),
  };

  if (item.status === 'encoding' && item.stage === 'remediate' && !item.remediateStack.length) {
    item.stage = item.chunks ? 'chunks' : 'full';
    item.chunkIndex = 0;
    item.chunkStreak = 0;
  }

  // C8a: chunkStreak's valid range for stage 'chunks' shrank to {0, 1} -- a
  // blind success now always advances chunkIndex and resets it immediately,
  // so it never legitimately grows past 1 anymore. A save from before C8a
  // can have chunkStreak up to encodeReps-1 for an item stopped mid-chunk;
  // clamp it down to 1 (interpreted as "already past the cued attempt, one
  // blind success away") rather than leave a magnitude the new comparison
  // (`chunkStreak === 0`) never produced on its own.
  if (item.stage === 'chunks' && item.chunkStreak > 1) {
    item.chunkStreak = 1;
  }

  return item;
}

// C3: migration for a SavedSessionState written before this phase (or one
// that never left batch 0) -- doc: "a saved state with no batchIndex is
// treated as batchIndex: 0, batchSize: items.length". Lives here rather
// than inside normalizeItem since batching is session-scoped, not
// per-item -- callers use this once when reconstructing SessionState from
// a resumed save (see App.tsx's handleResumeSession).
export function resolveBatchConfig(
  saved: Pick<SavedSessionState, 'batchIndex' | 'batchSize'>,
  items: DrillItem[]
): { batchIndex: number; batchSize: number } {
  return {
    batchIndex: saved.batchIndex ?? 0,
    batchSize: saved.batchSize ?? items.length,
  };
}

// Resumed session's write-back permission. A save with no recorded source
// (written before sourceDeckEditable existed) can't be told apart from a
// folder-practice save, so it's treated as session-only.
export function resolveSourceDeckEditable(saved: Pick<SavedSessionState, 'sourceDeckEditable'>): boolean {
  return saved.sourceDeckEditable ?? false;
}

// Writes a mid-session card edit back to the saved deck named deckName, but
// only if the session has a single source deck, that deck exists, and the
// card at the item's index still reads exactly as it did before the edit
// (DrillItem.id is the card's index in the deck as parsed). folderId and
// strictPunctuation are left undefined so the deck keeps its own. Returns
// the updated deck, or null if nothing was written.
export function writeBackCardEdit(
  deckName: string,
  sourceDeckEditable: boolean,
  before: Pick<DrillItem, 'id' | 'front' | 'back'>,
  after: Pick<DrillItem, 'front' | 'back' | 'extra'>
): DeckItem[] | null {
  if (!sourceDeckEditable || !deckName) return null;
  const deck = getDeckFromStorage(slugify(deckName));
  const card = deck?.[before.id];
  if (!deck || !card || card.front !== before.front || card.back !== before.back) return null;
  const updated = deck.map((c, idx) =>
    idx === before.id ? { front: after.front, back: after.back, extra: after.extra } : c
  );
  return saveDeckToStorage(deckName, updated) ? updated : null;
}

// LocalStorage helpers
export function lsGet<T>(key: string): T | null {
  try {
    const v = localStorage.getItem(key);
    return v ? JSON.parse(v) : null;
  } catch {
    return null;
  }
}

export function lsSet<T>(key: string, value: T): boolean {
  try {
    localStorage.setItem(key, JSON.stringify(value));
    return true;
  } catch {
    return false;
  }
}

export function lsDelete(key: string): boolean {
  try {
    localStorage.removeItem(key);
    return true;
  } catch {
    return false;
  }
}

export const PREMADE_DECKS_LIST: { name: string; slug: string }[] = [
  { name: 'Git Essentials', slug: 'git-essentials' },
  { name: 'Robert Frost: The Road Not Taken', slug: 'robert-frost-the-road-not-taken' },
  { name: 'Rapid World Capitals', slug: 'rapid-world-capitals' },
  { name: 'HTTP Status Codes', slug: 'http-status-codes' },
];

export function isPremadeDeck(slug?: string, name?: string): boolean {
  if (!slug && !name) return false;
  const s = (slug || '').toLowerCase().trim();
  const n = (name || '').toLowerCase().trim();
  const bannedKeywords = [
    'starter',
    'preset',
    'premade',
    'sample deck',
    'git essentials',
    'git-essentials',
    'robert frost',
    'road not taken',
    'world capitals',
    'http status',
    'http-status',
  ];
  if (bannedKeywords.some(kw => s.includes(kw) || n.includes(kw))) {
    return true;
  }
  return PREMADE_DECKS_LIST.some(
    p => p.slug === s || p.name.toLowerCase() === n || s.includes(p.slug)
  );
}

export function loadFolderIndex(): DeckFolder[] {
  return lsGet<DeckFolder[]>('deck-folders') || [];
}

export function saveFolderIndex(folders: DeckFolder[]): boolean {
  return lsSet('deck-folders', folders);
}

export function createFolder(name: string, parentId: string | null = null): DeckFolder {
  const folders = loadFolderIndex();
  const id = `folder_${Date.now()}_${Math.random().toString(36).substring(2, 7)}`;
  const now = new Date().toISOString();
  const newFolder: DeckFolder = {
    id,
    name: name.trim() || 'Untitled folder',
    parentId: parentId || null,
    createdAt: now,
    updatedAt: now,
  };
  folders.push(newFolder);
  saveFolderIndex(folders);
  return newFolder;
}

export function renameFolder(id: string, newName: string): boolean {
  const folders = loadFolderIndex();
  const folder = folders.find(f => f.id === id);
  if (!folder) return false;
  folder.name = newName.trim() || folder.name;
  folder.updatedAt = new Date().toISOString();
  return saveFolderIndex(folders);
}

export function getFolderDescendantIds(folderId: string, allFolders?: DeckFolder[]): string[] {
  const folders = allFolders || loadFolderIndex();
  const result: string[] = [];
  const queue = [folderId];

  while (queue.length > 0) {
    const current = queue.shift()!;
    const children = folders.filter(f => f.parentId === current);
    for (const child of children) {
      result.push(child.id);
      queue.push(child.id);
    }
  }

  return result;
}

export function moveFolder(id: string, newParentId: string | null): boolean {
  if (id === newParentId) return false;
  const folders = loadFolderIndex();
  const folder = folders.find(f => f.id === id);
  if (!folder) return false;

  // Prevent moving a folder into one of its descendants
  if (newParentId) {
    const descendants = getFolderDescendantIds(id, folders);
    if (descendants.includes(newParentId)) return false;
  }

  folder.parentId = newParentId || null;
  folder.updatedAt = new Date().toISOString();
  return saveFolderIndex(folders);
}

export function deleteFolder(id: string, deleteContents: boolean = true): boolean {
  const folders = loadFolderIndex();
  const descendantFolderIds = getFolderDescendantIds(id, folders);
  const allAffectedFolderIds = [id, ...descendantFolderIds];

  if (deleteContents) {
    // Delete all decks inside these folders
    const decks = loadDeckIndex();
    const decksToDelete = decks.filter(d => d.folderId && allAffectedFolderIds.includes(d.folderId));
    decksToDelete.forEach(d => {
      lsDelete(`deck:${d.slug}`);
      lsDelete(`session:${d.slug}`);
    });

    const remainingDecks = decks.filter(
      d => !d.folderId || !allAffectedFolderIds.includes(d.folderId)
    );
    lsSet('deck-index', remainingDecks);

    // Delete folder and all descendants
    const remainingFolders = folders.filter(f => !allAffectedFolderIds.includes(f.id));
    return saveFolderIndex(remainingFolders);
  } else {
    // Move contents to parent of deleted folder
    const targetFolder = folders.find(f => f.id === id);
    const parentId = targetFolder ? targetFolder.parentId : null;

    // Direct children folders get new parent
    folders.forEach(f => {
      if (f.parentId === id) {
        f.parentId = parentId;
      }
    });

    // Direct child decks get new parent
    const decks = loadDeckIndex();
    decks.forEach(d => {
      if (d.folderId === id) {
        d.folderId = parentId;
      }
    });
    lsSet('deck-index', decks);

    const remainingFolders = folders.filter(f => f.id !== id);
    return saveFolderIndex(remainingFolders);
  }
}

export function moveDeckToFolder(slug: string, folderId: string | null): boolean {
  const index = loadDeckIndex();
  const deck = index.find(d => d.slug === slug);
  if (!deck) return false;
  deck.folderId = folderId || null;
  deck.updatedAt = new Date().toISOString();
  return lsSet('deck-index', index);
}

export function moveMultipleDecksToFolder(slugs: string[], folderId: string | null): boolean {
  if (slugs.length === 0) return true;
  const index = loadDeckIndex();
  const slugSet = new Set(slugs);
  const now = new Date().toISOString();
  let changed = false;
  for (const deck of index) {
    if (slugSet.has(deck.slug)) {
      deck.folderId = folderId || null;
      deck.updatedAt = now;
      changed = true;
    }
  }
  return changed ? lsSet('deck-index', index) : true;
}

export function getFolderPath(folderId: string | null, allFolders?: DeckFolder[]): DeckFolder[] {
  if (!folderId) return [];
  const folders = allFolders || loadFolderIndex();
  const path: DeckFolder[] = [];
  let currentId: string | null = folderId;

  // Prevent infinite cycles
  const seen = new Set<string>();
  while (currentId && !seen.has(currentId)) {
    seen.add(currentId);
    const folder = folders.find(f => f.id === currentId);
    if (!folder) break;
    path.unshift(folder);
    currentId = folder.parentId;
  }

  return path;
}

export function getFolderFullPath(folderId: string | null, allFolders?: DeckFolder[]): string {
  if (!folderId) return 'All Decks';
  const path = getFolderPath(folderId, allFolders);
  if (path.length === 0) return 'All Decks';
  return path.map(p => p.name).join(' / ');
}

export function getAllCardsInFolderTree(folderId: string | null): DeckItem[] {
  const decks = loadDeckIndex();
  let matchingDecks: SavedDeckEntry[] = [];

  if (folderId === null) {
    matchingDecks = decks;
  } else {
    const descendantIds = [folderId, ...getFolderDescendantIds(folderId)];
    matchingDecks = decks.filter(d => d.folderId && descendantIds.includes(d.folderId));
  }

  const allCards: DeckItem[] = [];
  for (const d of matchingDecks) {
    const items = getDeckFromStorage(d.slug);
    if (items) {
      allCards.push(...items);
    }
  }
  return allCards;
}

export function loadDeckIndex(): SavedDeckEntry[] {
  if (typeof window !== 'undefined' && window.localStorage) {
    try {
      const legacyKeys = [
        'starter-packs',
        'starter_packs',
        'starter-presets',
        'presets',
        'premade_decks',
        'recall_drill_premade',
        'sample-decks',
      ];
      legacyKeys.forEach(k => localStorage.removeItem(k));
    } catch {
      // ignore
    }
  }

  const index = lsGet<SavedDeckEntry[]>('deck-index') || [];
  const filtered = index.filter(d => !isPremadeDeck(d.slug, d.name));
  if (filtered.length !== index.length) {
    lsSet('deck-index', filtered);
    index.forEach(d => {
      if (isPremadeDeck(d.slug, d.name)) {
        lsDelete(`deck:${d.slug}`);
        lsDelete(`session:${d.slug}`);
      }
    });
  }
  PREMADE_DECKS_LIST.forEach(p => {
    lsDelete(`deck:${p.slug}`);
    lsDelete(`session:${p.slug}`);
  });
  return filtered;
}

export function saveDeckToStorage(
  name: string,
  items: DeckItem[],
  folderId?: string | null,
  strictPunctuation?: boolean
): boolean {
  const slug = slugify(name);
  const ok = lsSet(`deck:${slug}`, items);
  if (!ok) return false;

  const index = loadDeckIndex();
  const existingIdx = index.findIndex(e => e.slug === slug);
  const now = new Date().toISOString();

  // Resolve folderId: if undefined and existing deck exists, preserve existing folderId
  const finalFolderId =
    folderId !== undefined
      ? folderId || null
      : existingIdx >= 0
      ? index[existingIdx].folderId || null
      : null;

  // Phase 2: same preserve-if-unspecified pattern as folderId above --
  // undefined keeps the existing deck's setting (or false for a new deck).
  const finalStrictPunctuation =
    strictPunctuation !== undefined
      ? strictPunctuation
      : existingIdx >= 0
      ? index[existingIdx].strictPunctuation ?? false
      : false;

  const entry: SavedDeckEntry = {
    slug,
    name,
    count: items.length,
    folderId: finalFolderId,
    updatedAt: now,
    lastUsedAt: now,
    strictPunctuation: finalStrictPunctuation,
  };

  if (existingIdx >= 0) {
    index[existingIdx] = entry;
  } else {
    index.push(entry);
  }

  lsSet('deck-index', index);
  return true;
}

export function recordDeckUsed(slug: string, name?: string, count?: number): void {
  if (!slug) return;
  const index = loadDeckIndex();
  const existingIdx = index.findIndex(e => e.slug === slug);
  const now = new Date().toISOString();
  if (existingIdx >= 0) {
    index[existingIdx].lastUsedAt = now;
    lsSet('deck-index', index);
  } else if (name) {
    index.push({
      slug,
      name,
      count: count ?? 0,
      updatedAt: now,
      lastUsedAt: now,
    });
    lsSet('deck-index', index);
  }
}

// True if this deck-index entry has an actual deck:<slug> payload behind
// it. A stale index entry can lack one -- recordDeckUsed's "no existing
// entry" branch created one for a folder-practice session before App.tsx
// guarded against it, since a folder has no single deck to save. Filter any
// deck list the UI lets someone open or practice through this so an
// already-existing phantom entry (from before that guard) doesn't render
// as a dead 0-card deck; re-checked on every read rather than deleted once,
// so it self-heals even across an export/import round-trip.
export function deckHasPayload(entry: SavedDeckEntry): boolean {
  return getDeckFromStorage(entry.slug) !== null;
}

export function getRecentlyUsedDecks(): SavedDeckEntry[] {
  const index = loadDeckIndex();
  return index
    .filter(d => !isPremadeDeck(d.slug, d.name) && deckHasPayload(d))
    .sort((a, b) => {
      const timeA = new Date(a.lastUsedAt || a.updatedAt || 0).getTime();
      const timeB = new Date(b.lastUsedAt || b.updatedAt || 0).getTime();
      return timeB - timeA;
    });
}

export function deleteDeckFromStorage(slug: string): boolean {
  lsDelete(`deck:${slug}`);
  lsDelete(`session:${slug}`);
  const index = loadDeckIndex();
  const next = index.filter(e => e.slug !== slug);
  lsSet('deck-index', next);
  return true;
}

export function getDeckFromStorage(slug: string): DeckItem[] | null {
  return lsGet<DeckItem[]>(`deck:${slug}`);
}

export function getSessionState(slug: string): SavedSessionState | null {
  return lsGet<SavedSessionState>(`session:${slug}`);
}

export function saveSessionState(slug: string, state: SavedSessionState): boolean {
  return lsSet(`session:${slug}`, state);
}

export function clearSessionState(slug: string): boolean {
  return lsDelete(`session:${slug}`);
}

// ---------------------------------------------------------------------------
// Phase 0 extraction: pure session state machine (selectTrial / applyAnswer /
// applyNext / initSession). Transcribed verbatim from src/components/
// SessionView.tsx's handleCheck/advanceEncode/advanceCycle -- no behavior
// changes, including known bugs B1 (findAllCulpritChunks positional misfire)
// and B2 (a revealed answer is never read by grading). Do not fix those here;
// they ship as Phase 1.
//
// currentId: -1 is the sentinel selectTrial uses to signal "session complete"
// (buildItems' ids start at 0, so -1 never collides with a real item).
// ---------------------------------------------------------------------------

export const SESSION_COMPLETE_ID = -1;

// One key per distinct setTimeout call site in the original handleCheck (17
// total: 3 chunks + 5 combine + 6 remediate + 3 full; cycle phase never uses
// a timeout -- it always waits for an explicit "Continue"/Enter action).
// 'revealed-reset' is new in Phase 1 (B2 fix): not pinned by the handoff doc,
// chosen to sit between the 500ms streak-progress dwell and the miss dwells
// since it's informational, not punitive.
// 'near-miss' is new in Phase 2 (C2): the doc pins this at ~1200ms.
// The six wrong-verdict dwells (*-miss, *-miss-retry, *-miss-split,
// combine-miss-remediate) were extended from their Phase 0 values (1600-1800)
// to 2200ms in Phase 2 (C2) so the "Count as correct" override had a window
// to be clickable in. Phase 4 (C5) made every wrong-verdict return
// `advance: 'manual'` instead, so these six keys are no longer consulted by
// any setTimeout -- the shell just waits for Enter/Next now, and the override
// stays reachable indefinitely rather than only within a dwell window. Left
// in the table rather than deleted: still meaningful as "how long this
// feedback would have shown" documentation, and DWELL_MS is a plain lookup
// table, not something worth special-casing per advance mode.
// 'chunks-cued-advance' was added in C8a (Phase 8) for the cued (attempt 0)
// success's "moved to blind, not advanced yet" feedback, then went dead one
// phase later in C8b (Phase 9): attempt 0 became an ungraded presentation
// (see 'chunks-presented' below), so there's no longer a *graded* cued
// success to show it for. 'chunks-streak-progress' has been dead since C8a
// for the same reason B2's six keys are dead -- chunks no longer has a
// "still accumulating, not there yet" state to show it in (chunkStreak only
// ever holds 0 or 1). Both left in the table for the same documentation
// reason as those six.
// 'chunks-presented' is new in C8b: the dwell for acknowledging a
// presentation trial (verdict 'presented') before the first blind attempt
// -- short, since there's no diff or streak-progress to read, just a
// transition.
export const DWELL_MS: Record<string, number> = {
  'chunks-advance': 700,
  'chunks-cued-advance': 500,
  'chunks-streak-progress': 500,
  'chunks-presented': 500,
  'chunks-miss': 2200,
  'combine-ready': 600,
  'combine-advance': 700,
  'combine-streak-progress': 500,
  'combine-miss-remediate': 2200,
  'combine-miss-retry': 2200,
  'remediate-next-spot': 900,
  'remediate-resume-combine': 700,
  'remediate-expand-parent': 1100,
  'remediate-streak-progress': 500,
  'remediate-miss-split': 2200,
  'remediate-miss-retry': 2200,
  'full-advance': 600,
  'full-streak-progress': 500,
  'full-miss': 2200,
  'revealed-reset': 1200,
  'near-miss': 1200,
};

// Builds one cycle-phase pass over `ids`. 'shuffled' (default) is the
// original random order; 'inOrder' is deck order -- DrillItem.id is the
// card's index in the deck as written (see buildItems), so sorting by id
// undoes buildItems' within-batch shuffle for the cycle phase only.
export function orderCycleQueue(ids: number[], cycleOrder: CycleOrder = 'shuffled'): number[] {
  return cycleOrder === 'inOrder' ? [...ids].sort((a, b) => a - b) : shuffle(ids);
}

// Reinserts a not-yet-mastered card into the current cycle pass `gap` cards
// ahead ('shuffled' mode). In 'inOrder' mode it does nothing: the card is
// still not mastered, so advanceCycleState picks it up again when it builds
// the next pass, and the current pass keeps its deck order intact.
function requeueCycleItem(queue: number[], id: number, gap: number, cycleOrder: CycleOrder = 'shuffled'): void {
  if (cycleOrder === 'inOrder') return;
  queue.splice(Math.min(gap, queue.length), 0, id);
}

// C3: this batch's items, in whatever order buildItems' one-time
// shuffleWithinBatches call left them in (see that function's comment) --
// partitionIntoBatches only slices, it never reorders.
function getCurrentBatch(items: DrillItem[], batchIndex: number, batchSize: number): DrillItem[] {
  return partitionIntoBatches(items, batchSize)[batchIndex] ?? [];
}

// C3: called after every completed stage-unit (one chunk learned, one
// combine window learned, one remediation span cleared -- see applyAnswer's
// call sites) as well as at session/batch start. Rotates within the current
// batch via selectNextEncodeItem instead of the old "always the first
// new/encoding item in deck order" (which was fully massed: item 0 to
// completion before item 1 was ever touched). Once every item in the batch
// is 'ready', starts that batch's cycle phase, scoped to just its items.
function advanceEncodeState(
  items: DrillItem[],
  stats: SessionStats,
  base: SessionState
): SessionState {
  const batch = getCurrentBatch(items, base.batchIndex, base.config.batchSize ?? items.length);
  const next = selectNextEncodeItem(batch, base.currentId);

  if (!next) {
    // Non-mastered only: after an editCurrentItem restart mid-cycle, the
    // batch's already-mastered cards must not be served again. On the normal
    // path nothing in the batch is mastered yet, so this is every item.
    const batchQueue = orderCycleQueue(
      batch.filter(i => i.status !== 'mastered').map(i => i.id),
      base.config.cycleOrder
    );
    return advanceCycleState(items, batchQueue, stats, {
      ...base,
      items,
      phase: 'cycle',
      queue: batchQueue,
      stats,
    });
  }

  const newItems = items.map(i =>
    i.id === next.id && i.status === 'new' ? { ...i, status: 'encoding' as const } : i
  );
  return { ...base, items: newItems, phase: 'encode', currentId: next.id, stats };
}

// C3: once every item in the CURRENT batch is mastered, either moves to the
// next batch's interstitial (phase 'batch-done' -- SessionView shows the
// summary and waits for "Next batch"/"Save and stop"; see advanceToNextBatch)
// or, if this was the last batch, ends the session the same way a
// non-batched (whole-deck) session always did.
function advanceBatchState(items: DrillItem[], stats: SessionStats, base: SessionState): SessionState {
  const totalBatches = partitionIntoBatches(items, base.config.batchSize ?? items.length).length;
  if (base.batchIndex + 1 >= totalBatches) {
    return { ...base, items, phase: 'cycle', queue: [], stats, currentId: SESSION_COMPLETE_ID };
  }
  // currentId is deliberately left as-is (not SESSION_COMPLETE_ID): that
  // sentinel means "the whole session is done" to SessionView's finishing
  // effect, and more batches remain here. selectTrial short-circuits on
  // phase 'batch-done' before ever looking currentId up.
  return { ...base, items, phase: 'batch-done', queue: [], stats };
}

function advanceCycleState(
  items: DrillItem[],
  currentQueue: number[],
  stats: SessionStats,
  base: SessionState
): SessionState {
  let q = [...currentQueue];
  if (!q.length) {
    // C3: scoped to the current batch, not the whole deck -- each batch runs
    // its own cycle phase to mastery before the next batch's encode phase
    // starts. A non-batched (whole-deck) session is just the batchSize>=
    // items.length degenerate case of the same code path.
    const batch = getCurrentBatch(items, base.batchIndex, base.config.batchSize ?? items.length);
    const remaining = batch.filter(i => i.status !== 'mastered');
    if (!remaining.length) {
      return advanceBatchState(items, stats, base);
    }
    q = orderCycleQueue(remaining.map(i => i.id), base.config.cycleOrder);
  }

  const nextId = q.shift()!;
  return { ...base, items, phase: 'cycle', queue: q, stats, currentId: nextId };
}

// C3: advances batchIndex and starts the new batch's encode phase. Called
// when the learner clicks "Next batch" on the interstitial (phase
// 'batch-done'). currentId is reset to SESSION_COMPLETE_ID first purely as
// "no previous item" input to selectNextEncodeItem's round-robin (the new
// batch's items never contain that id, so it falls through to "start from
// the front" the same as any id from a different batch would).
export function advanceToNextBatch(state: SessionState): SessionState {
  const resetState: SessionState = {
    ...state,
    batchIndex: state.batchIndex + 1,
    batchStartStats: { ...state.stats },
    phase: 'encode',
    currentId: SESSION_COMPLETE_ID,
  };
  return advanceEncodeState(state.items, state.stats, resetState);
}

// C3: batch-level summary for the interstitial (items mastered, trials
// spent, accuracy) -- diffs `stats` against the snapshot captured when this
// batch began (batchStartStats) rather than tracking a second running
// total. batchNumber/totalBatches are 1-indexed for display.
export function computeBatchSummary(state: SessionState): {
  batchNumber: number;
  totalBatches: number;
  itemsMastered: number;
  batchSize: number;
  trialsSpent: number;
  accuracyPercent: number;
} {
  const effectiveBatchSize = state.config.batchSize ?? state.items.length;
  const batches = partitionIntoBatches(state.items, effectiveBatchSize);
  const batch = batches[state.batchIndex] ?? [];
  const trialsSpent = state.stats.attempts - state.batchStartStats.attempts;
  const missesInBatch = state.stats.misses - state.batchStartStats.misses;
  const accuracyPercent =
    trialsSpent > 0 ? Math.round(((trialsSpent - missesInBatch) / trialsSpent) * 100) : 100;

  return {
    batchNumber: state.batchIndex + 1,
    totalBatches: batches.length,
    itemsMastered: batch.filter(i => i.status === 'mastered').length,
    batchSize: batch.length,
    trialsSpent,
    accuracyPercent,
  };
}

// ---------------------------------------------------------------------------
// Cold-start time estimate: a floor/ceiling range shown on the setup screen
// before a session starts, then recalibrated from the learner's own
// measured pace at every batch interstitial. Every function below is called
// from SetupView (setup screen) or SessionView's batch interstitial only --
// never from selectTrial/applyAnswer -- so none of this touches the
// per-trial hot path.
//
// Precedence for which multiplier feeds the range: a fresh in-session
// recalibration (computeCumulativeColdStartMultiplier) beats this deck's
// saved personal history (getColdStartHistory), which beats the
// exposure-level self-rating seed (COLD_START_MULTIPLIERS). The three tiers
// are consumed at different times -- before a session starts vs.
// mid-session -- so nothing here enforces the ordering centrally; SetupView
// and SessionView each apply it at their own call site.
// ---------------------------------------------------------------------------

export type ExposureLevel = 'fresh' | 'once' | 'familiar';
export type ColdStartDeckShape = 'chunked' | 'full';

// Seed multipliers: ceiling = floor (perfect-run trial count) x this value.
// Derived from docs/BASELINE.md's Part 4 harness table (test/simulate.ts,
// test/simulate.report.ts -- 50 seeded runs per (deck, learner) config):
//
//   chunked deck -- proseDeck (12 prose cards, chunkDifficulty 35%, avg 3
//   chunks/card), perfect-learner floor 144.0 trials:
//     fresh = struggling/perfect = 762.7 / 144.0 = 5.30
//     once  = realistic/perfect  = 257.9 / 144.0 = 1.79 -> 1.8
//
//   full-stage deck -- shortDeck + mediumDeck averaged (both unchunked,
//   backs <= MIN_WORDS_TO_CHUNK words), perfect-learner floor 60.0 trials
//   each:
//     fresh = struggling/perfect = ((147.7 + 149.4) / 2) / 60.0 = 2.48 -> 2.5
//     once  = realistic/perfect  = (( 91.6 +  92.0) / 2) / 60.0 = 1.53 -> 1.5
//
// The harness models only three learner tiers (perfect/realistic/
// struggling) -- there's no fourth "practiced but not yet perfect" tier to
// measure `familiar` from directly, so it's set as the midpoint between
// `once` and the perfect learner's own ratio of 1.0
// (1 + (once - 1) / 2, rounded to 1 decimal): 1.4 and 1.2 respectively. If
// the harness ever grows a fourth tier, re-derive `familiar` from it
// directly instead of this interpolation.
export const COLD_START_MULTIPLIERS: Record<ColdStartDeckShape, Record<ExposureLevel, number>> = {
  chunked: { fresh: 5.3, once: 1.8, familiar: 1.4 },
  full: { fresh: 2.5, once: 1.5, familiar: 1.2 },
};

// Picks the multiplier row by the deck's actual composition -- share of
// cards whose back exceeds MIN_WORDS_TO_CHUNK -- never by a user setting
// like chunkDifficulty (a deck's shape doesn't change just because the
// difficulty slider moved).
export function pickColdStartDeckShape(items: DeckItem[]): ColdStartDeckShape {
  if (!items.length) return 'full';
  const chunkableCount = items.filter(
    it => it.back.trim().split(/\s+/).filter(Boolean).length > MIN_WORDS_TO_CHUNK
  ).length;
  return chunkableCount / items.length > 0.5 ? 'chunked' : 'full';
}

// Floor of the estimate: the minimum possible value of state.stats.attempts
// (the same counter SessionView's status bar shows as "Attempts") assuming
// a perfect learner (every graded attempt correct first try). Deliberately
// NOT the same as test/simulate.ts's `totalTrials` -- that harness counter
// also counts a chunks-stage presentation (C8b: cue 'present', attempt 0 of
// a chunk) as a trial, but applyAnswer's isPresentation branch skips
// incrementing `attempts` for it (nothing was graded), so it must be
// excluded here too for computeCumulativeColdStartMultiplier's actual/floor
// ratio to land on 1.0 for a perfect learner. Cross-checked against
// docs/BASELINE.md's perfect-learner rows once that gap is accounted for:
// shortDeck/mediumDeck don't chunk at all, so their floor (60) matches
// BASELINE.md's total trials exactly; proseDeck's floor is 108, i.e.
// BASELINE.md's 144 minus one presentation per chunk (3 chunks/card x 12
// cards = 36, never repeated for a perfect learner since presentations
// only recur after a miss).
//
// Every item needs exactly 2 cycle-phase trials to reach `mastered`
// (cycleStreak >= 2, and a perfect learner's streak only ever goes up);
// chunked items additionally need exactly 1 graded (blind) trial per chunk
// (C8a's cued attempt 0 is the presentation excluded above) plus the
// combine ladder's cost (see requiredRepsForWindow); unchunked items just
// need `encodeReps` on their single ladder rung.
export function computeMinimumTrials(
  items: DrillItem[],
  encodeReps: number,
  ladderMode: LadderMode = 'cumulative'
): number {
  let total = 0;
  for (const item of items) {
    if (item.chunks && item.combineSeq) {
      total += item.chunks.length;
      if (ladderMode === 'cumulative') {
        total += Math.max(0, item.combineSeq.length - 1) + encodeReps;
      } else {
        total += item.combineSeq.length * encodeReps;
      }
    } else {
      total += encodeReps;
    }
    total += 2;
  }
  return total;
}

// Tunables mirroring test/simulate.ts's wallClockEstimate constants,
// duplicated here (not imported) since that module is test-only -- not
// worth promoting the whole harness into production code for two numbers.
const COLD_START_TYPING_CPS = 4.5;
const COLD_START_PER_TRIAL_OVERHEAD_SEC = 1.5;

export function estimateColdStartSeconds(trials: number, items: { back: string }[]): number {
  const avgChars = items.length
    ? items.reduce((sum, it) => sum + it.back.length, 0) / items.length
    : 20;
  return trials * (avgChars / COLD_START_TYPING_CPS + COLD_START_PER_TRIAL_OVERHEAD_SEC);
}

function formatColdStartMinutes(seconds: number): string {
  const mins = seconds / 60;
  if (mins < 1) return '<1';
  return String(Math.round(mins));
}

// Shared by SetupView's estimate and SessionView's recalibrated interstitial
// range -- collapses the two degenerate cases a plain "~{floor}-{ceiling}
// min" template mishandles: both ends under a minute (was rendering the
// useless "~<1-<1 min") and ends that round to the same minute value, e.g.
// a multiplier of 1 (was rendering the equally useless "~12-12 min").
export function formatColdStartRange(floorSeconds: number, ceilingSeconds: number): string {
  const low = formatColdStartMinutes(floorSeconds);
  const high = formatColdStartMinutes(ceilingSeconds);
  if (low === '<1' && high === '<1') return 'under a minute';
  if (low === high) return `~${low} min`;
  return `~${low}–${high} min`;
}

export interface ColdStartEstimate {
  floorTrials: number;
  ceilingTrials: number;
  floorSeconds: number;
  ceilingSeconds: number;
  multiplier: number;
  deckShape: ColdStartDeckShape;
}

// Setup-screen estimate: floor from perfect-run math, ceiling = floor x the
// resolved multiplier (a personal-history override when one exists,
// otherwise the exposure-level seed row -- see COLD_START_MULTIPLIERS and
// getColdStartHistory below).
export function computeColdStartEstimate(
  deckItems: DeckItem[],
  encodeReps: number,
  chunkDifficulty: number,
  ladderMode: LadderMode,
  multiplierOverride: number | ExposureLevel
): ColdStartEstimate {
  const deckShape = pickColdStartDeckShape(deckItems);
  const built = buildItems(deckItems, chunkDifficulty, ladderMode);
  const floorTrials = computeMinimumTrials(built, encodeReps, ladderMode);
  const multiplier =
    typeof multiplierOverride === 'number'
      ? multiplierOverride
      : COLD_START_MULTIPLIERS[deckShape][multiplierOverride];
  const ceilingTrials = Math.round(floorTrials * multiplier);
  return {
    floorTrials,
    ceilingTrials,
    floorSeconds: estimateColdStartSeconds(floorTrials, deckItems),
    ceilingSeconds: estimateColdStartSeconds(ceilingTrials, deckItems),
    multiplier,
    deckShape,
  };
}

// Personal history: the multiplier measured from this deck's most recent
// session (see computeCumulativeColdStartMultiplier), one entry per deck
// slug. Read by SetupView the next time this deck is set up, in place of
// the exposure-picker seed -- see the module-level precedence note above.
export interface ColdStartHistory {
  multiplier: number;
  deckShape: ColdStartDeckShape;
  measuredAt: string;
}

export function getColdStartHistory(slug: string): ColdStartHistory | null {
  if (!slug) return null;
  return lsGet<ColdStartHistory>(`cold-start-history:${slug}`);
}

export function saveColdStartHistory(slug: string, history: ColdStartHistory): boolean {
  if (!slug) return false;
  return lsSet(`cold-start-history:${slug}`, history);
}

// In-session recalibration: this deck's actual trials / perfect-run minimum
// trials, summed across every batch FULLY completed so far this session --
// not just the batch most recently finished. A batch only ever completes in
// order (batchIndex only advances once every item in it is 'mastered'), so
// "completed" is exactly batches[0..batchIndex] when the batch AT
// batchIndex is itself fully mastered (true at the batch-done interstitial,
// and true of every batch once the whole session finishes, even though the
// last batch skips the interstitial -- see advanceBatchState), and
// batches[0..batchIndex-1] otherwise (mid-batch, e.g. the learner hits "End
// session" partway through). state.batchStartStats.attempts -- the
// attempts total as of the current batch's own start -- gives the attempts
// spent on those prior batches in the mid-batch case, since nothing else
// has touched `attempts` since; state.stats.attempts (the live running
// total) is only correct once the current batch is itself done, because at
// that instant no later batch has started consuming attempts yet.
//
// Returns null when no batch has been completed yet (nothing measured),
// rather than defaulting to a placeholder multiplier that would silently
// look like a real measurement to a caller that doesn't check for it.
//
// Called at every batch interstitial (SessionView renders the remaining
// range from this) and once more whenever a session ends (SessionView
// persists the result via saveColdStartHistory for future setup screens) --
// never mid-trial, so it stays out of the per-trial hot path either way.
export function computeCumulativeColdStartMultiplier(state: SessionState): number | null {
  const effectiveBatchSize = state.config.batchSize ?? state.items.length;
  const batches = partitionIntoBatches(state.items, effectiveBatchSize);
  const currentBatch = batches[state.batchIndex] ?? [];
  const currentBatchDone = currentBatch.length > 0 && currentBatch.every(it => it.status === 'mastered');
  const completedThroughIdx = currentBatchDone ? state.batchIndex : state.batchIndex - 1;
  if (completedThroughIdx < 0) return null;

  const completedItems = batches.slice(0, completedThroughIdx + 1).flat();
  const minTrials = computeMinimumTrials(completedItems, state.config.encodeReps, state.config.ladderMode);
  const completedAttempts = currentBatchDone ? state.stats.attempts : state.batchStartStats.attempts;
  return minTrials > 0 ? completedAttempts / minTrials : null;
}

// Recomputes the floor/ceiling range for whatever batches remain after the
// one currently shown on the interstitial, using a caller-supplied
// multiplier (the recalibrated one, once available).
export function computeRemainingColdStartRange(
  state: SessionState,
  multiplier: number
): { floorTrials: number; ceilingTrials: number; floorSeconds: number; ceilingSeconds: number } {
  const effectiveBatchSize = state.config.batchSize ?? state.items.length;
  const batches = partitionIntoBatches(state.items, effectiveBatchSize);
  const remainingItems = batches.slice(state.batchIndex + 1).flat();
  const floorTrials = computeMinimumTrials(remainingItems, state.config.encodeReps, state.config.ladderMode);
  const ceilingTrials = Math.round(floorTrials * multiplier);
  return {
    floorTrials,
    ceilingTrials,
    floorSeconds: estimateColdStartSeconds(floorTrials, remainingItems),
    ceilingSeconds: estimateColdStartSeconds(ceilingTrials, remainingItems),
  };
}

function clamp01(n: number): number {
  return Math.max(0, Math.min(1, n));
}

// C4: 0..1 encoding progress for a single item, weighted per the doc: 'new'
// is 0, 'ready' is 0.7, 'mastered' is 1.0, and 'encoding' is the fraction of
// the item's own ladder completed, scaled into the 0-0.7 band (so crossing
// into 'ready' is always a visible jump, and 'mastered' always reads as
// "done", not just "encoded"). Deliberately approximate about the exact
// per-window rep requirement under the cumulative ladder (C1) -- this is a
// progress *estimate* for a UI bar, not a trial-count calculation; see
// requiredRepsForWindow's doc comment for why encodeReps is still the right
// denominator in the cases where a combine window's streak is ever actually
// observed above 0 (the final window, and every window under 'exhaustive').
export function computeItemProgress(item: DrillItem, encodeReps: number): number {
  if (item.status === 'mastered') return 1;
  if (item.status === 'ready') return 0.7;
  if (item.status === 'new') return 0;

  // status === 'encoding'
  if (!item.chunks) {
    // Unchunked ('full' stage, <=3 words or chunkDifficulty 100%): a single
    // ladder rung needing encodeReps.
    const frac = encodeReps > 0 ? clamp01(item.encodeStreak / encodeReps) : 0;
    return frac * 0.7;
  }

  const totalChunks = item.chunks.length;
  const totalWindows = item.combineSeq ? item.combineSeq.length : 0;
  const totalUnits = totalChunks + totalWindows;
  if (totalUnits === 0) return 0;

  let completedUnits: number;
  if (item.stage === 'chunks') {
    // C8a: a chunk always needs exactly 1 cued + 1 blind correct answer
    // (chunkStreak only ever holds 0 or 1), independent of encodeReps --
    // so unlike combine/full below, this fraction's denominator is a fixed
    // 2, not encodeReps.
    const streakFrac = clamp01(item.chunkStreak / 2);
    completedUnits = item.chunkIndex + streakFrac;
  } else if (item.stage === 'combine') {
    const streakFrac = encodeReps > 0 ? clamp01(item.combineStreak / encodeReps) : 0;
    completedUnits = totalChunks + item.combineSeqIdx + streakFrac;
  } else {
    // 'remediate': a detour off the combine ladder to isolate a culprit
    // chunk -- combineSeqIdx doesn't move until it resolves, so progress
    // holds at the same window boundary it was at going in (never dips: a
    // combine miss already reset combineStreak to 0 before this stage was
    // entered, so completedUnits here exactly matches what it was the
    // instant before the miss).
    completedUnits = totalChunks + item.combineSeqIdx;
  }

  return clamp01(completedUnits / totalUnits) * 0.7;
}

// C4: deck-wide and batch-scoped progress in one call. `batch` defaults to
// `items` (matching the doc's 2-arg signature exactly -- "whole deck" is
// just the batchSize>=length degenerate case elsewhere in this file too),
// but SessionView passes the actual current batch's items as a 3rd arg so
// `batchFraction` reflects just that batch, not the whole deck.
export function computeSessionProgress(
  items: DrillItem[],
  encodeReps: number,
  batch: DrillItem[] = items
): {
  deckFraction: number;
  batchFraction: number;
  masteredCount: number;
  readyCount: number;
} {
  const average = (list: DrillItem[]): number =>
    list.length ? list.reduce((sum, it) => sum + computeItemProgress(it, encodeReps), 0) / list.length : 0;

  return {
    deckFraction: average(items),
    batchFraction: average(batch),
    masteredCount: items.filter(it => it.status === 'mastered').length,
    readyCount: items.filter(it => it.status === 'ready').length,
  };
}

// Equivalent of SessionView's mount useEffect: picks the first trial of a
// fresh or resumed session before any answer has been submitted.
export function initSession(state: SessionState): SessionState {
  // C3: a save made exactly at the interstitial ("Save and stop" on
  // 'batch-done') resumes straight back into it -- nothing to select.
  if (state.phase === 'batch-done') return state;
  if (state.phase === 'cycle') {
    return advanceCycleState(state.items, state.queue, state.stats, state);
  }
  return advanceEncodeState(state.items, state.stats, state);
}

export function selectTrial(state: SessionState): Trial | null {
  // C3: the interstitial has no trial -- SessionView renders the batch
  // summary instead of the card.
  if (state.phase === 'batch-done') return null;
  const it = state.items.find(i => i.id === state.currentId);
  if (!it) return null;

  // C5: attempt 0 of a stage-unit (streak 0) gets a firstLetter cue; attempt
  // 1+ (streak >= 1) is fully blind. The cycle phase never had a copy-typing
  // attempt to remove, so it stays fully blind unconditionally, as before.
  const cueForStreak = (streak: number, target: string): Cue =>
    streak >= 1 ? { kind: 'none' } : { kind: 'firstLetter', pattern: renderFirstLetterCue(target) };

  if (state.phase === 'cycle') {
    return {
      itemId: it.id,
      stage: 'cycle',
      prompt: it.front,
      target: it.back,
      cue: { kind: 'none' },
      label: 'Spaced Retrieval Cycle',
      detail: 'Spaced Retrieval • Cycling review',
    };
  }

  if (it.stage === 'chunks' && it.chunks) {
    const chunk = it.chunks[it.chunkIndex];
    // C8b: attempt 0 (chunkStreak 0) is a presentation, not a graded cued
    // typing attempt -- the chunk's full text is shown (via Trial.target,
    // same as every other cue), ungraded, and acknowledged with Enter/
    // Continue. Attempt 1+ is unchanged: fully blind.
    const chunkCue: Cue = it.chunkStreak === 0 ? { kind: 'present' } : { kind: 'none' };
    return {
      itemId: it.id,
      stage: 'chunks',
      prompt: it.front,
      target: chunk,
      cue: chunkCue,
      label: `Chunk Practice • ${it.chunkIndex + 1}/${it.chunks.length}`,
      detail: `Encoding • Part ${it.chunkIndex + 1} of ${it.chunks.length}`,
    };
  }

  if (it.stage === 'combine' && it.chunks && it.combineSeq) {
    const seqItem = it.combineSeq[it.combineSeqIdx];
    const combined = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
    return {
      itemId: it.id,
      stage: 'combine',
      prompt: it.front,
      target: combined,
      cue: cueForStreak(it.combineStreak, combined),
      label: 'Combination Practice',
      detail: `Encoding • Combining parts ${seqItem.start}-${seqItem.end} (${it.combineSeqIdx + 1}/${it.combineSeq.length})`,
    };
  }

  if (it.stage === 'remediate') {
    const rTop = it.remediateStack[it.remediateStack.length - 1];
    const rWordCount = rTop.text.split(' ').length;
    const queueSuffix =
      it.remediateQueue.length > 0
        ? ` (${it.remediateQueue.length} more spot${it.remediateQueue.length > 1 ? 's' : ''} after this)`
        : '';
    const detail =
      it.remediateStack.length > 1
        ? `Isolating exact spot • drilled down ${it.remediateStack.length - 1} level${
            it.remediateStack.length - 1 > 1 ? 's' : ''
          }, now on ${rWordCount} word${rWordCount === 1 ? '' : 's'}${queueSuffix}`
        : `Reinforcing this ${rWordCount}-word part before combining again${queueSuffix}`;
    return {
      itemId: it.id,
      stage: 'remediate',
      prompt: it.front,
      target: rTop.text,
      cue: cueForStreak(rTop.streak, rTop.text),
      label: 'Precision Repair',
      detail,
    };
  }

  // Stage: full (short phrase <= 3 words, or chunkDifficulty >= 100)
  return {
    itemId: it.id,
    stage: 'full',
    prompt: it.front,
    target: it.back,
    cue: cueForStreak(it.encodeStreak, it.back),
    label: 'Full Recall',
    detail: 'Encoding • Full item',
  };
}

export interface ApplyAnswerResult {
  state: SessionState;
  verdict: Verdict;
  feedback: Feedback;
  advance: 'auto' | 'manual';
}

export function applyAnswer(
  state: SessionState,
  typed: string,
  // override (C2): retroactively counts a still-pending wrong verdict as
  // exact. The shell implements this by re-calling applyAnswer with the
  // trial's own target text as `typed` (which always grades 'exact') and
  // override: true -- override only changes stats accounting below (no new
  // attempt, +1 to overrides instead), not the grading itself.
  opts: { revealed: boolean; override?: boolean }
): ApplyAnswerResult {
  const currentItem = state.items.find(i => i.id === state.currentId);
  if (!currentItem) {
    throw new Error('applyAnswer called with no current item');
  }

  const isOverride = opts.override === true;
  // C8b: a chunks-stage presentation trial (chunkStreak 0, cue 'present') --
  // nothing was graded, so it must not count as an attempt. !isOverride
  // guards the one case where chunkStreak legitimately reads 0 here despite
  // a real graded answer having just happened: overriding a wrong blind
  // attempt, whose miss already reset chunkStreak to 0 before the override
  // call -- that's a real (retroactively-exact) answer, not a presentation.
  const isPresentation =
    !isOverride &&
    state.phase === 'encode' &&
    currentItem.stage === 'chunks' &&
    currentItem.chunkStreak === 0;
  const nextStats: SessionStats = {
    ...state.stats,
    attempts: state.stats.attempts + (isOverride || isPresentation ? 0 : 1),
    overrides: state.stats.overrides + (isOverride ? 1 : 0),
  };
  const newItems = [...state.items];
  const itIdx = newItems.findIndex(i => i.id === currentItem.id);
  const it = { ...newItems[itIdx] };
  const base: SessionState = { ...state, stats: nextStats };

  if (isPresentation) {
    it.chunkStreak = 1;
    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems },
      verdict: 'presented',
      feedback: { text: 'Now try it from memory', type: 'info', dwellKey: 'chunks-presented' },
      advance: 'auto',
    };
  }

  // B2 fix: a revealed trial must not advance the streak and must not count
  // as a miss, regardless of what was typed (including typing the now-visible
  // answer correctly). Resets the current stage's streak to 0 and stays on
  // the same trial -- it never reaches the per-stage grading below.
  if (opts.revealed) {
    return applyRevealedAnswer(state, it, newItems, itIdx, base);
  }

  const gradeOpts = {
    lenient: true,
    stemTolerance: state.config.stemTolerance,
    strictPunctuation: state.config.strictPunctuation ?? false,
  };

  // C2: a near-miss verdict always shows the diff with a neutral note and the
  // 1200ms dwell, overriding whatever stage-specific success feedback/dwell
  // an exact match would have used -- the doc treats every near-miss
  // uniformly regardless of which transition it triggered.
  const successFeedback = (gr: GradeResult, defaultFeedback: Feedback): Feedback => {
    if (gr.verdict === 'near') {
      return { text: 'Close — compare the wording:', type: 'info', diff: gr.diff, dwellKey: 'near-miss' };
    }
    return defaultFeedback;
  };

  if (state.phase === 'encode') {
    if (it.stage === 'chunks' && it.chunks) {
      const targetChunk = it.chunks[it.chunkIndex];
      const gr = grade(typed, targetChunk, gradeOpts);
      const isOk = gr.verdict !== 'wrong';
      if (gr.verdict === 'near') nextStats.nearMisses++;

      if (isOk) {
        // C8a/C8b: the chunks stage's advance criterion is "one correct
        // answer at cue level 'none'" -- encodeReps no longer paces it
        // (unlike combine's final window and the full stage, which still
        // use it). By the time grading is reached here, chunkStreak is
        // always 1: the presentation short-circuit above (C8b) intercepts
        // every chunkStreak-0 attempt before grading, so any correct answer
        // that reaches this branch is necessarily the single blind attempt
        // (or an override retroactively counting one as correct) and
        // advances the chunk immediately, every time.
        it.chunkIndex++;
        it.chunkStreak = 0;
        let feedback: Feedback;
        if (it.chunkIndex >= it.chunks.length) {
          it.stage = 'combine';
          it.combineSeqIdx = 0;
          it.combineStreak = 0;
          feedback = successFeedback(gr, {
            text: 'All parts learned — now combining them',
            type: 'success',
            dwellKey: 'chunks-advance',
          });
        } else {
          feedback = successFeedback(gr, {
            text: 'Part learned!',
            type: 'success',
            dwellKey: 'chunks-advance',
          });
        }
        newItems[itIdx] = it;
        const advancedState = advanceEncodeState(newItems, nextStats, base);
        return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
      }

      nextStats.misses++;
      it.chunkStreak = 0;
      const feedback: Feedback = {
        text: 'Streak reset — compare your answer:',
        type: 'danger',
        diff: gr.diff,
        dwellKey: 'chunks-miss',
      };
      newItems[itIdx] = it;
      // C5: a wrong verdict now waits for an explicit advance (Enter/Next)
      // instead of an auto-advance timer, so the diff is actually read and
      // C2's "Count as correct" override stays reachable indefinitely rather
      // than only within a dwell window.
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'manual',
      };
    }

    if (it.stage === 'combine' && it.chunks && it.combineSeq) {
      const seqItem = it.combineSeq[it.combineSeqIdx];
      const combinedTarget = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
      const wasBlind = it.combineStreak >= 1;
      const gr = grade(typed, combinedTarget, gradeOpts);
      const isOk = gr.verdict !== 'wrong';
      if (gr.verdict === 'near') nextStats.nearMisses++;
      // C1: 'exhaustive' keeps the original uniform encodeReps-per-window
      // requirement (so the ladder-mode trial-count comparison stays
      // apples-to-apples); 'cumulative' needs only 1 on every window except
      // the final (whole-answer) one.
      const requiredReps =
        state.config.ladderMode === 'cumulative'
          ? requiredRepsForWindow(seqItem, it.chunks.length, state.config.encodeReps)
          : state.config.encodeReps;

      if (isOk) {
        it.combineStreak++;
        if (wasBlind) it.combineMissCount = 0;

        if (it.combineStreak >= requiredReps) {
          it.combineSeqIdx++;
          it.combineStreak = 0;
          let feedback: Feedback;
          if (it.combineSeqIdx >= it.combineSeq.length) {
            it.status = 'ready';
            feedback = successFeedback(gr, { text: 'Encoded!', type: 'success', dwellKey: 'combine-ready' });
          } else {
            feedback = successFeedback(gr, {
              text: 'Combination learned!',
              type: 'success',
              dwellKey: 'combine-advance',
            });
          }
          newItems[itIdx] = it;
          const advancedState = advanceEncodeState(newItems, nextStats, base);
          return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
        }
        const feedback = successFeedback(gr, {
          text: `${it.combineStreak} of ${requiredReps} streaks`,
          type: 'success',
          dwellKey: 'combine-streak-progress',
        });
        newItems[itIdx] = it;
        // Phase 2 (within-session spacing): a correct rep still short of
        // criterion now rotates to another batch card too, not just a
        // stage-unit completion -- the presentation beat -> blind attempt
        // pair stays adjacent (that's the combine window's own attempt 0/1,
        // not a rotation point), but repeated reps within the same window
        // are spread out across the batch instead of running back to back.
        const advancedState = advanceEncodeState(newItems, nextStats, base);
        return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
      }

      nextStats.misses++;
      it.combineStreak = 0;
      it.combineMissCount++;
      const windowChunkCount = seqItem.end - seqItem.start + 1;
      const missThreshold = windowChunkCount <= 2 ? 1 : 2;

      let feedback: Feedback;
      if (it.combineMissCount >= missThreshold) {
        const culprits = findAllCulpritChunks(
          typed,
          it.chunks,
          seqItem.start - 1,
          seqItem.end - 1,
          gradeOpts.strictPunctuation
        );
        it.remediateStack = [{ text: it.chunks[culprits[0]], streak: 0, missCount: 0 }];
        it.remediateQueue = culprits.slice(1).map(idx => it.chunks![idx]);
        it.remediateReturnSeqIdx = it.combineSeqIdx;
        it.combineMissCount = 0;
        it.stage = 'remediate';

        const spotWord = culprits.length > 1 ? 'spots' : 'part';
        const missMsg = missThreshold === 1 ? 'Missed it — isolating ' : 'Repeated miss — isolating ';
        feedback = {
          text: `${missMsg} ${culprits.length} trouble ${spotWord} to reinforce`,
          type: 'danger',
          dwellKey: 'combine-miss-remediate',
        };
      } else {
        feedback = {
          text: 'Streak reset — check the wording:',
          type: 'danger',
          diff: gr.diff,
          dwellKey: 'combine-miss-retry',
        };
      }
      newItems[itIdx] = it;
      // C5: manual advance on a wrong verdict (see the chunks-miss branch above).
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'manual',
      };
    }

    if (it.stage === 'remediate') {
      // Clone remediateStack/remediateQueue (and the RemediateItem objects
      // within) before mutating -- they're shared array/object references
      // with the input state's item until cloned, and applyAnswer must never
      // mutate its input.
      it.remediateStack = it.remediateStack.map(r => ({ ...r }));
      it.remediateQueue = [...it.remediateQueue];
      const rTop = it.remediateStack[it.remediateStack.length - 1];
      const gr = grade(typed, rTop.text, gradeOpts);
      const isOk = gr.verdict !== 'wrong';
      if (gr.verdict === 'near') nextStats.nearMisses++;

      if (isOk) {
        rTop.streak++;
        rTop.missCount = 0;
        if (rTop.streak >= state.config.encodeReps) {
          it.remediateStack.pop();
          if (it.remediateStack.length === 0) {
            if (it.remediateQueue.length > 0) {
              const nextPiece = it.remediateQueue.shift()!;
              it.remediateStack = [{ text: nextPiece, streak: 0, missCount: 0 }];
              const feedback = successFeedback(gr, {
                text: 'Trouble spot solid! Now checking the next spot',
                type: 'success',
                dwellKey: 'remediate-next-spot',
              });
              newItems[itIdx] = it;
              // C3: "one remediation span cleared" -- rotates to the next
              // unfinished item in the batch, same as every other
              // stage-unit completion below.
              const advancedState = advanceEncodeState(newItems, nextStats, base);
              return {
                state: advancedState,
                verdict: gr.verdict,
                feedback,
                advance: 'auto',
              };
            }
            it.stage = 'combine';
            it.combineSeqIdx = it.remediateReturnSeqIdx;
            it.combineStreak = 0;
            const feedback = successFeedback(gr, {
              text: 'Reinforced! Resuming progressive combining',
              type: 'success',
              dwellKey: 'remediate-resume-combine',
            });
            newItems[itIdx] = it;
            const advancedState = advanceEncodeState(newItems, nextStats, base);
            return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
          }
          const parentLevel = it.remediateStack[it.remediateStack.length - 1];
          parentLevel.streak = 0;
          const parentWordCount = parentLevel.text.split(' ').length;
          const feedback = successFeedback(gr, {
            text: `Isolated piece mastered — expanding to ${parentWordCount}-word parent`,
            type: 'success',
            dwellKey: 'remediate-expand-parent',
          });
          newItems[itIdx] = it;
          // C3: same rotation as the "next queued spot" branch above.
          const advancedState = advanceEncodeState(newItems, nextStats, base);
          return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
        }
        const feedback = successFeedback(gr, {
          text: `${rTop.streak} of ${state.config.encodeReps} streaks`,
          type: 'success',
          dwellKey: 'remediate-streak-progress',
        });
        newItems[itIdx] = it;
        // Phase 2 (within-session spacing): rotate to another batch card
        // between reps here too -- see the combine branch's comment above.
        const advancedState = advanceEncodeState(newItems, nextStats, base);
        return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
      }

      nextStats.misses++;
      rTop.streak = 0;
      rTop.missCount++;
      const rWordCount = rTop.text.split(' ').length;

      let feedback: Feedback;
      if (rTop.missCount >= 2 && rWordCount > 1) {
        const halves = splitInHalf(rTop.text);
        const culpritPiece = culpritHalf(typed, halves[0], halves[1], gradeOpts.strictPunctuation);
        it.remediateStack.push({ text: culpritPiece, streak: 0, missCount: 0 });
        feedback = {
          text: 'Still struggling — zooming into smaller sub-phrase',
          type: 'danger',
          dwellKey: 'remediate-miss-split',
        };
      } else {
        feedback = {
          text: 'Not quite — compare with target:',
          type: 'danger',
          diff: gr.diff,
          dwellKey: 'remediate-miss-retry',
        };
      }
      newItems[itIdx] = it;
      // C5: manual advance on a wrong verdict (see the chunks-miss branch above).
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'manual',
      };
    }

    // Stage: full (short phrase <= 3 words, or chunkDifficulty >= 100)
    const gr = grade(typed, it.back, gradeOpts);
    const isOk = gr.verdict !== 'wrong';
    if (gr.verdict === 'near') nextStats.nearMisses++;

    if (isOk) {
      it.encodeStreak++;
      if (it.encodeStreak >= state.config.encodeReps) {
        it.status = 'ready';
        const feedback = successFeedback(gr, { text: 'Encoded!', type: 'success', dwellKey: 'full-advance' });
        newItems[itIdx] = it;
        const advancedState = advanceEncodeState(newItems, nextStats, base);
        return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
      }
      const feedback = successFeedback(gr, {
        text: `${it.encodeStreak} of ${state.config.encodeReps} streaks`,
        type: 'success',
        dwellKey: 'full-streak-progress',
      });
      newItems[itIdx] = it;
      // Phase 2 (within-session spacing): rotate to another batch card
      // between reps here too -- see the combine branch's comment above.
      const advancedState = advanceEncodeState(newItems, nextStats, base);
      return { state: advancedState, verdict: gr.verdict, feedback, advance: 'auto' };
    }

    nextStats.misses++;
    it.encodeStreak = 0;
    const feedback: Feedback = {
      text: 'Streak reset — compare your answer:',
      type: 'danger',
      diff: gr.diff,
      dwellKey: 'full-miss',
    };
    newItems[itIdx] = it;
    // C5: manual advance on a wrong verdict (see the chunks-miss branch above).
    return {
      state: { ...base, items: newItems, stats: nextStats },
      verdict: 'wrong',
      feedback,
      advance: 'manual',
    };
  }

  // Phase: cycle (spaced retrieval interleaving) -- always manual advance;
  // grading updates items/queue/stats immediately but the item switch itself
  // waits for an explicit applyNext() call (mirrors handleNext/advanceCycle).
  const gr = grade(typed, it.back, gradeOpts);
  const isOkCycle = gr.verdict !== 'wrong';
  if (gr.verdict === 'near') nextStats.nearMisses++;
  const updatedQueue = [...state.queue];
  let feedback: Feedback;

  if (isOkCycle) {
    it.cycleStreak++;
    if (it.cycleStreak >= 2) {
      it.status = 'mastered';
      feedback = successFeedback(gr, {
        text: 'Mastered! Item retired.',
        type: 'success',
        dwellKey: 'cycle-mastered',
      });
    } else {
      feedback = successFeedback(gr, {
        text: 'Correct — will test once more later in the session.',
        type: 'success',
        dwellKey: 'cycle-correct',
      });
      // Within-session spacing (2026-09-24): a first-correct card goes to the
      // END of the current pass, not a fixed gap -- maximizes the trials
      // separating it from its mastering answer. Only the last remaining
      // card in a pass is exempt (queue is empty, so this is a no-op and it
      // repeats at lag 0) until the Final check covers that case instead.
      requeueCycleItem(updatedQueue, it.id, updatedQueue.length, state.config.cycleOrder);
    }
  } else {
    nextStats.misses++;
    it.cycleStreak = 0;
    feedback = {
      text: 'Missed — review answer below before continuing:',
      type: 'danger',
      diff: gr.diff,
      dwellKey: 'cycle-miss',
    };
    const gap = 2 + Math.floor(Math.random() * 2);
    requeueCycleItem(updatedQueue, it.id, gap, state.config.cycleOrder);
  }

  newItems[itIdx] = it;
  return {
    state: { ...base, items: newItems, queue: updatedQueue, stats: nextStats },
    verdict: gr.verdict,
    feedback,
    advance: 'manual',
  };
}

// B2 fix: handles a revealed trial uniformly across every stage/phase. Resets
// only the current stage's own streak field to 0 -- never touches status,
// combineMissCount, remediateStack/Queue contents, or the cycle queue's
// contents beyond the same reinsertion a miss would need (the item still has
// to be retested) -- and never increments stats.misses.
function applyRevealedAnswer(
  state: SessionState,
  it: DrillItem,
  newItems: DrillItem[],
  itIdx: number,
  base: SessionState
): ApplyAnswerResult {
  const feedback: Feedback = {
    text: 'Revealed — streak reset for this part.',
    type: 'danger',
    dwellKey: 'revealed-reset',
  };

  if (state.phase === 'cycle') {
    it.cycleStreak = 0;
    const updatedQueue = [...state.queue];
    const gap = 2 + Math.floor(Math.random() * 2);
    requeueCycleItem(updatedQueue, it.id, gap, state.config.cycleOrder);
    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems, queue: updatedQueue },
      verdict: 'revealed',
      feedback,
      advance: 'manual',
    };
  }

  if (it.stage === 'chunks') {
    it.chunkStreak = 0;
  } else if (it.stage === 'combine') {
    it.combineStreak = 0;
  } else if (it.stage === 'remediate') {
    it.remediateStack = it.remediateStack.map(r => ({ ...r }));
    const rTop = it.remediateStack[it.remediateStack.length - 1];
    if (rTop) rTop.streak = 0;
  } else {
    it.encodeStreak = 0;
  }

  newItems[itIdx] = it;
  return {
    state: { ...base, items: newItems },
    verdict: 'revealed',
    feedback,
    advance: 'auto',
  };
}

// Equivalent of SessionView's handleNext -> advanceCycle. The re-entrancy
// guard for a manual advance (B5) is shell-level UI state (isProcessing),
// not part of SessionState, so it belongs in SessionView, not here.
export function applyNext(state: SessionState): SessionState {
  return advanceCycleState(state.items, state.queue, state.stats, state);
}

// Mid-session edit of the card currently being drilled (state.currentId).
// Only valid in 'encode' or 'cycle'; anything else, or an empty field after
// trimming, returns the state unchanged. Stats are never touched.
//
// If the answer didn't really change -- exactMatch under the deck's own
// punctuation mode, so 'pre op' -> 'pre-op' keeps progress on a normal deck
// but not a strict one -- progress is kept and only the text (and chunk
// texts) are swapped. That needs the chunk count to stay the same and the
// item not to be in 'remediate' (whose stack holds old chunk text);
// presentation beats and cues show chunk text, so chunks can't go stale.
// Otherwise the card restarts from scratch, rebuilt exactly as buildItems
// would, at its existing id, and is served again right away -- which from
// 'cycle' means dropping back to 'encode' with an empty queue. Other items
// keep their status and cycleStreak; once the restarted card is encoded,
// advanceEncodeState rebuilds the cycle queue from the batch's non-mastered
// cards.
export function editCurrentItem(
  state: SessionState,
  edit: { front: string; back: string; extra?: string }
): { state: SessionState; restarted: boolean } {
  const unchanged = { state, restarted: false };
  if (state.phase !== 'encode' && state.phase !== 'cycle') return unchanged;
  const old = state.items.find(i => i.id === state.currentId);
  if (!old) return unchanged;
  const front = edit.front.trim();
  const back = edit.back.trim();
  if (!front || !back) return unchanged;
  // Display-only: never enters answerChanged, never affects the branch below.
  const extra = edit.extra?.trim() || undefined;

  const replaceItem = (item: DrillItem) => state.items.map(i => (i.id === item.id ? item : i));

  const answerChanged = !exactMatch(old.back, back, state.config.strictPunctuation ?? false);
  if (!answerChanged) {
    // An untouched back keeps its stored chunks as-is: recomputing could
    // disagree with how an older session chunked it (e.g. one saved before
    // MIN_WORDS_TO_CHUNK changed), and a prompt-only edit must never restart.
    if (back === old.back) {
      return { state: { ...state, items: replaceItem({ ...old, front, extra }) }, restarted: false };
    }
    const chunks = chunkText(back, state.config.chunkDifficulty, MIN_WORDS_TO_CHUNK);
    const sameChunkCount = (chunks?.length ?? null) === (old.chunks?.length ?? null);
    if (sameChunkCount && old.stage !== 'remediate') {
      return { state: { ...state, items: replaceItem({ ...old, front, back, chunks, extra }) }, restarted: false };
    }
  }

  const rebuilt: DrillItem = {
    ...buildItem({ front, back, extra }, old.id, state.config.chunkDifficulty, state.config.ladderMode, MIN_WORDS_TO_CHUNK),
    status: 'encoding',
  };
  return {
    state: {
      ...state,
      items: replaceItem(rebuilt),
      ...(state.phase === 'cycle' ? { phase: 'encode' as const, queue: [] } : {}),
    },
    restarted: true,
  };
}
