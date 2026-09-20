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
}

export interface WordDiffResult {
  word: string;
  matched: boolean;
}

export interface DeckItem {
  front: string;
  back: string;
}

export interface SavedSessionState {
  deckName: string;
  phase: 'encode' | 'cycle';
  queue: number[];
  stats: SessionStats;
  items: DrillItem[];
  encodeReps: number;
  chunkDifficulty?: number;
  stemTolerance?: boolean;
  ladderMode?: LadderMode;
  timestamp?: number;
}

// C1: 'exhaustive' is buildCombineSequence's original n(n-1)/2-window ladder,
// kept available so the trial-count claim below can be measured against it
// rather than trusted. 'cumulative' (forward chaining) is the new default.
export type LadderMode = 'cumulative' | 'exhaustive';

export type ViewState = 'setup' | 'decks' | 'session' | 'done';

// 'near' (Phase 2, C2): lenient grading forgave the difference (stopword-only,
// or a light-stem difference on an otherwise very close answer) -- advances
// the streak like 'exact', but never counts as a miss.
// 'revealed' (Phase 1, B2 fix): the trial was answered after Show Answer --
// streak resets to 0 and it never counts as a miss, regardless of what was typed.
export type Verdict = 'exact' | 'near' | 'wrong' | 'revealed';

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
  // combine branch applies (see requiredRepsForWindow). batchSize is added
  // by C3; intentionally absent here.
  ladderMode: LadderMode;
}

export interface SessionState {
  items: DrillItem[];
  phase: 'encode' | 'cycle';
  queue: number[];
  stats: SessionStats;
  currentId: number;
  // Always 0 in Phase 0; never read or branched on until C3 (batching).
  batchIndex: number;
  config: SessionConfig;
}

export interface Trial {
  itemId: number;
  stage: EncodeStage | 'cycle';
  prompt: string;
  target: string;
  // Stands in for C5's not-yet-built Cue type; today's only signal is
  // streak-derived blind/not-blind.
  isBlind: boolean;
  label: string;
  detail: string;
}
