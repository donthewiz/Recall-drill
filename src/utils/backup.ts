// Storage-durability helpers: requesting persistent storage, and exporting /
// importing a full backup of the deck library.
//
// localStorage keys this file reads and writes (see also drillEngine.ts,
// which owns the per-key read/write helpers `lsGet`/`lsSet`/`lsDelete`):
//   - 'deck-index'    -- SavedDeckEntry[], the deck library's index
//   - 'deck-folders'  -- DeckFolder[], the folder tree
//   - `deck:${slug}`  -- DeckItem[], one deck's cards
//   - `session:${slug}` -- SavedSessionState, one deck's in-progress session
//   - 'recall_drill_last_export' -- ISO timestamp of the last successful export

import {
  DeckFolder,
  DeckItem,
  SavedDeckEntry,
  SavedSessionState,
} from '../types';
import {
  loadDeckIndex,
  loadFolderIndex,
  saveFolderIndex,
  getDeckFromStorage,
  getSessionState,
  lsGet,
  lsSet,
  lsDelete,
} from './drillEngine';

export const BACKUP_SCHEMA_VERSION = 1;

export const LAST_EXPORT_KEY = 'recall_drill_last_export';

export const EXPORT_STALE_DAYS = 14;

export interface DeckBackupEntry {
  slug: string;
  name: string;
  folderId: string | null;
  updatedAt?: string;
  lastUsedAt?: string;
  items: DeckItem[];
  session?: SavedSessionState | null;
}

export interface BackupPayload {
  schemaVersion: number;
  exportedAt: string;
  folders: DeckFolder[];
  decks: DeckBackupEntry[];
}

export function buildBackupPayload(): BackupPayload {
  const index = loadDeckIndex();
  const folders = loadFolderIndex();
  return {
    schemaVersion: BACKUP_SCHEMA_VERSION,
    exportedAt: new Date().toISOString(),
    folders,
    decks: index.map(d => ({
      slug: d.slug,
      name: d.name,
      folderId: d.folderId ?? null,
      updatedAt: d.updatedAt,
      lastUsedAt: d.lastUsedAt,
      items: getDeckFromStorage(d.slug) || [],
      session: getSessionState(d.slug),
    })),
  };
}

function pad2(n: number): string {
  return String(n).padStart(2, '0');
}

export function backupFilename(date: Date = new Date()): string {
  return `recall-drill-backup-${date.getFullYear()}-${pad2(date.getMonth() + 1)}-${pad2(date.getDate())}.json`;
}

export function getLastExportDate(): string | null {
  return lsGet<string>(LAST_EXPORT_KEY);
}

function recordExportNow(): void {
  lsSet(LAST_EXPORT_KEY, new Date().toISOString());
}

export function daysSince(isoDate: string): number {
  return (Date.now() - new Date(isoDate).getTime()) / (24 * 60 * 60 * 1000);
}

// Builds the payload and marks "last export" as now. Call this once per
// user-initiated export -- kept separate from buildBackupPayload so the
// round-trip unit test can build a payload without mutating that timestamp.
export function exportAllDecks(): BackupPayload {
  const payload = buildBackupPayload();
  recordExportNow();
  return payload;
}

// Triggers a browser download of the given payload as a .json file. No-op
// (throws) outside a DOM environment -- callers only use this from the UI.
export function triggerBackupDownload(payload: BackupPayload): void {
  const json = JSON.stringify(payload, null, 2);
  const blob = new Blob([json], { type: 'application/json' });
  const url = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = url;
  a.download = backupFilename();
  document.body.appendChild(a);
  a.click();
  document.body.removeChild(a);
  URL.revokeObjectURL(url);
}

export interface BackupValidationResult {
  valid: boolean;
  error?: string;
}

export function validateBackupPayload(data: unknown): BackupValidationResult {
  if (!data || typeof data !== 'object') {
    return { valid: false, error: 'This file is not a valid backup (expected a JSON object).' };
  }
  const obj = data as Record<string, unknown>;
  if (typeof obj.schemaVersion !== 'number') {
    return { valid: false, error: 'This file is missing a schema version and cannot be imported.' };
  }
  if (obj.schemaVersion > BACKUP_SCHEMA_VERSION) {
    return {
      valid: false,
      error: `This backup was made with a newer version of the app (schema v${obj.schemaVersion}). Update the app before importing it.`,
    };
  }
  if (!Array.isArray(obj.decks)) {
    return { valid: false, error: 'This file has no decks array and cannot be imported.' };
  }
  if (!Array.isArray(obj.folders)) {
    return { valid: false, error: 'This file has no folders array and cannot be imported.' };
  }
  for (const d of obj.decks as unknown[]) {
    const deck = d as Record<string, unknown>;
    if (!deck || typeof deck.slug !== 'string' || typeof deck.name !== 'string' || !Array.isArray(deck.items)) {
      return { valid: false, error: 'One or more decks in this file are malformed.' };
    }
  }
  for (const f of obj.folders as unknown[]) {
    const folder = f as Record<string, unknown>;
    if (!folder || typeof folder.id !== 'string' || typeof folder.name !== 'string') {
      return { valid: false, error: 'One or more folders in this file are malformed.' };
    }
  }
  return { valid: true };
}

export interface ImportSummary {
  decksImported: number;
  decksSkipped: number;
  foldersImported: number;
}

// 'merge' adds decks not already present locally (matched by slug) and
// leaves everything else untouched. 'replace' wipes every existing deck,
// folder, and session before restoring the backup in full. Neither mode is
// ever invoked without the caller having already gotten explicit
// confirmation -- see DecksView's import modal.
export function importBackupPayload(
  payload: BackupPayload,
  mode: 'merge' | 'replace'
): ImportSummary {
  if (mode === 'replace') {
    const existing = loadDeckIndex();
    existing.forEach(d => {
      lsDelete(`deck:${d.slug}`);
      lsDelete(`session:${d.slug}`);
    });
    lsSet('deck-index', []);
    saveFolderIndex([]);
  }

  const existingFolders = loadFolderIndex();
  const existingFolderIds = new Set(existingFolders.map(f => f.id));
  const mergedFolders = [...existingFolders];
  let foldersImported = 0;
  for (const f of payload.folders) {
    if (!existingFolderIds.has(f.id)) {
      mergedFolders.push(f);
      existingFolderIds.add(f.id);
      foldersImported++;
    }
  }
  saveFolderIndex(mergedFolders);

  const existingIndex = loadDeckIndex();
  const existingSlugs = new Set(existingIndex.map(d => d.slug));
  const nextIndex = [...existingIndex];
  let decksImported = 0;
  let decksSkipped = 0;

  for (const deck of payload.decks) {
    if (mode === 'merge' && existingSlugs.has(deck.slug)) {
      decksSkipped++;
      continue;
    }

    lsSet(`deck:${deck.slug}`, deck.items);
    if (deck.session) {
      lsSet(`session:${deck.slug}`, deck.session);
    }

    const entry: SavedDeckEntry = {
      slug: deck.slug,
      name: deck.name,
      count: deck.items.length,
      folderId: deck.folderId ?? null,
      updatedAt: deck.updatedAt,
      lastUsedAt: deck.lastUsedAt,
    };
    const idx = nextIndex.findIndex(e => e.slug === deck.slug);
    if (idx >= 0) {
      nextIndex[idx] = entry;
    } else {
      nextIndex.push(entry);
    }
    existingSlugs.add(deck.slug);
    decksImported++;
  }

  lsSet('deck-index', nextIndex);

  return { decksImported, decksSkipped, foldersImported };
}

export type PersistenceStatus = 'protected' | 'not-protected' | 'unsupported' | 'checking';

// Called once on app load. Installed PWAs are usually auto-granted this by
// the browser; it stops the browser evicting decks under storage pressure.
export async function requestPersistentStorage(): Promise<PersistenceStatus> {
  if (typeof navigator === 'undefined' || !navigator.storage || !navigator.storage.persist) {
    return 'unsupported';
  }
  try {
    const granted = await navigator.storage.persist();
    return granted ? 'protected' : 'not-protected';
  } catch {
    return 'unsupported';
  }
}
