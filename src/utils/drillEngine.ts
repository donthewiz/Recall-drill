import {
  CombineSequenceItem,
  DeckItem,
  DrillItem,
  SavedDeckEntry,
  SavedSessionState,
  DeckFolder,
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

export function findAllCulpritChunks(
  typed: string,
  chunks: string[],
  startIdx: number,
  endIdx: number
): number[] {
  const typedWords = typed
    .trim()
    .split(/\s+/)
    .filter(w => w.length > 0);
  let pos = 0;
  const culprits: number[] = [];

  for (let idx = startIdx; idx <= endIdx; idx++) {
    const chunkWordCount = chunks[idx].split(' ').length;
    const segment = typedWords.slice(pos, pos + chunkWordCount).join(' ');
    if (norm(segment) !== norm(chunks[idx])) {
      culprits.push(idx);
    }
    pos += chunkWordCount;
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
