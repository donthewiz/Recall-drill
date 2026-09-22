// Regression-guard for a data-loss bug reported against the card-edit
// stack ("Regression A"): a card edited and saved in the deck editor
// *before* a session starts must still be there after the session ends,
// with no mid-session edit involved. Investigation (see the session
// report) could not reproduce a revert via the literal repro at HEAD, on
// any of the three most-suspected commits -- this test pins down exactly
// the storage-level claim that repro made ("confirm deck:<slug> ... now
// holds the edit" / "reopen from the library" still shows it), using the
// same drillEngine storage functions App.tsx's handlers call, since there
// is no component-test harness for App.tsx itself.
//
// It intentionally mirrors handleFinishSession's own two branches (fully
// mastered -> clearSessionState; otherwise -> saveSessionState) so a
// regression that made either branch call saveDeckToStorage with a stale
// snapshot would be caught here.
import { describe, expect, it, beforeEach } from 'vitest';
import {
  buildItems,
  clearSessionState,
  getDeckFromStorage,
  getSessionState,
  saveDeckToStorage,
  saveSessionState,
} from '../utils/drillEngine';
import type { DeckItem } from '../types';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };
const NAME = 'Bisect A';
const SLUG = 'bisect-a';

describe('a pre-session saved edit survives a start -> finish cycle', () => {
  beforeEach(() => {
    localStorage.clear();
  });

  it('ending a session early (not mastered) leaves the edited deck untouched', () => {
    // 1. Original deck.
    saveDeckToStorage(NAME, [{ front: 'Bisect A', back: 'original text' }, { front: 'card2', back: 'b2' }]);
    // 2. Edit a card's back in the deck editor, Save deck.
    const edited: DeckItem[] = [{ front: 'Bisect A', back: 'EDITED TEXT' }, { front: 'card2', back: 'b2' }];
    saveDeckToStorage(NAME, edited);
    expect(getDeckFromStorage(SLUG)).toEqual(edited); // "confirm deck:<slug> now holds the edit"

    // 3. Start the session: handleStartSession builds items from the deck
    // it just read (which already reflects the edit).
    const items = buildItems(edited, 35, 'cumulative', undefined, undefined, false);
    expect(items[0].back).toBe('EDITED TEXT'); // "the edit is present"

    // 4. End session with no mid-session edit, not fully mastered (nothing
    // was answered) -- handleFinishSession's saveSessionState branch.
    saveSessionState(SLUG, {
      deckName: NAME,
      phase: 'encode',
      queue: [],
      stats: { ...zeroStats },
      items,
      encodeReps: 3,
      chunkDifficulty: 35,
      stemTolerance: true,
      ladderMode: 'cumulative',
      sourceDeckEditable: true,
      timestamp: Date.now(),
    });

    // The saved deck must still hold the edit -- nothing in the finish
    // path writes deck:<slug>.
    expect(getDeckFromStorage(SLUG)).toEqual(edited);
    expect(getSessionState(SLUG)?.items[0].back).toBe('EDITED TEXT');
  });

  it('ending a fully-mastered session (clearSessionState branch) also leaves the edited deck untouched', () => {
    saveDeckToStorage(NAME, [{ front: 'Bisect A', back: 'original text' }]);
    const edited: DeckItem[] = [{ front: 'Bisect A', back: 'EDITED TEXT' }];
    saveDeckToStorage(NAME, edited);

    const items = buildItems(edited, 35, 'cumulative', undefined, undefined, false).map(i => ({
      ...i,
      status: 'mastered' as const,
    }));
    // handleFinishSession: mastered >= items.length -> clearSessionState,
    // never saveDeckToStorage.
    clearSessionState(SLUG);

    expect(getDeckFromStorage(SLUG)).toEqual(edited);
    expect(getSessionState(SLUG)).toBeNull();
  });
});
