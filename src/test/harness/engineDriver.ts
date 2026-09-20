// Real, extracted-engine-backed EngineDriver -- drives selectTrial/applyAnswer/
// applyNext/initSession from src/utils/drillEngine.ts directly. Fed into the
// same runCharacterizationSuite as reference/legacyEngine.ts's driver; both
// must produce identical assertions, proving the extraction preserved behavior.
import { DeckItem, DrillItem, SessionState, SessionStats } from '../../types';
import {
  buildItems,
  selectTrial,
  applyAnswer,
  applyNext,
  initSession,
  SESSION_COMPLETE_ID,
} from '../../utils/drillEngine';
import type { DriverAnswerResult, DriverTrial, EngineDriver, ItemSnapshot } from '../reference/legacyEngine';
import { snapshotOf } from '../reference/legacyEngine';

export class RealEngineDriver implements EngineDriver {
  private state: SessionState = {
    items: [],
    phase: 'encode',
    queue: [],
    stats: { attempts: 0, misses: 0 },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    config: { encodeReps: 3, chunkDifficulty: 35 },
  };

  init(deck: DeckItem[], config: { encodeReps: number; chunkDifficulty?: number }): void {
    const items: DrillItem[] = buildItems(deck, config.chunkDifficulty ?? 35);
    this.state = initSession({
      items,
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      config: { encodeReps: config.encodeReps, chunkDifficulty: config.chunkDifficulty ?? 35 },
    });
  }

  currentTrial(): DriverTrial | null {
    const trial = selectTrial(this.state);
    if (!trial) return null;
    return {
      itemId: trial.itemId,
      stage: trial.stage,
      target: trial.target,
      isBlind: trial.isBlind,
    };
  }

  answer(typed: string): DriverAnswerResult {
    const result = applyAnswer(this.state, typed, { revealed: false });
    this.state = result.state;
    return { verdict: result.verdict, advance: result.advance };
  }

  showAnswer(): void {
    // No-op, matching legacyEngine.ts: userRevealedAnswer never affects
    // grading in applyAnswer (B2 preserved).
  }

  next(): void {
    this.state = applyNext(this.state);
  }

  snapshotItem(itemId: number): ItemSnapshot {
    const it = this.state.items.find(i => i.id === itemId);
    if (!it) throw new Error(`No item with id ${itemId}`);
    return snapshotOf(it);
  }

  stats(): SessionStats {
    return { ...this.state.stats };
  }

  isFinished(): boolean {
    return this.state.currentId === SESSION_COMPLETE_ID;
  }
}
