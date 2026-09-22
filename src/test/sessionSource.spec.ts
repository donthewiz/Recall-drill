// Session source persistence: a saved session records whether it maps onto
// one saved deck (sourceDeckEditable), so a resumed folder-practice session
// stays session-only instead of defaulting to editable. Round-trips through
// the same saveSessionState/getSessionState localStorage path the app uses,
// then checks write-back actually happens (or doesn't) via writeBackCardEdit.
import { describe, expect, it, beforeEach } from 'vitest';
import {
  buildItems,
  getDeckFromStorage,
  getSessionState,
  resolveSourceDeckEditable,
  saveDeckToStorage,
  saveSessionState,
  writeBackCardEdit,
} from '../utils/drillEngine';
import type { DeckItem, SavedSessionState } from '../types';

const deck: DeckItem[] = [
  { front: 'Tachycardia', back: 'fast heart rate' },
  { front: '-itis', back: 'inflammation' },
];
const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

// Deck name doubles as the session slug -- for folder practice that's the
// folder's name, which here deliberately collides with a real deck's slug
// and card text: exactly the case the old `true` default would write into.
const NAME = 'Cardio';

function savedSession(extra: Partial<SavedSessionState>): SavedSessionState {
  return {
    deckName: NAME,
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    items: buildItems(deck, 35, 'cumulative', undefined, undefined, false),
    encodeReps: 3,
    ...extra,
  };
}

// Save -> restore through localStorage, resolve editability the way
// App.handleResumeSession does, then attempt the card-0 write-back.
function resumeAndEdit(saved: SavedSessionState): { editable: boolean; written: DeckItem[] | null } {
  saveSessionState('cardio', saved);
  const restored = getSessionState('cardio')!;
  const editable = resolveSourceDeckEditable(restored);
  const before = restored.items.find(i => i.id === 0)!;
  const written = writeBackCardEdit(restored.deckName, editable, before, { front: 'Tachycardia', back: 'rapid heart rate' });
  return { editable, written };
}

describe('resumed session source: sourceDeckEditable round-trip', () => {
  beforeEach(() => {
    localStorage.clear();
    saveDeckToStorage(NAME, deck);
  });

  it('a folder-practice session saved -> restored is non-editable and writes nothing back', () => {
    const { editable, written } = resumeAndEdit(savedSession({ sourceDeckEditable: false }));
    expect(editable).toBe(false);
    expect(written).toBeNull();
    expect(getDeckFromStorage('cardio')).toEqual(deck);
  });

  it('a single-deck session saved -> restored is editable and writes the edit back', () => {
    const { editable, written } = resumeAndEdit(savedSession({ sourceDeckEditable: true }));
    expect(editable).toBe(true);
    expect(written?.[0]).toEqual({ front: 'Tachycardia', back: 'rapid heart rate' });
    expect(getDeckFromStorage('cardio')?.[0].back).toBe('rapid heart rate');
    expect(getDeckFromStorage('cardio')?.[1]).toEqual(deck[1]);
  });

  it('a legacy save with no sourceDeckEditable field is non-editable and writes nothing back', () => {
    // A real pre-field payload: the key is absent from the stored JSON, not
    // present-and-undefined.
    const legacy = savedSession({});
    expect('sourceDeckEditable' in legacy).toBe(false);
    const { editable, written } = resumeAndEdit(legacy);
    expect(getSessionState('cardio')!.sourceDeckEditable).toBeUndefined();
    expect(editable).toBe(false);
    expect(written).toBeNull();
    expect(getDeckFromStorage('cardio')).toEqual(deck);
  });

  it('even when editable, nothing is written if the deck card no longer matches the pre-edit text', () => {
    saveDeckToStorage(NAME, [{ front: 'Tachycardia', back: 'changed elsewhere' }, deck[1]]);
    const { editable, written } = resumeAndEdit(savedSession({ sourceDeckEditable: true }));
    expect(editable).toBe(true);
    expect(written).toBeNull();
    expect(getDeckFromStorage('cardio')?.[0].back).toBe('changed elsewhere');
  });
});
