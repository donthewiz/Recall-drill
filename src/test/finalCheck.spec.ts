// Phase 3 (Final check, within-session spacing, 2026-09-24) tests.
//   - Final check covers every card exactly once for a perfect learner.
//   - A miss requeues the card to the end; the session doesn't end until
//     it's answered correctly.
//   - A reveal isn't a miss but counts in finalMisses.
//   - Save -> resume mid-Final-check restores the queue and the finalDone
//     flags (including the resume safety net for a card that was mid-trial,
//     and so missing from the persisted queue, when the session was saved).
//   - An old save (no finalDone/finalMisses at all) resumes fine.
import { describe, expect, it } from 'vitest';
import {
  applyAnswer,
  applyNext,
  buildItems,
  computeCumulativeColdStartMultiplier,
  initSession,
  normalizeItem,
  resolveBatchConfig,
  selectTrial,
  SESSION_COMPLETE_ID,
} from '../utils/drillEngine';
import type { DeckItem, SavedSessionState, SessionState } from '../types';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function makeDeck(count: number): DeckItem[] {
  return Array.from({ length: count }, (_, i) => ({ front: `Q${i}`, back: `answer${i}` }));
}

function freshState(items: ReturnType<typeof buildItems>, encodeReps = 1): SessionState {
  return initSession({
    items,
    phase: 'encode',
    queue: [],
    stats: { ...zeroStats },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { ...zeroStats },
    config: { encodeReps, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' },
  });
}

// Drives a perfect (always correct) learner from 'encode' through 'cycle',
// stopping the instant phase becomes 'final' -- nothing in the Final check
// itself has been answered yet.
function driveToFinalCheck(state: SessionState): SessionState {
  let s = state;
  for (let guard = 0; s.phase !== 'final'; guard++) {
    if (guard > 2000) throw new Error('never reached the Final check');
    const trial = selectTrial(s)!;
    const typed = trial.cue.kind === 'present' ? '' : trial.target;
    const res = applyAnswer(s, typed, { revealed: false });
    s = res.advance === 'manual' && res.state.phase === 'cycle' ? applyNext(res.state) : res.state;
  }
  return s;
}

// One correct Final-check answer, including the manual advance -- every
// 'final'-phase result is advance: 'manual', so this always calls applyNext.
function answerCorrectAndAdvance(s: SessionState): SessionState {
  const trial = selectTrial(s)!;
  const res = applyAnswer(s, trial.target, { revealed: false });
  return applyNext(res.state);
}

describe('Final check: covers every card exactly once (perfect learner)', () => {
  it('a shuffled, cue-free pass serves each item exactly once, then the session completes', () => {
    const items = buildItems(makeDeck(6), 35, 'cumulative');
    let s = driveToFinalCheck(freshState(items));
    expect(s.phase).toBe('final');
    expect(s.items.every(i => i.status === 'mastered')).toBe(true);
    expect(s.items.every(i => !i.finalDone)).toBe(true);

    const served: number[] = [];
    for (let guard = 0; s.currentId !== SESSION_COMPLETE_ID; guard++) {
      if (guard > 100) throw new Error('Final check never completed');
      const trial = selectTrial(s)!;
      expect(trial.stage).toBe('final');
      expect(trial.cue).toEqual({ kind: 'none' });
      expect(trial.detail).toBe(`Final check • ${served.length + 1} of ${items.length}`);
      served.push(trial.itemId);
      s = answerCorrectAndAdvance(s);
    }

    expect(served.length).toBe(items.length);
    expect(new Set(served).size).toBe(items.length); // each id exactly once
    expect(served.slice().sort((a, b) => a - b)).toEqual(items.map(i => i.id).sort((a, b) => a - b));
    expect(s.phase).toBe('final');
    expect(s.items.every(i => i.finalDone)).toBe(true);
    // Phase 3 never touches status/cycleStreak.
    expect(s.items.every(i => i.status === 'mastered' && i.cycleStreak === 2)).toBe(true);
  });

  it('the "k of N" counter reads N of N right after the last card\'s correct answer, before Continue is clicked', () => {
    // Regression: SessionView commits a manual-advance result to state
    // immediately on Check, not just on Continue (see handleCheck) -- so by
    // the time the last card's own "Correct!" feedback is showing,
    // its finalDone is already true in state while selectTrial is still
    // deriving that SAME trial (currentId hasn't advanced yet). Counting
    // the just-answered card in `doneCount` produced "N+1 of N" until
    // Continue was clicked.
    const items = buildItems(makeDeck(3), 35, 'cumulative');
    let s = driveToFinalCheck(freshState(items));
    for (let i = 0; i < items.length - 1; i++) s = answerCorrectAndAdvance(s);

    const lastTrial = selectTrial(s)!;
    expect(lastTrial.detail).toBe(`Final check • ${items.length} of ${items.length}`);

    const res = applyAnswer(s, lastTrial.target, { revealed: false });
    expect(res.state.items.find(i => i.id === lastTrial.itemId)!.finalDone).toBe(true);
    // Still showing the same (just-answered) trial -- currentId hasn't
    // advanced (that needs applyNext, called on Continue) -- and it must
    // still read N of N, not N+1 of N.
    expect(selectTrial(res.state)).toMatchObject({
      itemId: lastTrial.itemId,
      detail: `Final check • ${items.length} of ${items.length}`,
    });
  });
});

describe('Final check: a miss requeues the card to the end, not lost', () => {
  it('a wrong answer comes back only after every other pending card, and the session waits for it', () => {
    const items = buildItems(makeDeck(4), 35, 'cumulative');
    const s0 = driveToFinalCheck(freshState(items));

    const missedId = s0.currentId;
    const otherIds = [...s0.queue];
    expect(otherIds.length).toBe(3);

    const res = applyAnswer(s0, 'totally wrong', { revealed: false });
    expect(res.verdict).toBe('wrong');
    expect(res.advance).toBe('manual');
    const missedItem = res.state.items.find(i => i.id === missedId)!;
    expect(missedItem.finalDone).not.toBe(true);
    expect(missedItem.finalMisses).toBe(1);
    expect(missedItem.status).toBe('mastered'); // untouched
    expect(res.state.stats.misses).toBe(s0.stats.misses + 1);
    // Pushed to the END -- every other still-pending id comes first.
    expect(res.state.queue).toEqual([...otherIds, missedId]);

    let s = applyNext(res.state);
    for (const id of otherIds) {
      expect(s.currentId).toBe(id);
      s = answerCorrectAndAdvance(s);
    }
    // Only now does the missed card come back -- the session did not end
    // while it was still unanswered.
    expect(s.currentId).toBe(missedId);
    expect(s.phase).toBe('final');

    s = answerCorrectAndAdvance(s);
    expect(s.currentId).toBe(SESSION_COMPLETE_ID);
    expect(s.items.find(i => i.id === missedId)!.finalDone).toBe(true);
  });
});

describe('Final check: a reveal is not a miss but counts in finalMisses', () => {
  it('increments finalMisses, leaves stats.misses alone, and requeues to the end', () => {
    const items = buildItems(makeDeck(3), 35, 'cumulative');
    const s = driveToFinalCheck(freshState(items));
    const revealedId = s.currentId;
    const otherIds = [...s.queue];

    const res = applyAnswer(s, '', { revealed: true });
    expect(res.verdict).toBe('revealed');
    expect(res.advance).toBe('manual');
    expect(res.state.stats.misses).toBe(s.stats.misses); // not a miss
    const it = res.state.items.find(i => i.id === revealedId)!;
    expect(it.finalMisses).toBe(1);
    expect(it.finalDone).not.toBe(true);
    expect(res.state.queue).toEqual([...otherIds, revealedId]);
  });
});

describe('Final check: save -> resume restores the queue and finalDone flags', () => {
  it('a mid-Final-check resume preserves finalDone and still tests the card that was in flight at save time', () => {
    const items = buildItems(makeDeck(5), 35, 'cumulative');
    let s = driveToFinalCheck(freshState(items));

    // Answer two cards correctly, leaving the rest -- including the one
    // currently shown -- pending.
    s = answerCorrectAndAdvance(s);
    s = answerCorrectAndAdvance(s);
    const doneIds = s.items.filter(i => i.finalDone).map(i => i.id).sort((a, b) => a - b);
    expect(doneIds.length).toBe(2);
    const inFlightId = s.currentId;

    // Mirrors SessionView's persistState -> App.handleResumeSession round
    // trip (see c3.spec.ts's equivalent for 'batch-done'). s.queue already
    // excludes inFlightId, the same way a cycle-phase mid-trial save does --
    // it was already popped off before this render.
    const saved: SavedSessionState = {
      deckName: 'Test deck',
      phase: s.phase,
      queue: s.queue,
      stats: s.stats,
      items: s.items,
      encodeReps: s.config.encodeReps,
      chunkDifficulty: s.config.chunkDifficulty,
      stemTolerance: s.config.stemTolerance,
      ladderMode: s.config.ladderMode,
      batchIndex: s.batchIndex,
      batchSize: s.config.batchSize,
      batchStartStats: s.batchStartStats,
      timestamp: Date.now(),
    };
    const reloaded: SavedSessionState = JSON.parse(JSON.stringify(saved));
    expect(reloaded.queue).not.toContain(inFlightId);

    const mode = reloaded.ladderMode ?? 'cumulative';
    const normalizedItems = reloaded.items.map(it => normalizeItem(it, mode));
    const { batchIndex, batchSize } = resolveBatchConfig(reloaded, normalizedItems);
    const resumed: SessionState = initSession({
      items: normalizedItems,
      phase: reloaded.phase,
      queue: reloaded.queue,
      stats: reloaded.stats,
      currentId: SESSION_COMPLETE_ID,
      batchIndex,
      batchStartStats: reloaded.batchStartStats ?? reloaded.stats,
      config: {
        encodeReps: reloaded.encodeReps,
        chunkDifficulty: reloaded.chunkDifficulty ?? 35,
        stemTolerance: reloaded.stemTolerance ?? true,
        ladderMode: mode,
        batchSize,
      },
    });

    expect(resumed.phase).toBe('final');
    expect(resumed.items.filter(i => i.finalDone).map(i => i.id).sort((a, b) => a - b)).toEqual(doneIds);

    // Drive to completion -- every still-pending card, including the one
    // that was in flight at save time, must be served before it ends (the
    // resume safety net in advanceCycleState).
    let cur = resumed;
    const servedAfterResume = new Set<number>();
    for (let guard = 0; cur.currentId !== SESSION_COMPLETE_ID; guard++) {
      if (guard > 100) throw new Error('resumed Final check never completed');
      servedAfterResume.add(cur.currentId);
      cur = answerCorrectAndAdvance(cur);
    }
    const stillPendingIds = items.map(i => i.id).filter(id => !doneIds.includes(id));
    for (const id of stillPendingIds) expect(servedAfterResume.has(id)).toBe(true);
    expect(servedAfterResume.has(inFlightId)).toBe(true);
    expect(cur.items.every(i => i.finalDone)).toBe(true);
  });

  it('an old save with no finalDone/finalMisses on any item resumes fine', () => {
    const items = buildItems(makeDeck(3), 35, 'cumulative');
    const s = driveToFinalCheck(freshState(items));

    // Simulate a pre-Phase-3 payload: an old save's items never had these
    // keys at all.
    const strippedItems = s.items.map(({ finalDone: _fd, finalMisses: _fm, ...rest }) => rest);
    const normalizedItems = strippedItems.map(it => normalizeItem(it, 'cumulative'));
    expect(normalizedItems.every(i => i.finalDone === undefined && i.finalMisses === undefined)).toBe(true);

    const resumed: SessionState = initSession({
      items: normalizedItems,
      phase: 'final',
      queue: s.queue,
      stats: s.stats,
      currentId: SESSION_COMPLETE_ID,
      batchIndex: s.batchIndex,
      batchStartStats: s.batchStartStats,
      config: s.config,
    });

    expect(resumed.phase).toBe('final');
    expect(selectTrial(resumed)).not.toBeNull();

    let cur = resumed;
    for (let guard = 0; cur.currentId !== SESSION_COMPLETE_ID; guard++) {
      if (guard > 100) throw new Error('never completed');
      cur = answerCorrectAndAdvance(cur);
    }
    expect(cur.items.every(i => i.finalDone)).toBe(true);
  });
});

describe('Final check: computeCumulativeColdStartMultiplier stays in sync with the floor', () => {
  it('reads exactly 1 for a perfect learner throughout -- at the start of the Final check, partway through it, and once it completes', () => {
    // Regression: the numerator (completedAttempts) used to keep growing
    // with every in-progress Final-check trial while the denominator
    // (minTrials) excluded the Final check's cost entirely until it was
    // fully done -- inflating the multiplier above 1 for a perfect learner
    // partway through. finalCheckStartAttempts freezes the numerator at the
    // same "Final check not counted yet" point the denominator is at.
    const items = buildItems(makeDeck(4), 35, 'cumulative');
    let s = driveToFinalCheck(freshState(items));
    expect(s.phase).toBe('final');
    expect(computeCumulativeColdStartMultiplier(s)).toBeCloseTo(1, 10);

    s = answerCorrectAndAdvance(s);
    s = answerCorrectAndAdvance(s);
    expect(s.items.filter(i => i.finalDone).length).toBe(2);
    expect(computeCumulativeColdStartMultiplier(s)).toBeCloseTo(1, 10);

    s = answerCorrectAndAdvance(s);
    s = answerCorrectAndAdvance(s);
    expect(s.currentId).toBe(SESSION_COMPLETE_ID);
    expect(computeCumulativeColdStartMultiplier(s)).toBeCloseTo(1, 10);
  });
});
