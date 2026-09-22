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
