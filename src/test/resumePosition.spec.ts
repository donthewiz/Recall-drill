// @vitest-environment jsdom
// Resume position (2026-09-26): a save records currentId, and a resumed
// encode phase picks up on the card that was on screen instead of the
// batch's first unfinished card. Without it, leaving a chunked card mid-build
// (End session, reload, closing the app) served the other cards first and
// then dropped back into a bare chunk / remediation piece.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  buildItems,
  getSessionState,
  initSession,
  saveSessionState,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { DeckItem, SessionState, Trial } from '../types';
import { CHUNK_DIFFICULTY, FOUR_CHUNK_BACK } from './fixtures/deck';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

const DECK: DeckItem[] = [
  { front: 'short A', back: 'alpha one' },
  { front: 'short B', back: 'beta two' },
  { front: 'long', back: FOUR_CHUNK_BACK },
  { front: 'short C', back: 'gamma three' },
];
const LONG_ID = 2;

function freshState(): SessionState {
  return initSession({
    items: buildItems(DECK, CHUNK_DIFFICULTY, 'cumulative', undefined, undefined, false),
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps: 3, chunkDifficulty: CHUNK_DIFFICULTY, stemTolerance: true, ladderMode: 'cumulative' },
  });
}

const correct = (t: Trial) => (t.cue.kind === 'present' ? '' : t.target);

// Plays correctly (answering with `answerFor` where it returns a string)
// until `stop` is true, and returns that state.
function playUntil(
  stop: (s: SessionState) => boolean,
  answerFor: (t: Trial, s: SessionState) => string | undefined = () => undefined
): SessionState {
  let s = freshState();
  for (let guard = 0; !stop(s); guard++) {
    expect(guard).toBeLessThan(500);
    const t = selectTrial(s)!;
    s = applyAnswer(s, answerFor(t, s) ?? correct(t), { revealed: false }).state;
  }
  return s;
}

// What SessionView's persistState writes and a resume reads back: a JSON
// round-trip of the state, then initSession on it.
const resume = (s: SessionState, currentId = s.currentId) =>
  initSession({ ...JSON.parse(JSON.stringify(s)), currentId });

const long = (s: SessionState) => s.items.find(i => i.id === LONG_ID)!;

describe('resume position', () => {
  it('resumes a mid-remediation card on the same card and piece', () => {
    let missed = false;
    const saved = playUntil(
      s => long(s).stage === 'remediate' && long(s).remediateStack[0]?.streak === 1,
      (t, s) => {
        if (!missed && t.itemId === LONG_ID && t.stage === 'combine') {
          missed = true;
          return 'large green zzz';
        }
        return undefined;
      }
    );
    expect(saved.currentId).toBe(LONG_ID);
    const before = selectTrial(saved)!;

    const after = selectTrial(resume(saved))!;
    expect(after.itemId).toBe(LONG_ID);
    expect(after.stage).toBe(before.stage);
    expect(after.target).toBe(before.target);

    // Control: without a saved currentId (an old save), the resume starts at
    // the batch's first unfinished card instead.
    expect(selectTrial(resume(saved, SESSION_COMPLETE_ID))!.itemId).not.toBe(LONG_ID);
  });

  it('resumes a mid-chunks card on the same chunk', () => {
    const saved = playUntil(s => long(s).stage === 'chunks' && long(s).chunkIndex === 1);
    const before = selectTrial(saved)!;
    const after = selectTrial(resume(saved))!;
    expect(after.itemId).toBe(LONG_ID);
    expect(after.stage).toBe('chunks');
    expect(after.target).toBe(before.target);
    expect(after.cue.kind).toBe(before.cue.kind);
  });

  it('falls back to rotation when the saved card is no longer unfinished', () => {
    const saved = playUntil(s => long(s).status === 'ready' && s.phase === 'encode');
    const resumed = resume(saved, LONG_ID);
    const t = selectTrial(resumed)!;
    expect(t.itemId).not.toBe(LONG_ID);
    const it = resumed.items.find(i => i.id === t.itemId)!;
    expect(it.status === 'ready' || it.status === 'mastered').toBe(false);
  });

  it('a fresh start is unchanged: first card in deck order', () => {
    expect(selectTrial(freshState())!.itemId).toBe(0);
  });

  it('currentId survives the storage round-trip', () => {
    saveSessionState('resume-position', {
      deckName: 'resume-position',
      phase: 'encode',
      queue: [],
      stats: { ...zeroStats },
      items: [],
      encodeReps: 3,
      currentId: 7,
    });
    expect(getSessionState('resume-position')?.currentId).toBe(7);
  });
});
