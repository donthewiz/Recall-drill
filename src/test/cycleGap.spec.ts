// Within-session spacing, Phase 1 (2026-09-24): a first-correct cycle card
// now reinserts at the END of the current pass, not a fixed gap of 3 --
// maximizing the trials separating it from its mastering answer. See
// docs/V2-HANDOFF.md's "Within-session spacing" section for the rationale
// (Karpicke & Bauernschmidt 2011: spacing between recalls tripled retention).
import { describe, expect, it } from 'vitest';
import { applyAnswer, applyNext, buildItems, initSession } from '../utils/drillEngine';
import type { DeckItem, SessionState } from '../types';

const zeroStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };

function makeShortDeck(count: number): DeckItem[] {
  return Array.from({ length: count }, (_, i) => ({ front: `Q${i}`, back: `answer${i}` }));
}

// 5-card, full-stage (short answers never chunk), single-batch deck, already
// 'ready' -- initSession builds the first shuffled cycle pass directly.
function cycleState(count: number): SessionState {
  const items = buildItems(makeShortDeck(count), 35, 'cumulative', count).map(it => ({
    ...it,
    status: 'ready' as const,
  }));
  return initSession({
    items,
    phase: 'cycle',
    queue: [],
    stats: zeroStats,
    currentId: -1,
    batchIndex: 0,
    batchStartStats: zeroStats,
    config: {
      encodeReps: 1,
      chunkDifficulty: 35,
      stemTolerance: true,
      ladderMode: 'cumulative',
      batchSize: count,
      cycleOrder: 'shuffled',
    },
  });
}

describe('Phase 1: cycle reinsertion gap -- first-correct goes to the end of the pass', () => {
  it('every first-correct card is not served again until every other queued card has been served (perfect learner)', () => {
    let s = cycleState(5);

    // For each id, the set of other ids that were still in the queue at the
    // moment it got its first correct answer -- all of them must be served
    // (become currentId at least once) before this id is served again.
    const pendingRequirements = new Map<number, Set<number>>();
    // The one card exempt from the rule: it got its first correct answer
    // while the queue was already empty (the last unmastered card in a
    // pass), so it repeats at lag 0 until Phase 3's Final check.
    let exemptCount = 0;

    let guard = 0;
    while (s.items.some(i => i.status !== 'mastered')) {
      expect(guard++).toBeLessThan(100); // safety net against a runaway loop

      const currentId = s.currentId;
      const before = s.items.find(i => i.id === currentId)!;
      expect(before.cycleStreak).toBeLessThan(2); // never re-served once mastered

      if (pendingRequirements.has(currentId)) {
        // This id is being served again after its first correct -- every
        // other id that was queued at that moment must already be gone.
        expect(pendingRequirements.get(currentId)!.size).toBe(0);
        pendingRequirements.delete(currentId);
      }
      // Mark this id as served against every other id's still-open requirement.
      for (const req of pendingRequirements.values()) req.delete(currentId);

      const queueAtThisMoment = [...s.queue];
      const res = applyAnswer(s, before.back, { revealed: false });
      const after = res.state.items.find(i => i.id === currentId)!;

      if (before.cycleStreak === 0 && after.cycleStreak === 1) {
        if (queueAtThisMoment.length === 0) {
          exemptCount++;
        } else {
          pendingRequirements.set(currentId, new Set(queueAtThisMoment));
        }
      }

      s = applyNext(res.state);
    }

    // With 5 cards needing 2 correct answers each and a perfect learner, the
    // reinsert-at-the-end rule produces a strict round robin (every card's
    // first-correct pass fully precedes anyone's mastering pass), so the
    // lag-0 exception never actually fires here -- but the loop above must
    // not treat that as a failure if it ever does (at most one card, the
    // last one left in a pass, per the documented limitation).
    expect(s.items.every(i => i.status === 'mastered')).toBe(true);
    expect(exemptCount).toBeLessThanOrEqual(1);
  });
});
