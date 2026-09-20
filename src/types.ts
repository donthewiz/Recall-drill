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
  timestamp?: number;
}

export type ViewState = 'setup' | 'decks' | 'session' | 'done';

// 'near' is added by C2 (lenient grading); Phase 0 grading is still exact-match only.
export type Verdict = 'exact' | 'wrong';

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
  // batchSize, ladderMode, lenient, stemTolerance are added by C1-C3;
  // intentionally absent in Phase 0.
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
