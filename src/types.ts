export type ItemStatus = 'new' | 'encoding' | 'ready' | 'mastered';

export type EncodeStage = 'chunks' | 'combine' | 'remediate' | 'full';

export interface RemediateItem {
  text: string;
  streak: number;
  missCount: number;
}

export interface CombineSequenceItem {
  start: number;
  end: number;
}

export interface DrillItem {
  id: number;
  front: string;
  back: string;
  // Anki-style "Extra" field: display-only, shown in post-answer feedback
  // once the full back is on screen. Never graded, chunked, or counted
  // toward trials -- see drillEngine.ts's grade()/chunkText() call sites,
  // neither of which reads it.
  extra?: string;
  status: ItemStatus;
  encodeStreak: number;
  cycleStreak: number;
  chunks: string[] | null;
  chunkIndex: number;
  chunkStreak: number;
  combineSeq: CombineSequenceItem[] | null;
  combineSeqIdx: number;
  combineStreak: number;
  combineMissCount: number;
  remediateStack: RemediateItem[];
  remediateQueue: string[];
  remediateReturnSeqIdx: number;
  stage: EncodeStage;
  // Phase 3 (Final check, within-session spacing): whether this item has
  // already had its one correct Final-check answer. Both fields are
  // undefined on any save from before this phase -- normalizeItem threads
  // them through unchanged, same as `extra`.
  finalDone?: boolean;
  // Count of wrong/revealed answers during the Final check -- distinct from
  // `stats.misses` (session-wide) and never affects `status`/`cycleStreak`.
  finalMisses?: number;
}

export interface SessionStats {
  attempts: number;
  misses: number;
  // C2: near-misses (lenient grading forgave the difference) and manual
  // overrides ("Count as correct" on a wrong verdict) are tracked separately
  // from misses -- neither counts toward `misses`.
  nearMisses: number;
  overrides: number;
  startTime?: number;
}

export interface DeckFolder {
  id: string;
  name: string;
  parentId: string | null;
  createdAt: string;
  updatedAt?: string;
}

export interface SavedDeckEntry {
  slug: string;
  name: string;
  count: number;
  folderId?: string | null;
  updatedAt?: string;
  lastUsedAt?: string;
  // Phase 2 (per-deck strict punctuation): undefined on any deck saved
  // before this setting existed -> false (punctuation still forgiven).
  strictPunctuation?: boolean;
}

export interface WordDiffResult {
  word: string;
  matched: boolean;
}

export interface DeckItem {
  front: string;
  back: string;
  // Anki-style "Extra" field: optional, display-only. See DrillItem.extra.
  extra?: string;
}

export interface SavedSessionState {
  deckName: string;
  // C3: 'batch-done' is the interstitial between batches -- selectTrial has
  // nothing to show, and SessionView renders the batch summary screen
  // instead of the card. A save made at that exact moment ("Save and stop"
  // on the interstitial) persists this phase so resuming lands back on it.
  // Phase 3: 'final' is the Final check -- one shuffled, cue-free pass over
  // every item, entered after the LAST batch's cycle finishes instead of
  // ending the session there.
  phase: 'encode' | 'cycle' | 'batch-done' | 'final';
  queue: number[];
  stats: SessionStats;
  items: DrillItem[];
  encodeReps: number;
  chunkDifficulty?: number;
  stemTolerance?: boolean;
  ladderMode?: LadderMode;
  // undefined on any save from before this setting existed -> 'shuffled'.
  cycleOrder?: CycleOrder;
  // Phase 2: undefined on any save from before this setting existed -> false.
  strictPunctuation?: boolean;
  // C3: undefined on any save from before this phase (or when the user
  // never left batch 0) -- resolved by resolveBatchConfig's migration
  // default (batchIndex 0, batchSize items.length -- i.e. one big
  // "whole deck" batch, matching pre-C3 behavior's absence of a checkpoint).
  batchIndex?: number;
  batchSize?: number;
  // C3: session-cumulative SessionStats as of the moment the current batch
  // began -- lets the interstitial report "this batch" trials/accuracy by
  // diffing against `stats` instead of carrying separate running totals.
  batchStartStats?: SessionStats;
  // Phase 3: stats.attempts as of the moment the Final check began -- lets
  // computeCumulativeColdStartMultiplier's numerator match its denominator
  // while the Final check is still in progress (see that function's doc
  // comment). Undefined on any save from before this field existed, or one
  // that hasn't reached the Final check yet.
  finalCheckStartAttempts?: number;
  // Whether this session maps onto one saved deck (named deckName) that a
  // mid-session card edit may be written back to -- false for folder
  // practice. Undefined on any save from before this field existed ->
  // false (see resolveSourceDeckEditable): with no recorded source, edits
  // stay session-only.
  sourceDeckEditable?: boolean;
  timestamp?: number;
}

// C1: 'exhaustive' is buildCombineSequence's original n(n-1)/2-window ladder,
// kept available so the trial-count claim below can be measured against it
// rather than trusted. 'cumulative' (forward chaining) is the new default.
export type LadderMode = 'cumulative' | 'exhaustive';

// Cycle-phase card order. 'shuffled' (default) is the original behavior: a
// random order per pass, with a missed/revealed card reinserted 2-3 cards
// later and a correct-but-not-yet-mastered card reinserted at the END of the
// current pass (Within-session spacing, 2026-09-24) -- maximizing the gap
// before its mastering answer, per Karpicke & Bauernschmidt (2011).
// 'inOrder' walks the current batch's not-yet-mastered cards in deck order
// (DrillItem.id, i.e. the order they were written), one full pass at a
// time; nothing is reinserted mid-pass -- a missed card, or one that still
// needs its second correct, simply comes back on the next pass, still in
// order. Encode-phase order is unaffected either way.
export type CycleOrder = 'shuffled' | 'inOrder';

export type ViewState = 'setup' | 'decks' | 'session' | 'done';

// 'near' (Phase 2, C2): lenient grading forgave the difference (stopword-only,
// or a light-stem difference on an otherwise very close answer) -- advances
// the streak like 'exact', but never counts as a miss.
// 'revealed' (Phase 1, B2 fix): the trial was answered after Show Answer --
// streak resets to 0 and it never counts as a miss, regardless of what was typed.
// 'presented' (Phase 9, C8b): a chunks-stage presentation trial (cue
// 'present') was acknowledged -- nothing was graded, nothing can be wrong;
// distinct from 'exact' so the shell never mistakes it for a real answer.
export type Verdict = 'exact' | 'near' | 'wrong' | 'revealed' | 'presented';

export interface Feedback {
  text: string;
  type: 'success' | 'danger' | 'info';
  diff?: WordDiffResult[];
  // One of 17 keys enumerated in drillEngine.ts's DWELL_MS table -- drives
  // SessionView's setTimeout delay lookup without re-deriving the branch logic.
  dwellKey: string;
}

export interface SessionConfig {
  encodeReps: number;
  chunkDifficulty: number;
  // C2: whether grade() forgives a light-stem difference (e.g. a dropped
  // plural) on an otherwise very close answer. Default true; the doc calls
  // out turning it off for terminology decks where inflection matters.
  // `lenient` itself isn't user-configurable (the doc only asks for a
  // stemTolerance setting), so it's passed as a fixed `true` from
  // applyAnswer rather than living here.
  stemTolerance: boolean;
  // C1: which combine-window sequence buildCombineSequence produced this
  // item's combineSeq with, and which per-window rep rule applyAnswer's
  // combine branch applies (see requiredRepsForWindow).
  ladderMode: LadderMode;
  // C3: items per batch (deck order); undefined/0/>=items.length all mean
  // "whole deck as one batch" (no interstitial checkpoint) -- see
  // partitionIntoBatches. Left optional rather than required so every
  // pre-C3 SessionConfig literal (tests, test/simulate.ts's baselines)
  // keeps compiling and behaving exactly as before without being touched.
  batchSize?: number;
  // See CycleOrder. Optional for the same reason as batchSize: undefined
  // means 'shuffled', so every existing config literal keeps its behavior.
  cycleOrder?: CycleOrder;
  // Phase 2: per-deck "Punctuation must match" setting. Optional for the
  // same reason as batchSize/cycleOrder: undefined means false (punctuation
  // forgiven), so every existing config literal keeps its behavior.
  strictPunctuation?: boolean;
}

export interface SessionState {
  items: DrillItem[];
  phase: 'encode' | 'cycle' | 'batch-done' | 'final';
  queue: number[];
  stats: SessionStats;
  currentId: number;
  // C3: which batch (0-indexed, per partitionIntoBatches) is currently
  // active. Was always 0 and unused before this phase.
  batchIndex: number;
  // C3: see SavedSessionState.batchStartStats.
  batchStartStats: SessionStats;
  // Phase 3: see SavedSessionState.finalCheckStartAttempts. Optional (unlike
  // batchStartStats) so every pre-Phase-3 SessionState literal -- the many
  // tests that construct one directly -- keeps compiling unchanged; set by
  // advanceBatchState the moment phase first becomes 'final'.
  finalCheckStartAttempts?: number;
  config: SessionConfig;
}

// C5: replaces the old streak-derived isBlind boolean with an explicit cue
// level. 'firstLetter' is attempt 0 of a stage-unit (first char of each word,
// rest underscored -- see renderFirstLetterCue); 'none' is attempt 1+ (fully
// blind). 'full' and 'choice' are never produced by selectTrial itself --
// 'full' is what SessionView renders locally when the learner reveals the
// answer (Esc / Show Answer), and 'choice' is C7 (multiple-choice rung),
// dropped from scope.
// 'present' (C8b): the chunks stage's attempt 0 -- the chunk's full text is
// shown, ungraded, no input accepted; the learner presses Enter/Continue to
// move on to the first real (blind) attempt. selectTrial produces it only
// for stage 'chunks'; no payload needed, the text to show is Trial.target,
// same as every other cue.
export type Cue =
  | { kind: 'none' }
  | { kind: 'firstLetter'; pattern: string }
  | { kind: 'full'; text: string }
  | { kind: 'choice'; options: string[] }
  | { kind: 'present' };

export interface Trial {
  itemId: number;
  stage: EncodeStage | 'cycle' | 'final';
  prompt: string;
  target: string;
  cue: Cue;
  label: string;
  detail: string;
}
