import { describe, it, expect, beforeEach } from 'vitest';
import {
  saveDeckToStorage,
  loadDeckIndex,
  loadFolderIndex,
  createFolder,
  getDeckFromStorage,
  getSessionState,
  saveSessionState,
} from '../utils/drillEngine';
import {
  buildBackupPayload,
  validateBackupPayload,
  importBackupPayload,
  backupFilename,
  BACKUP_SCHEMA_VERSION,
} from '../utils/backup';
import { DeckItem, SavedSessionState } from '../types';

const catsDeck: DeckItem[] = [
  { front: 'capital of france', back: 'paris' },
  { front: 'capital of spain', back: 'madrid' },
];

const dogsDeck: DeckItem[] = [{ front: '2+2', back: '4' }];

const fakeSession: SavedSessionState = {
  deckName: 'Cats',
  phase: 'cycle',
  queue: [0, 1],
  stats: { attempts: 3, misses: 1, nearMisses: 0, overrides: 0 },
  items: [],
  encodeReps: 3,
};

describe('backup export/import round trip', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('restores an identical library after export, wipe, and import (replace)', () => {
    const folder = createFolder('Geography');
    saveDeckToStorage('Cats', catsDeck, folder.id);
    saveDeckToStorage('Dogs', dogsDeck);
    saveSessionState('cats', fakeSession);

    const beforeIndex = loadDeckIndex();
    const beforeFolders = loadFolderIndex();
    const beforeCatsItems = getDeckFromStorage('cats');
    const beforeDogsItems = getDeckFromStorage('dogs');
    const beforeSession = getSessionState('cats');

    const payload = buildBackupPayload();
    expect(payload.schemaVersion).toBe(BACKUP_SCHEMA_VERSION);
    expect(payload.decks).toHaveLength(2);
    expect(payload.folders).toHaveLength(1);

    localStorage.clear();
    expect(loadDeckIndex()).toHaveLength(0);
    expect(loadFolderIndex()).toHaveLength(0);

    const validation = validateBackupPayload(payload);
    expect(validation.valid).toBe(true);

    const summary = importBackupPayload(payload, 'replace');
    expect(summary.decksImported).toBe(2);
    expect(summary.decksSkipped).toBe(0);
    expect(summary.foldersImported).toBe(1);

    expect(loadDeckIndex()).toEqual(beforeIndex);
    expect(loadFolderIndex()).toEqual(beforeFolders);
    expect(getDeckFromStorage('cats')).toEqual(beforeCatsItems);
    expect(getDeckFromStorage('dogs')).toEqual(beforeDogsItems);
    expect(getSessionState('cats')).toEqual(beforeSession);
  });

  it('merge mode adds only decks not already present, by slug', () => {
    saveDeckToStorage('Cats', catsDeck);
    const payload = buildBackupPayload();

    // Locally, "Cats" now has different content and there is a brand new "Dogs" deck.
    saveDeckToStorage('Cats', [{ front: 'local edit', back: 'kept' }]);
    saveDeckToStorage('Dogs', dogsDeck);

    const summary = importBackupPayload(payload, 'merge');
    expect(summary.decksImported).toBe(0);
    expect(summary.decksSkipped).toBe(1);

    // Existing "Cats" deck is untouched by the merge.
    expect(getDeckFromStorage('cats')).toEqual([{ front: 'local edit', back: 'kept' }]);
    expect(loadDeckIndex().map(d => d.slug).sort()).toEqual(['cats', 'dogs']);
  });

  it('merge mode adds a deck slug that is missing locally', () => {
    saveDeckToStorage('Cats', catsDeck);
    const payload = buildBackupPayload();

    localStorage.clear();
    saveDeckToStorage('Dogs', dogsDeck);

    const summary = importBackupPayload(payload, 'merge');
    expect(summary.decksImported).toBe(1);
    expect(summary.decksSkipped).toBe(0);
    expect(getDeckFromStorage('cats')).toEqual(catsDeck);
    expect(loadDeckIndex().map(d => d.slug).sort()).toEqual(['cats', 'dogs']);
  });

  it('rejects malformed or future-schema backup files', () => {
    expect(validateBackupPayload(null).valid).toBe(false);
    expect(validateBackupPayload({}).valid).toBe(false);
    expect(validateBackupPayload({ schemaVersion: 1, decks: 'nope', folders: [] }).valid).toBe(false);
    expect(
      validateBackupPayload({ schemaVersion: 1, decks: [{ slug: 'x' }], folders: [] }).valid
    ).toBe(false);
    expect(
      validateBackupPayload({ schemaVersion: BACKUP_SCHEMA_VERSION + 1, decks: [], folders: [] }).valid
    ).toBe(false);
    expect(validateBackupPayload({ schemaVersion: 1, decks: [], folders: [] }).valid).toBe(true);
  });

  it('names the backup file with the current date', () => {
    expect(backupFilename(new Date(2026, 8, 21))).toBe('recall-drill-backup-2026-09-21.json');
  });
});
