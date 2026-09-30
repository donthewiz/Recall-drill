// Deck parsing, chunking, the combine ladder, remediation helpers, and
// DrillItem construction/normalization.

import {
  CombineSequenceItem,
  DeckItem,
  DrillItem,
  SavedSessionState,
  LadderMode,
} from '../types';
import { exactMatch, computeWordDiff } from './grading';

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
export function buildItem(
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
    // Phase 3: undefined on any save from before the Final check existed --
    // threaded through unchanged, same as `extra`.
    finalDone: it.finalDone,
    finalMisses: it.finalMisses,
    // Per-card telemetry: same, undefined on older saves.
    attempts: it.attempts,
    misses: it.misses,
    reveals: it.reveals,
    nearMisses: it.nearMisses,
    hardSpans: it.hardSpans,
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
