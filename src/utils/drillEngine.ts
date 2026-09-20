import {
  CombineSequenceItem,
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
} from '../types';

export function norm(s: string): string {
  return s
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9 ]/g, '')
    .replace(/\s+/g, ' ');
}

export interface WordDiffResult {
  word: string;
  matched: boolean;
}

export function computeWordDiff(typedStr: string, targetStr: string): WordDiffResult[] {
  const typedWords = typedStr.trim().length ? typedStr.trim().split(/\s+/) : [];
  const targetWords = targetStr.trim().split(/\s+/);
  const tN = typedWords.map(w => norm(w));
  const gN = targetWords.map(w => norm(w));
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

  const matchedTarget = new Array(m).fill(false);
  let i = n;
  let jj = m;
  while (i > 0 && jj > 0) {
    if (tN[i - 1] === gN[jj - 1]) {
      matchedTarget[jj - 1] = true;
      i--;
      jj--;
    } else if (dp[i - 1][jj] >= dp[i][jj - 1]) {
      i--;
    } else {
      jj--;
    }
  }

  return targetWords.map((word, idx) => ({
    word,
    matched: matchedTarget[idx],
  }));
}

export function parseDeck(text: string): DeckItem[] {
  const lines = text.split('\n');
  const out: DeckItem[] = [];

  for (let i = 0; i < lines.length; i++) {
    const line = lines[i].trim();
    if (!line || line.startsWith('//') || line.startsWith('#')) continue;

    let front = '';
    let back = '';

    if (line.includes('\t')) {
      const parts = line.split('\t');
      front = parts[0].trim();
      back = parts.slice(1).join('\t').trim();
    } else if (line.includes('::')) {
      const parts = line.split('::');
      front = (parts[0] || '').trim();
      back = (parts.slice(1).join('::') || '').trim();
    } else if (line.includes(' - ') && !line.includes('->')) {
      // Fallback for hyphen separator
      const parts = line.split(' - ');
      front = (parts[0] || '').trim();
      back = (parts.slice(1).join(' - ') || '').trim();
    }

    if (front && back) {
      out.push({ front, back });
    }
  }

  return out;
}

export function chunkText(text: string, chunkPercent: number = 35): string[] | null {
  const words = text.split(/\s+/).filter(w => w.length > 0);
  if (words.length <= 3) return null;

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

export function buildCombineSequence(n: number): CombineSequenceItem[] {
  const seq: CombineSequenceItem[] = [];
  for (let e = 2; e <= n; e++) {
    for (let s = 2; s <= e; s++) {
      seq.push({ start: e - s + 1, end: e });
    }
  }
  return seq;
}

export function splitInHalf(text: string): [string, string] {
  const words = text.split(' ');
  const mid = Math.ceil(words.length / 2);
  return [words.slice(0, mid).join(' '), words.slice(mid).join(' ')];
}

export function culpritHalf(typed: string, left: string, right: string): string {
  const typedWords = typed.trim().length ? typed.trim().split(/\s+/) : [];
  const leftWordCount = left.split(' ').length;
  const leftTyped = typedWords.slice(0, leftWordCount).join(' ');
  if (norm(leftTyped) !== norm(left)) return left;
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
  endIdx: number
): number[] {
  const combinedTarget = chunks.slice(startIdx, endIdx + 1).join(' ');
  const diff = computeWordDiff(typed, combinedTarget);

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

export function slugify(name: string): string {
  const s = name
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return s || 'deck';
}

export function buildItems(parsed: DeckItem[], chunkPercent: number = 35): DrillItem[] {
  return parsed.map((p, i) => {
    const chunks = chunkText(p.back, chunkPercent);
    return {
      id: i,
      front: p.front,
      back: p.back,
      status: 'new',
      encodeStreak: 0,
      cycleStreak: 0,
      chunks,
      chunkIndex: 0,
      chunkStreak: 0,
      combineSeq: chunks ? buildCombineSequence(chunks.length) : null,
      combineSeqIdx: 0,
      combineStreak: 0,
      combineMissCount: 0,
      remediateStack: [],
      remediateQueue: [],
      remediateReturnSeqIdx: 0,
      stage: chunks ? 'chunks' : 'full',
    };
  });
}

export function normalizeItem(it: any): DrillItem {
  const item: DrillItem = {
    id: it.id,
    front: it.front,
    back: it.back,
    status: it.status || 'new',
    encodeStreak: it.encodeStreak ?? 0,
    cycleStreak: it.cycleStreak ?? 0,
    chunks: it.chunks || null,
    chunkIndex: it.chunkIndex ?? 0,
    chunkStreak: it.chunkStreak ?? 0,
    combineSeq: it.combineSeq || (it.chunks ? buildCombineSequence(it.chunks.length) : null),
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

  return item;
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
  folderId?: string | null
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

  const entry: SavedDeckEntry = {
    slug,
    name,
    count: items.length,
    folderId: finalFolderId,
    updatedAt: now,
    lastUsedAt: now,
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

export function getRecentlyUsedDecks(): SavedDeckEntry[] {
  const index = loadDeckIndex();
  return index
    .filter(d => !isPremadeDeck(d.slug, d.name))
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
// chosen to sit between the 500ms streak-progress dwell and the 1600ms miss
// dwells since it's informational, not punitive.
export const DWELL_MS: Record<string, number> = {
  'chunks-advance': 700,
  'chunks-streak-progress': 500,
  'chunks-miss': 1800,
  'combine-ready': 600,
  'combine-advance': 700,
  'combine-streak-progress': 500,
  'combine-miss-remediate': 1800,
  'combine-miss-retry': 1600,
  'remediate-next-spot': 900,
  'remediate-resume-combine': 700,
  'remediate-expand-parent': 1100,
  'remediate-streak-progress': 500,
  'remediate-miss-split': 1800,
  'remediate-miss-retry': 1600,
  'full-advance': 600,
  'full-streak-progress': 500,
  'full-miss': 1600,
  'revealed-reset': 1200,
};

function advanceEncodeState(
  items: DrillItem[],
  stats: SessionStats,
  base: SessionState
): SessionState {
  const remaining = items.filter(i => i.status === 'new' || i.status === 'encoding');
  if (!remaining.length) {
    const newQueue = shuffle(items.filter(i => i.status !== 'mastered').map(i => i.id));
    return advanceCycleState(items, newQueue, stats, {
      ...base,
      items,
      phase: 'cycle',
      queue: newQueue,
      stats,
    });
  }

  const nextItem = remaining[0];
  const newItems = items.map(i =>
    i.id === nextItem.id ? { ...i, status: 'encoding' as const } : i
  );
  return { ...base, items: newItems, phase: 'encode', currentId: nextItem.id, stats };
}

function advanceCycleState(
  items: DrillItem[],
  currentQueue: number[],
  stats: SessionStats,
  base: SessionState
): SessionState {
  let q = [...currentQueue];
  if (!q.length) {
    const remaining = items.filter(i => i.status !== 'mastered');
    if (!remaining.length) {
      return { ...base, items, phase: 'cycle', queue: [], stats, currentId: SESSION_COMPLETE_ID };
    }
    q = shuffle(remaining.map(i => i.id));
  }

  const nextId = q.shift()!;
  return { ...base, items, phase: 'cycle', queue: q, stats, currentId: nextId };
}

// Equivalent of SessionView's mount useEffect: picks the first trial of a
// fresh or resumed session before any answer has been submitted.
export function initSession(state: SessionState): SessionState {
  if (state.phase === 'cycle') {
    return advanceCycleState(state.items, state.queue, state.stats, state);
  }
  return advanceEncodeState(state.items, state.stats, state);
}

export function selectTrial(state: SessionState): Trial | null {
  const it = state.items.find(i => i.id === state.currentId);
  if (!it) return null;

  if (state.phase === 'cycle') {
    return {
      itemId: it.id,
      stage: 'cycle',
      prompt: it.front,
      target: it.back,
      isBlind: true,
      label: 'Spaced Retrieval Cycle',
      detail: 'Spaced Retrieval • Cycling review',
    };
  }

  if (it.stage === 'chunks' && it.chunks) {
    const chunk = it.chunks[it.chunkIndex];
    return {
      itemId: it.id,
      stage: 'chunks',
      prompt: it.front,
      target: chunk,
      isBlind: it.chunkStreak >= 1,
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
      isBlind: it.combineStreak >= 1,
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
      isBlind: rTop.streak >= 1,
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
    isBlind: it.encodeStreak >= 1,
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
  // override is reserved for C2 (lenient grading's manual override) -- inert
  // in Phase 0/1.
  opts: { revealed: boolean; override?: boolean }
): ApplyAnswerResult {
  const currentItem = state.items.find(i => i.id === state.currentId);
  if (!currentItem) {
    throw new Error('applyAnswer called with no current item');
  }

  const nextStats: SessionStats = { ...state.stats, attempts: state.stats.attempts + 1 };
  const newItems = [...state.items];
  const itIdx = newItems.findIndex(i => i.id === currentItem.id);
  const it = { ...newItems[itIdx] };
  const base: SessionState = { ...state, stats: nextStats };

  // B2 fix: a revealed trial must not advance the streak and must not count
  // as a miss, regardless of what was typed (including typing the now-visible
  // answer correctly). Resets the current stage's streak to 0 and stays on
  // the same trial -- it never reaches the per-stage isOk branching below.
  if (opts.revealed) {
    return applyRevealedAnswer(state, it, newItems, itIdx, base);
  }

  if (state.phase === 'encode') {
    if (it.stage === 'chunks' && it.chunks) {
      const targetChunk = it.chunks[it.chunkIndex];
      const isOk = norm(typed) === norm(targetChunk);

      if (isOk) {
        it.chunkStreak++;
        if (it.chunkStreak >= state.config.encodeReps) {
          it.chunkIndex++;
          it.chunkStreak = 0;
          let feedback: Feedback;
          if (it.chunkIndex >= it.chunks.length) {
            it.stage = 'combine';
            it.combineSeqIdx = 0;
            it.combineStreak = 0;
            feedback = {
              text: 'All parts learned — now combining them',
              type: 'success',
              dwellKey: 'chunks-advance',
            };
          } else {
            feedback = { text: 'Part learned!', type: 'success', dwellKey: 'chunks-advance' };
          }
          newItems[itIdx] = it;
          const advancedState = advanceEncodeState(newItems, nextStats, base);
          return { state: advancedState, verdict: 'exact', feedback, advance: 'auto' };
        }
        const feedback: Feedback = {
          text: `${it.chunkStreak} of ${state.config.encodeReps} streaks`,
          type: 'success',
          dwellKey: 'chunks-streak-progress',
        };
        newItems[itIdx] = it;
        return { state: { ...base, items: newItems }, verdict: 'exact', feedback, advance: 'auto' };
      }

      nextStats.misses++;
      it.chunkStreak = 0;
      const diff = computeWordDiff(typed, targetChunk);
      const feedback: Feedback = {
        text: 'Streak reset — compare your answer:',
        type: 'danger',
        diff,
        dwellKey: 'chunks-miss',
      };
      newItems[itIdx] = it;
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'auto',
      };
    }

    if (it.stage === 'combine' && it.chunks && it.combineSeq) {
      const seqItem = it.combineSeq[it.combineSeqIdx];
      const combinedTarget = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
      const wasBlind = it.combineStreak >= 1;
      const isOk = norm(typed) === norm(combinedTarget);

      if (isOk) {
        it.combineStreak++;
        if (wasBlind) it.combineMissCount = 0;

        if (it.combineStreak >= state.config.encodeReps) {
          it.combineSeqIdx++;
          it.combineStreak = 0;
          let feedback: Feedback;
          if (it.combineSeqIdx >= it.combineSeq.length) {
            it.status = 'ready';
            feedback = { text: 'Encoded!', type: 'success', dwellKey: 'combine-ready' };
          } else {
            feedback = {
              text: 'Combination learned!',
              type: 'success',
              dwellKey: 'combine-advance',
            };
          }
          newItems[itIdx] = it;
          const advancedState = advanceEncodeState(newItems, nextStats, base);
          return { state: advancedState, verdict: 'exact', feedback, advance: 'auto' };
        }
        const feedback: Feedback = {
          text: `${it.combineStreak} of ${state.config.encodeReps} streaks`,
          type: 'success',
          dwellKey: 'combine-streak-progress',
        };
        newItems[itIdx] = it;
        return { state: { ...base, items: newItems }, verdict: 'exact', feedback, advance: 'auto' };
      }

      nextStats.misses++;
      it.combineStreak = 0;
      it.combineMissCount++;
      const windowChunkCount = seqItem.end - seqItem.start + 1;
      const missThreshold = windowChunkCount <= 2 ? 1 : 2;

      let feedback: Feedback;
      if (it.combineMissCount >= missThreshold) {
        const culprits = findAllCulpritChunks(typed, it.chunks, seqItem.start - 1, seqItem.end - 1);
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
        const diff = computeWordDiff(typed, combinedTarget);
        feedback = {
          text: 'Streak reset — check the wording:',
          type: 'danger',
          diff,
          dwellKey: 'combine-miss-retry',
        };
      }
      newItems[itIdx] = it;
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'auto',
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
      const isOk = norm(typed) === norm(rTop.text);

      if (isOk) {
        rTop.streak++;
        rTop.missCount = 0;
        if (rTop.streak >= state.config.encodeReps) {
          it.remediateStack.pop();
          if (it.remediateStack.length === 0) {
            if (it.remediateQueue.length > 0) {
              const nextPiece = it.remediateQueue.shift()!;
              it.remediateStack = [{ text: nextPiece, streak: 0, missCount: 0 }];
              const feedback: Feedback = {
                text: 'Trouble spot solid! Now checking the next spot',
                type: 'success',
                dwellKey: 'remediate-next-spot',
              };
              newItems[itIdx] = it;
              return {
                state: { ...base, items: newItems },
                verdict: 'exact',
                feedback,
                advance: 'auto',
              };
            }
            it.stage = 'combine';
            it.combineSeqIdx = it.remediateReturnSeqIdx;
            it.combineStreak = 0;
            const feedback: Feedback = {
              text: 'Reinforced! Resuming progressive combining',
              type: 'success',
              dwellKey: 'remediate-resume-combine',
            };
            newItems[itIdx] = it;
            const advancedState = advanceEncodeState(newItems, nextStats, base);
            return { state: advancedState, verdict: 'exact', feedback, advance: 'auto' };
          }
          const parentLevel = it.remediateStack[it.remediateStack.length - 1];
          parentLevel.streak = 0;
          const parentWordCount = parentLevel.text.split(' ').length;
          const feedback: Feedback = {
            text: `Isolated piece mastered — expanding to ${parentWordCount}-word parent`,
            type: 'success',
            dwellKey: 'remediate-expand-parent',
          };
          newItems[itIdx] = it;
          return { state: { ...base, items: newItems }, verdict: 'exact', feedback, advance: 'auto' };
        }
        const feedback: Feedback = {
          text: `${rTop.streak} of ${state.config.encodeReps} streaks`,
          type: 'success',
          dwellKey: 'remediate-streak-progress',
        };
        newItems[itIdx] = it;
        return { state: { ...base, items: newItems }, verdict: 'exact', feedback, advance: 'auto' };
      }

      nextStats.misses++;
      rTop.streak = 0;
      rTop.missCount++;
      const rWordCount = rTop.text.split(' ').length;

      let feedback: Feedback;
      if (rTop.missCount >= 2 && rWordCount > 1) {
        const halves = splitInHalf(rTop.text);
        const culpritPiece = culpritHalf(typed, halves[0], halves[1]);
        it.remediateStack.push({ text: culpritPiece, streak: 0, missCount: 0 });
        feedback = {
          text: 'Still struggling — zooming into smaller sub-phrase',
          type: 'danger',
          dwellKey: 'remediate-miss-split',
        };
      } else {
        const diff = computeWordDiff(typed, rTop.text);
        feedback = {
          text: 'Not quite — compare with target:',
          type: 'danger',
          diff,
          dwellKey: 'remediate-miss-retry',
        };
      }
      newItems[itIdx] = it;
      return {
        state: { ...base, items: newItems, stats: nextStats },
        verdict: 'wrong',
        feedback,
        advance: 'auto',
      };
    }

    // Stage: full (short phrase <= 3 words, or chunkDifficulty >= 100)
    const isOk = norm(typed) === norm(it.back);

    if (isOk) {
      it.encodeStreak++;
      if (it.encodeStreak >= state.config.encodeReps) {
        it.status = 'ready';
        const feedback: Feedback = { text: 'Encoded!', type: 'success', dwellKey: 'full-advance' };
        newItems[itIdx] = it;
        const advancedState = advanceEncodeState(newItems, nextStats, base);
        return { state: advancedState, verdict: 'exact', feedback, advance: 'auto' };
      }
      const feedback: Feedback = {
        text: `${it.encodeStreak} of ${state.config.encodeReps} streaks`,
        type: 'success',
        dwellKey: 'full-streak-progress',
      };
      newItems[itIdx] = it;
      return { state: { ...base, items: newItems }, verdict: 'exact', feedback, advance: 'auto' };
    }

    nextStats.misses++;
    it.encodeStreak = 0;
    const diff = computeWordDiff(typed, it.back);
    const feedback: Feedback = {
      text: 'Streak reset — compare your answer:',
      type: 'danger',
      diff,
      dwellKey: 'full-miss',
    };
    newItems[itIdx] = it;
    return {
      state: { ...base, items: newItems, stats: nextStats },
      verdict: 'wrong',
      feedback,
      advance: 'auto',
    };
  }

  // Phase: cycle (spaced retrieval interleaving) -- always manual advance;
  // grading updates items/queue/stats immediately but the item switch itself
  // waits for an explicit applyNext() call (mirrors handleNext/advanceCycle).
  const isOkCycle = norm(typed) === norm(it.back);
  const updatedQueue = [...state.queue];
  let feedback: Feedback;

  if (isOkCycle) {
    it.cycleStreak++;
    if (it.cycleStreak >= 2) {
      it.status = 'mastered';
      feedback = { text: 'Mastered! Item retired.', type: 'success', dwellKey: 'cycle-mastered' };
    } else {
      feedback = {
        text: 'Correct — will test once more later in the session.',
        type: 'success',
        dwellKey: 'cycle-correct',
      };
      updatedQueue.splice(Math.min(3, updatedQueue.length), 0, it.id);
    }
  } else {
    nextStats.misses++;
    it.cycleStreak = 0;
    const diff = computeWordDiff(typed, it.back);
    feedback = {
      text: 'Missed — review answer below before continuing:',
      type: 'danger',
      diff,
      dwellKey: 'cycle-miss',
    };
    const gap = 2 + Math.floor(Math.random() * 2);
    updatedQueue.splice(Math.min(gap, updatedQueue.length), 0, it.id);
  }

  newItems[itIdx] = it;
  return {
    state: { ...base, items: newItems, queue: updatedQueue, stats: nextStats },
    verdict: isOkCycle ? 'exact' : 'wrong',
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
    updatedQueue.splice(Math.min(gap, updatedQueue.length), 0, it.id);
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
