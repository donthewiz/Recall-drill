// localStorage persistence: decks, the deck index, folders, and saved
// session state.

import {
  DeckItem,
  DrillItem,
  SavedDeckEntry,
  SavedSessionState,
  DeckFolder,
} from '../types';
import { slugify } from './items';

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
