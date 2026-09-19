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
