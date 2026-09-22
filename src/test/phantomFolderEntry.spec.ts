// A folder is not a deck: recordDeckUsed used to create a payload-less
// deck-index entry for a folder-practice session (its "no existing entry"
// branch runs whenever the slug isn't already in the index, regardless of
// whether a deck:<slug> payload backs it). App.tsx now guards that call for
// folder sessions, so no new phantom entry gets created; deckHasPayload
// filters out any that already exist from before that guard, everywhere a
// deck list is assembled for the user to open or practice.
import { describe, expect, it, beforeEach } from 'vitest';
import {
  recordDeckUsed,
  saveDeckToStorage,
  loadDeckIndex,
  getRecentlyUsedDecks,
  deckHasPayload,
  buildItems,
  writeBackCardEdit,
  getDeckFromStorage,
} from '../utils/drillEngine';

describe('folder practice does not create a deck-index entry', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('recordDeckUsed alone (no saveDeckToStorage call) creates a payload-less entry -- the pre-fix shape', () => {
    // This is what App.tsx's handleStartSession did for folder practice
    // before the fromFolder guard: recordDeckUsed with no matching
    // saveDeckToStorage call, since a folder has no single deck to save.
    recordDeckUsed('anatomy-101', 'Anatomy 101', 12);
    const entry = loadDeckIndex().find(d => d.slug === 'anatomy-101');
    expect(entry).toBeDefined();
    expect(deckHasPayload(entry!)).toBe(false);
  });

  it('a real deck saved through saveDeckToStorage has a payload and is not filtered', () => {
    saveDeckToStorage('Cardio', [{ front: 'Tachycardia', back: 'fast heart rate' }]);
    const entry = loadDeckIndex().find(d => d.slug === 'cardio');
    expect(deckHasPayload(entry!)).toBe(true);
  });
});

describe('deckHasPayload filters phantom entries out of every deck list', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('getRecentlyUsedDecks excludes a pre-existing phantom entry but keeps a real one', () => {
    saveDeckToStorage('Cardio', [{ front: 'Tachycardia', back: 'fast heart rate' }]);
    recordDeckUsed('anatomy-101', 'Anatomy 101', 12); // phantom: no payload

    const recent = getRecentlyUsedDecks();
    expect(recent.map(d => d.slug)).toEqual(['cardio']);
  });

  it('loadDeckIndex itself still returns the phantom entry (payload-agnostic, unlike getRecentlyUsedDecks)', () => {
    // loadDeckIndex is the low-level accessor other lookups rely on (e.g. a
    // strictPunctuation setting by slug) that don't need the deck payload
    // to exist -- only the user-facing "decks you can open" lists filter it.
    recordDeckUsed('anatomy-101', 'Anatomy 101', 12);
    expect(loadDeckIndex().some(d => d.slug === 'anatomy-101')).toBe(true);
  });

  it('a phantom entry stays filtered even after being reintroduced (e.g. via a backup import)', () => {
    // deckHasPayload re-checks storage on every call rather than deleting
    // the entry once, so it keeps working no matter how the phantom entry
    // got into deck-index.
    const now = new Date().toISOString();
    localStorage.setItem(
      'deck-index',
      JSON.stringify([{ slug: 'anatomy-101', name: 'Anatomy 101', count: 12, updatedAt: now, lastUsedAt: now }])
    );
    expect(getRecentlyUsedDecks()).toEqual([]);
  });
});

// Regression B: a real deck that happens to share its slug with a practiced
// folder's name must never receive a folder session's mid-session edit.
// The storage layer's part of that guard -- sourceDeckEditable being false
// for every folder session, regardless of what the folder is named -- is
// covered here, deliberately against a deck that DOES exist under that
// exact slug (so the guard being checked is sourceDeckEditable, not just
// "no such deck"). The other half of this regression (App.tsx resetting
// deckName/editorDeckItems together on Back to Setup, so the editor never
// pairs a folder's name with an unrelated real deck's cards and lets a
// later Save create a phantom deck) is React component state with no test
// harness in this repo; see the session report for the manual repro
// verified for that half.
describe('folder practice never writes a mid-session edit under the folder name/slug', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('sourceDeckEditable false blocks the write even when a deck already exists at that slug', () => {
    const original = [{ front: 'RealDeckCard1', back: 'real-back-1' }];
    saveDeckToStorage('My Test Folder', original); // slug collision, deliberately
    const items = buildItems(original, 35, 'cumulative', undefined, undefined, false);

    const written = writeBackCardEdit('My Test Folder', false, items[0], {
      front: 'RealDeckCard1',
      back: 'edited during folder practice',
    });

    expect(written).toBeNull();
    expect(getDeckFromStorage('my-test-folder')).toEqual(original);
  });
});
