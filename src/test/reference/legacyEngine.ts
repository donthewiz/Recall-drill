// Reference re-implementation of SessionView.tsx's pre-extraction state machine
// (handleCheck / advanceEncode / advanceCycle), transcribed verbatim from
// src/components/SessionView.tsx as it exists today, minus React state/setTimeout
// scheduling (this driver applies every transition synchronously/eagerly instead
// of waiting for the setTimeout delay -- the delay never changes the resulting
// state, only when the UI renders it, so this is behavior-preserving for the
// purposes of characterizing (stage, target, streak, status) transitions).
//
// This file must NOT fix any of B1-B5; it exists to lock in current (buggy)
// behavior before extraction. Do not "improve" this file during Phase 0.
import { DeckItem, DrillItem, SessionStats } from '../../types';
import {
  norm,
  computeWordDiff,
  findAllCulpritChunks,
  splitInHalf,
  culpritHalf,
  shuffle,
  buildItems,
} from '../../utils/drillEngine';

export interface DriverTrial {
  itemId: number;
  stage: string;
  target: string;
  isBlind: boolean;
}

export interface DriverAnswerResult {
  // LegacyEngine (frozen pre-Phase-1 snapshot) only ever produces 'exact' |
  // 'wrong' -- 'revealed' (Phase 1, B2) and 'near' (Phase 2, C2) are outcomes
  // only the real engine driver can produce, since LegacyEngine's grading
  // never reads a revealed flag and never applies lenient grading.
  verdict: 'exact' | 'near' | 'wrong' | 'revealed';
  advance: 'auto' | 'manual';
}

export interface ItemSnapshot {
  stage: string;
  status: string;
  chunkIndex: number;
  chunkStreak: number;
  combineSeqIdx: number;
  combineStreak: number;
  combineMissCount: number;
  encodeStreak: number;
  cycleStreak: number;
  remediateStackLen: number;
  remediateQueueLen: number;
  remediateTopStreak: number | null;
  remediateTopMissCount: number | null;
}

export interface EngineDriver {
  init(deck: DeckItem[], config: { encodeReps: number; chunkDifficulty?: number }): void;
  currentTrial(): DriverTrial | null;
  answer(typed: string): DriverAnswerResult;
  showAnswer(): void;
  next(): void;
  snapshotItem(itemId: number): ItemSnapshot;
  stats(): SessionStats;
  isFinished(): boolean;
}

function deriveTrial(it: DrillItem): DriverTrial {
  if (it.stage === 'chunks' && it.chunks) {
    return {
      itemId: it.id,
      stage: 'chunks',
      target: it.chunks[it.chunkIndex],
      isBlind: it.chunkStreak >= 1,
    };
  }
  if (it.stage === 'combine' && it.chunks && it.combineSeq) {
    const seqItem = it.combineSeq[it.combineSeqIdx];
    const combined = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
    return {
      itemId: it.id,
      stage: 'combine',
      target: combined,
      isBlind: it.combineStreak >= 1,
    };
  }
  if (it.stage === 'remediate') {
    const rTop = it.remediateStack[it.remediateStack.length - 1];
    return {
      itemId: it.id,
      stage: 'remediate',
      target: rTop.text,
      isBlind: rTop.streak >= 1,
    };
  }
  return {
    itemId: it.id,
    stage: 'full',
    target: it.back,
    isBlind: it.encodeStreak >= 1,
  };
}

export function snapshotOf(it: DrillItem): ItemSnapshot {
  const rTop = it.remediateStack[it.remediateStack.length - 1] ?? null;
  return {
    stage: it.stage,
    status: it.status,
    chunkIndex: it.chunkIndex,
    chunkStreak: it.chunkStreak,
    combineSeqIdx: it.combineSeqIdx,
    combineStreak: it.combineStreak,
    combineMissCount: it.combineMissCount,
    encodeStreak: it.encodeStreak,
    cycleStreak: it.cycleStreak,
    remediateStackLen: it.remediateStack.length,
    remediateQueueLen: it.remediateQueue.length,
    remediateTopStreak: rTop ? rTop.streak : null,
    remediateTopMissCount: rTop ? rTop.missCount : null,
  };
}

export class LegacyEngine implements EngineDriver {
  private items: DrillItem[] = [];
  private phase: 'encode' | 'cycle' = 'encode';
  private queue: number[] = [];
  private sessionStats: SessionStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };
  private currentId = 0;
  private encodeReps = 3;
  private finished = false;

  init(deck: DeckItem[], config: { encodeReps: number; chunkDifficulty?: number }): void {
    this.encodeReps = config.encodeReps;
    this.items = buildItems(deck, config.chunkDifficulty ?? 35);
    this.sessionStats = { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 };
    this.phase = 'encode';
    this.queue = [];
    this.finished = false;
    // Mirrors SessionView's mount useEffect: initialPhase is always 'encode' for
    // a fresh session, so pick the first item via advanceEncode.
    this.advanceEncode(this.items, this.sessionStats);
  }

  currentTrial(): DriverTrial | null {
    const it = this.items.find(i => i.id === this.currentId);
    if (!it) return null;
    if (this.phase === 'cycle') {
      return { itemId: it.id, stage: 'cycle', target: it.back, isBlind: true };
    }
    return deriveTrial(it);
  }

  showAnswer(): void {
    // Matches SessionView: userRevealedAnswer is write-only from handleCheck's
    // perspective, so this driver doesn't need to thread it into answer() at all
    // (B2 preserved: a reveal never affects grading below).
  }

  next(): void {
    this.advanceCycle(this.items, this.queue, this.sessionStats);
  }

  stats(): SessionStats {
    return { ...this.sessionStats };
  }

  isFinished(): boolean {
    return this.finished;
  }

  snapshotItem(itemId: number): ItemSnapshot {
    const it = this.items.find(i => i.id === itemId);
    if (!it) throw new Error(`No item with id ${itemId}`);
    return snapshotOf(it);
  }

  private advanceEncode(updatedItems: DrillItem[], updatedStats: SessionStats): void {
    const remaining = updatedItems.filter(i => i.status === 'new' || i.status === 'encoding');
    if (!remaining.length) {
      const newQueue = shuffle(updatedItems.filter(i => i.status !== 'mastered').map(i => i.id));
      this.items = updatedItems;
      this.phase = 'cycle';
      this.queue = newQueue;
      this.advanceCycle(updatedItems, newQueue, updatedStats);
      return;
    }

    const nextItem = remaining[0];
    const newItems = updatedItems.map(i =>
      i.id === nextItem.id ? { ...i, status: 'encoding' as const } : i
    );
    this.items = newItems;
    this.currentId = nextItem.id;
  }

  private advanceCycle(
    updatedItems: DrillItem[],
    currentQueue: number[],
    updatedStats: SessionStats
  ): void {
    let q = [...currentQueue];
    if (!q.length) {
      const remaining = updatedItems.filter(i => i.status !== 'mastered');
      if (!remaining.length) {
        this.items = updatedItems;
        this.finished = true;
        return;
      }
      q = shuffle(remaining.map(i => i.id));
    }

    const nextId = q.shift()!;
    this.items = updatedItems;
    this.queue = q;
    this.currentId = nextId;
  }

  answer(typed: string): DriverAnswerResult {
    const currentItem = this.items.find(i => i.id === this.currentId);
    if (!currentItem) throw new Error('No current item');

    const nextStats = { ...this.sessionStats, attempts: this.sessionStats.attempts + 1 };
    this.sessionStats = nextStats;

    const newItems = [...this.items];
    const itIdx = newItems.findIndex(i => i.id === currentItem.id);
    const it = { ...newItems[itIdx] };

    if (this.phase === 'encode') {
      if (it.stage === 'chunks' && it.chunks) {
        const targetChunk = it.chunks[it.chunkIndex];
        const isOk = norm(typed) === norm(targetChunk);

        if (isOk) {
          it.chunkStreak++;
          if (it.chunkStreak >= this.encodeReps) {
            it.chunkIndex++;
            it.chunkStreak = 0;
            if (it.chunkIndex >= it.chunks.length) {
              it.stage = 'combine';
              it.combineSeqIdx = 0;
              it.combineStreak = 0;
            }
            newItems[itIdx] = it;
            this.items = newItems;
            this.advanceEncode(newItems, nextStats);
          } else {
            newItems[itIdx] = it;
            this.items = newItems;
          }
        } else {
          nextStats.misses++;
          it.chunkStreak = 0;
          computeWordDiff(typed, targetChunk);
          newItems[itIdx] = it;
          this.items = newItems;
        }
        return { verdict: isOk ? 'exact' : 'wrong', advance: 'auto' };
      }

      if (it.stage === 'combine' && it.chunks && it.combineSeq) {
        const seqItem = it.combineSeq[it.combineSeqIdx];
        const combinedTarget = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
        const wasBlind = it.combineStreak >= 1;
        const isOk = norm(typed) === norm(combinedTarget);

        if (isOk) {
          it.combineStreak++;
          if (wasBlind) it.combineMissCount = 0;

          if (it.combineStreak >= this.encodeReps) {
            it.combineSeqIdx++;
            it.combineStreak = 0;
            if (it.combineSeqIdx >= it.combineSeq.length) {
              it.status = 'ready';
            }
            newItems[itIdx] = it;
            this.items = newItems;
            this.advanceEncode(newItems, nextStats);
          } else {
            newItems[itIdx] = it;
            this.items = newItems;
          }
        } else {
          nextStats.misses++;
          it.combineStreak = 0;
          it.combineMissCount++;
          const windowChunkCount = seqItem.end - seqItem.start + 1;
          const missThreshold = windowChunkCount <= 2 ? 1 : 2;

          if (it.combineMissCount >= missThreshold) {
            const culprits = findAllCulpritChunks(
              typed,
              it.chunks,
              seqItem.start - 1,
              seqItem.end - 1
            );
            it.remediateStack = [{ text: it.chunks[culprits[0]], streak: 0, missCount: 0 }];
            it.remediateQueue = culprits.slice(1).map(idx => it.chunks![idx]);
            it.remediateReturnSeqIdx = it.combineSeqIdx;
            it.combineMissCount = 0;
            it.stage = 'remediate';
          } else {
            computeWordDiff(typed, combinedTarget);
          }
          newItems[itIdx] = it;
          this.items = newItems;
        }
        return { verdict: isOk ? 'exact' : 'wrong', advance: 'auto' };
      }

      if (it.stage === 'remediate') {
        const rTop = it.remediateStack[it.remediateStack.length - 1];
        const isOk = norm(typed) === norm(rTop.text);

        if (isOk) {
          rTop.streak++;
          rTop.missCount = 0;
          if (rTop.streak >= this.encodeReps) {
            it.remediateStack.pop();
            if (it.remediateStack.length === 0) {
              if (it.remediateQueue.length > 0) {
                const nextPiece = it.remediateQueue.shift()!;
                it.remediateStack = [{ text: nextPiece, streak: 0, missCount: 0 }];
                newItems[itIdx] = it;
                this.items = newItems;
              } else {
                it.stage = 'combine';
                it.combineSeqIdx = it.remediateReturnSeqIdx;
                it.combineStreak = 0;
                newItems[itIdx] = it;
                this.items = newItems;
                this.advanceEncode(newItems, nextStats);
                return { verdict: 'exact', advance: 'auto' };
              }
            } else {
              const parentLevel = it.remediateStack[it.remediateStack.length - 1];
              parentLevel.streak = 0;
              newItems[itIdx] = it;
              this.items = newItems;
            }
          } else {
            newItems[itIdx] = it;
            this.items = newItems;
          }
        } else {
          nextStats.misses++;
          rTop.streak = 0;
          rTop.missCount++;
          const rWordCount = rTop.text.split(' ').length;

          if (rTop.missCount >= 2 && rWordCount > 1) {
            const halves = splitInHalf(rTop.text);
            const culpritPiece = culpritHalf(typed, halves[0], halves[1]);
            it.remediateStack.push({ text: culpritPiece, streak: 0, missCount: 0 });
          } else {
            computeWordDiff(typed, rTop.text);
          }
          newItems[itIdx] = it;
          this.items = newItems;
        }
        return { verdict: isOk ? 'exact' : 'wrong', advance: 'auto' };
      }

      // Stage: full (short phrase <= 3 words, or chunkDifficulty >= 100)
      const isOk = norm(typed) === norm(it.back);

      if (isOk) {
        it.encodeStreak++;
        if (it.encodeStreak >= this.encodeReps) {
          it.status = 'ready';
          newItems[itIdx] = it;
          this.items = newItems;
          this.advanceEncode(newItems, nextStats);
        } else {
          newItems[itIdx] = it;
          this.items = newItems;
        }
      } else {
        nextStats.misses++;
        it.encodeStreak = 0;
        computeWordDiff(typed, it.back);
        newItems[itIdx] = it;
        this.items = newItems;
      }
      return { verdict: isOk ? 'exact' : 'wrong', advance: 'auto' };
    }

    // Phase: cycle (spaced retrieval interleaving) -- always manual advance
    const isOkCycle = norm(typed) === norm(it.back);
    const updatedQueue = [...this.queue];

    if (isOkCycle) {
      it.cycleStreak++;
      if (it.cycleStreak >= 2) {
        it.status = 'mastered';
      } else {
        updatedQueue.splice(Math.min(3, updatedQueue.length), 0, it.id);
      }
    } else {
      nextStats.misses++;
      it.cycleStreak = 0;
      computeWordDiff(typed, it.back);
      const gap = 2 + Math.floor(Math.random() * 2);
      updatedQueue.splice(Math.min(gap, updatedQueue.length), 0, it.id);
    }

    newItems[itIdx] = it;
    this.items = newItems;
    this.queue = updatedQueue;
    return { verdict: isOkCycle ? 'exact' : 'wrong', advance: 'manual' };
  }
}
