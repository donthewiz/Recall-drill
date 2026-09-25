// Real, extracted-engine-backed EngineDriver -- drives selectTrial/applyAnswer/
// applyNext/initSession from src/utils/drillEngine.ts directly. Fed into the
// same runCharacterizationSuite as reference/legacyEngine.ts's driver for the
// parts of the suite that still apply to both (everything except B2, which
// LegacyEngine can never satisfy post-fix -- see characterization.engine.spec.ts).
import { DeckItem, DrillItem, LadderMode, SessionState, SessionStats } from '../../types';
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
  private revealed = false;
  private state: SessionState = {
    items: [],
    phase: 'encode',
    queue: [],
    stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    currentId: SESSION_COMPLETE_ID,
    batchIndex: 0,
    batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
    config: { encodeReps: 3, chunkDifficulty: 35, stemTolerance: true, ladderMode: 'cumulative' },
  };

  init(
    deck: DeckItem[],
    config: {
      encodeReps: number;
      chunkDifficulty?: number;
      stemTolerance?: boolean;
      ladderMode?: LadderMode;
    }
  ): void {
    const mode = config.ladderMode ?? 'cumulative';
    const items: DrillItem[] = buildItems(deck, config.chunkDifficulty ?? 35, mode);
    this.state = initSession({
      items,
      phase: 'encode',
      queue: [],
      stats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      batchStartStats: { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 },
      config: {
        encodeReps: config.encodeReps,
        chunkDifficulty: config.chunkDifficulty ?? 35,
        stemTolerance: config.stemTolerance ?? true,
        ladderMode: mode,
      },
    });
  }

  currentTrial(): DriverTrial | null {
    const trial = selectTrial(this.state);
    if (!trial) return null;
    return {
      itemId: trial.itemId,
      stage: trial.stage,
      target: trial.target,
      // C5 replaced Trial.isBlind with Trial.cue, but the shared
      // characterization suite's isBlind assertions still hold: 'none' is
      // exactly the old streak>=1 definition of blind (cycle is always
      // 'none' too, matching its old hardcoded isBlind: true), so deriving
      // it here keeps DriverTrial's shape -- and every existing assertion --
      // unchanged for both drivers.
      isBlind: trial.cue.kind === 'none',
    };
  }

  answer(typed: string): DriverAnswerResult {
    const result = applyAnswer(this.state, typed, { revealed: this.revealed });
    this.revealed = false;
    this.state = result.state;
    return { verdict: result.verdict, advance: result.advance };
  }

  showAnswer(): void {
    this.revealed = true;
  }

  // C5: a wrong verdict in the encode phase now also returns
  // advance: 'manual', but unlike the cycle phase, the engine state already
  // points at the right trial (same item/stage, streak reset) -- nothing
  // needs popping off a queue. applyNext is advanceCycleState, so calling it
  // during the encode phase would incorrectly try to advance as if `queue`
  // were a cycle queue. Only the cycle and (Phase 3) Final-check phases'
  // manual advance need it.
  next(): void {
    if (this.state.phase === 'cycle' || this.state.phase === 'final') {
      this.state = applyNext(this.state);
    }
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
