import React, { useEffect, useRef, useState } from 'react';
import { CycleOrder, DeckItem, DrillItem, Feedback, LadderMode, SessionState, SessionStats, Verdict } from '../types';
import {
  slugify,
  saveSessionState,
  writeBackCardEdit,
  editCurrentItem,
  selectTrial,
  applyAnswer,
  applyNext,
  advanceToNextBatch,
  computeBatchSummary,
  computeSessionProgress,
  partitionIntoBatches,
  initSession,
  SESSION_COMPLETE_ID,
  DWELL_MS,
  computeCumulativeColdStartMultiplier,
  computeRemainingColdStartRange,
  formatColdStartRange,
  pickColdStartDeckShape,
  saveColdStartHistory,
} from '../utils/drillEngine';
import { Check, CheckCheck, ArrowRight, Eye, LogOut, CheckCircle2, Save, Pencil } from 'lucide-react';

interface SessionViewProps {
  deckName: string;
  initialItems: DrillItem[];
  // C3: 'batch-done' resumes a session saved ("Save and stop") exactly on
  // the interstitial between batches -- straight back onto it.
  initialPhase: 'encode' | 'cycle' | 'batch-done';
  initialQueue: number[];
  initialStats: SessionStats;
  encodeReps: number;
  chunkDifficulty?: number;
  stemTolerance?: boolean;
  ladderMode?: LadderMode;
  strictPunctuation?: boolean;
  cycleOrder?: CycleOrder;
  // C3: undefined/0/>=deck size all mean "whole deck as one batch" -- see
  // partitionIntoBatches. batchIndex/batchStartStats resume mid-batch state;
  // both default to session-start values for a brand new session.
  batchSize?: number;
  initialBatchIndex?: number;
  initialBatchStartStats?: SessionStats;
  onFinishSession: (state: SessionState) => void;
  // Whether a mid-session card edit may also be written back to the saved
  // deck named deckName. False for folder practice, which has no single
  // source deck.
  sourceDeckEditable: boolean;
  // Called with the whole updated deck after an edit was written back, so
  // App can refresh what the deck editor reseeds from.
  onDeckCardEdited: (items: DeckItem[]) => void;
}

// Stage-specific placeholder hint shown while blind (no cue text visible).
const BLIND_PLACEHOLDER: Record<string, string> = {
  chunks: 'Type this part from memory...',
  combine: 'Type it from memory...',
  remediate: 'Type this from memory...',
  full: 'Type the full answer from memory...',
  cycle: 'Type the answer from memory...',
};

export const SessionView: React.FC<SessionViewProps> = ({
  deckName,
  initialItems,
  initialPhase,
  initialQueue,
  initialStats,
  encodeReps,
  chunkDifficulty = 35,
  stemTolerance = true,
  ladderMode = 'cumulative',
  strictPunctuation = false,
  cycleOrder = 'shuffled',
  batchSize,
  initialBatchIndex = 0,
  initialBatchStartStats,
  onFinishSession,
  sourceDeckEditable,
  onDeckCardEdited,
}) => {
  const [sessionState, setSessionState] = useState<SessionState>(() =>
    initSession({
      items: initialItems,
      phase: initialPhase,
      queue: initialQueue,
      stats: initialStats,
      currentId: SESSION_COMPLETE_ID,
      batchIndex: initialBatchIndex,
      batchStartStats: initialBatchStartStats ?? initialStats,
      config: { encodeReps, chunkDifficulty, stemTolerance, ladderMode, strictPunctuation, batchSize, cycleOrder },
    })
  );
  const [typedValue, setTypedValue] = useState('');
  const [showNextBtn, setShowNextBtn] = useState(false);
  const [userRevealedAnswer, setUserRevealedAnswer] = useState(false);
  const [feedback, setFeedback] = useState<Feedback | null>(null);
  // C2: tracks the verdict of the currently-displayed feedback, so the
  // "Count as correct" override can be offered only while a 'wrong' verdict
  // is still showing (i.e. before its dwell timer commits the miss).
  const [lastVerdict, setLastVerdict] = useState<Verdict | null>(null);
  const [flash, setFlash] = useState<'idle' | 'success' | 'danger'>('idle');
  const [isProcessing, setIsProcessing] = useState(false);
  // Mid-session card editor. editRevealsOnClose: the editor was opened while
  // an answer was still pending, so it showed the learner the full answer --
  // closing it without a restart marks the attempt revealed.
  const [isEditing, setIsEditing] = useState(false);
  const [editFront, setEditFront] = useState('');
  const [editBack, setEditBack] = useState('');
  const [editExtra, setEditExtra] = useState('');
  const [editRevealsOnClose, setEditRevealsOnClose] = useState(false);
  const [editNotice, setEditNotice] = useState<string | null>(null);

  const inputRef = useRef<HTMLInputElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Extra-pause case only: applyAnswer already advanced past the current
  // item (e.g. it just got mastered), but the extra note needs the OLD
  // item's trial to stay on screen until Continue, so that state is held
  // here instead of being committed to sessionState right away.
  const pendingAdvanceStateRef = useRef<SessionState | null>(null);

  const persistState = (state: SessionState) => {
    if (!state.items.length || !deckName) return;
    const slug = slugify(deckName);
    saveSessionState(slug, {
      deckName,
      phase: state.phase,
      queue: state.queue,
      stats: state.stats,
      items: state.items,
      encodeReps: state.config.encodeReps,
      chunkDifficulty: state.config.chunkDifficulty,
      stemTolerance: state.config.stemTolerance,
      ladderMode: state.config.ladderMode,
      strictPunctuation: state.config.strictPunctuation,
      cycleOrder: state.config.cycleOrder,
      batchIndex: state.batchIndex,
      batchSize: state.config.batchSize,
      batchStartStats: state.batchStartStats,
      sourceDeckEditable,
      timestamp: Date.now(),
    });
  };

  // Persist on every state change, mirroring the original's persistState call
  // at the end of every handleCheck/advanceEncode/advanceCycle branch.
  useEffect(() => {
    persistState(sessionState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionState]);

  // Cold-start recalibration: persists the cumulative (all batches
  // completed so far, however many that is) actual/minimum multiplier as
  // this deck's personal history right before handing off to
  // onFinishSession -- covers a naturally finished session (every batch
  // done), "Save and stop" on an interstitial (some batches done), and "End
  // session" mid-trial (possibly zero batches done, in which case
  // computeCumulativeColdStartMultiplier returns null and nothing is
  // written, leaving any existing history untouched). See
  // computeCumulativeColdStartMultiplier's own doc comment in
  // drillEngine.ts for why this is safe to compute from `state` alone at
  // any of those three call sites.
  const finishSession = (state: SessionState) => {
    const multiplier = computeCumulativeColdStartMultiplier(state);
    if (multiplier !== null && deckName) {
      saveColdStartHistory(slugify(deckName), {
        multiplier,
        deckShape: pickColdStartDeckShape(state.items),
        measuredAt: new Date().toISOString(),
      });
    }
    onFinishSession(state);
  };

  // Session complete: selectTrial has no item left to show (currentId hit the
  // SESSION_COMPLETE_ID sentinel). Mirrors advanceCycle calling
  // onFinishSession directly once everything is mastered.
  //
  // C3: phase 'batch-done' is excluded deliberately -- initSession leaves a
  // resumed 'batch-done' state's currentId exactly as seeded (the
  // SESSION_COMPLETE_ID placeholder passed into the initial useState above),
  // since there's no trial to select there. Without this guard, resuming
  // straight into an interstitial would immediately look indistinguishable
  // from "whole session finished" and skip straight to DoneView instead of
  // showing the interstitial at all.
  useEffect(() => {
    if (
      sessionState.phase !== 'batch-done' &&
      sessionState.currentId === SESSION_COMPLETE_ID &&
      sessionState.items.length
    ) {
      finishSession(sessionState);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionState.currentId, sessionState.phase]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // Autofocus input on item transition (and when the card editor closes).
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, [sessionState.currentId, feedback, showNextBtn, isEditing]);

  // "Saved for this session only" stays up until the card changes.
  useEffect(() => {
    setEditNotice(null);
  }, [sessionState.currentId]);

  const triggerFlash = (ok: boolean) => {
    setFlash(ok ? 'success' : 'danger');
    setTimeout(() => {
      setFlash('idle');
    }, 400);
  };

  const trial = selectTrial(sessionState);
  const cue = trial?.cue ?? { kind: 'none' as const };
  const promptText = trial?.prompt ?? '';
  const phaseDetail = trial?.detail ?? '';
  const currentItem = trial ? sessionState.items.find(i => i.id === trial.itemId) : undefined;
  // Extra field: the post-answer feedback shows it only when the full back is
  // what's actually on screen -- the 'full' stage, the cycle phase, and the
  // FINAL combine window (the whole answer, start 1..n) all show it in full.
  // Chunk presentation beats, intermediate combine windows, and remediation
  // only ever show a fragment of the back, so extra stays hidden there --
  // including under Esc reveal, which just reveals whatever fragment that
  // stage tests, not the complete back. A 'wrong'/'manual' verdict doesn't
  // change which stage/window is current (see applyAnswer), so this stays
  // correct for the whole time feedback is shown, auto-advance or not.
  const showsFullBack =
    !!trial &&
    (trial.stage === 'full' ||
      trial.stage === 'cycle' ||
      (trial.stage === 'combine' &&
        !!currentItem?.combineSeq &&
        currentItem.combineSeqIdx === currentItem.combineSeq.length - 1));

  // C5: cue-driven display replaces the old streak-derived isBlind toggle
  // between "show nothing" and "show the full target" (copy-typing).
  // Revealing (Esc / Show Answer) always wins regardless of cue level.
  // C8b: 'present' shows the full target too, but ungraded -- no input is
  // accepted, and there's nothing to reveal (it's already fully shown).
  let subText = '';
  let placeholderText = '';
  if (trial) {
    if (userRevealedAnswer) {
      subText = trial.target;
      placeholderText = trial.target;
    } else if (cue.kind === 'present') {
      subText = trial.target;
      placeholderText = 'Press Enter to continue';
    } else if (cue.kind === 'firstLetter') {
      subText = cue.pattern;
      placeholderText = cue.pattern;
    } else {
      subText = '';
      placeholderText = BLIND_PLACEHOLDER[trial.stage] ?? 'Type from memory...';
    }
  }
  const isPresentation = cue.kind === 'present' && !userRevealedAnswer;

  // Extra field: an auto-advance would otherwise sweep the extra note off
  // screen before it can be read, so a visible extra forces a manual
  // Continue instead -- same effect as a 'manual' advance from applyAnswer.
  const shouldPauseForExtra = showsFullBack && !!currentItem?.extra;

  const handleShowAnswer = () => {
    setUserRevealedAnswer(true);
  };

  const handleCheck = () => {
    if (isProcessing || !trial) return;
    setIsProcessing(true);

    const result = applyAnswer(sessionState, typedValue, { revealed: userRevealedAnswer });
    setFeedback(result.feedback);
    setLastVerdict(result.verdict);
    // C8b: acknowledging a presentation is neither a success nor a failure
    // -- nothing was graded, so it shouldn't flash red or green.
    if (result.verdict !== 'presented') {
      triggerFlash(result.verdict === 'exact' || result.verdict === 'near');
    }
    persistState(result.state);

    if (result.advance === 'auto' && !shouldPauseForExtra) {
      const delay = DWELL_MS[result.feedback.dwellKey] ?? 0;
      timeoutRef.current = setTimeout(() => {
        setSessionState(result.state);
        setTypedValue('');
        setUserRevealedAnswer(false);
        setFeedback(null);
        setLastVerdict(null);
        setIsProcessing(false);
      }, delay);
    } else if (result.advance === 'auto') {
      // Would have auto-advanced, but the extra note is showing -- hold the
      // (already-advanced-past-this-item) state until Continue instead of
      // committing it now, so the current card/extra stays on screen.
      pendingAdvanceStateRef.current = result.state;
      setShowNextBtn(true);
      setIsProcessing(false);
    } else {
      setSessionState(result.state);
      setShowNextBtn(true);
      setIsProcessing(false);
    }
  };

  // C2 manual override: retroactively counts a still-pending 'wrong' verdict
  // as correct. Only reachable while that verdict's feedback is still showing
  // (i.e. before handleCheck's dwell timer commits it) -- cancels that timer
  // and re-grades the SAME trial against its own target, which always grades
  // 'exact'; applyAnswer's override flag then swaps the stats accounting
  // (no new attempt, +1 override) instead of +1 attempt/+1 miss.
  const handleOverride = () => {
    if (lastVerdict !== 'wrong' || !trial) return;
    if (timeoutRef.current) clearTimeout(timeoutRef.current);
    setIsProcessing(true);

    const result = applyAnswer(sessionState, trial.target, { revealed: false, override: true });
    setFeedback(result.feedback);
    setLastVerdict(result.verdict);
    triggerFlash(true);
    persistState(result.state);

    if (result.advance === 'auto' && !shouldPauseForExtra) {
      const delay = DWELL_MS[result.feedback.dwellKey] ?? 0;
      timeoutRef.current = setTimeout(() => {
        setSessionState(result.state);
        setTypedValue('');
        setUserRevealedAnswer(false);
        setFeedback(null);
        setLastVerdict(null);
        setIsProcessing(false);
      }, delay);
    } else if (result.advance === 'auto') {
      pendingAdvanceStateRef.current = result.state;
      setShowNextBtn(true);
      setIsProcessing(false);
    } else {
      setSessionState(result.state);
      setShowNextBtn(true);
      setIsProcessing(false);
    }
  };

  const handleNext = () => {
    // B5 fix: guard against a fast double-Enter (or double-click) firing
    // handleNext twice before the UI settles, which could otherwise skip a
    // trial -- mirrors handleCheck's own self-guard.
    if (isProcessing) return;
    setIsProcessing(true);
    setShowNextBtn(false);
    if (pendingAdvanceStateRef.current) {
      // The extra-pause case: applyAnswer's already-advanced state was held
      // back (see handleCheck/handleOverride) until this Continue.
      setSessionState(pendingAdvanceStateRef.current);
      pendingAdvanceStateRef.current = null;
    } else if (sessionState.phase === 'cycle') {
      // C5: a wrong verdict in the encode phase now also needs an explicit
      // advance, but sessionState already points at the right trial (same
      // item/stage, streak reset by applyAnswer) -- there's no queue to pop.
      // Only the cycle phase's manual advance needs applyNext.
      setSessionState(applyNext(sessionState));
    }
    setTypedValue('');
    setUserRevealedAnswer(false);
    setFeedback(null);
    setLastVerdict(null);
    setIsProcessing(false);
  };

  // C3: advances past the interstitial into the next batch's encode phase.
  // Only meaningful while phase is 'batch-done' -- the "Next batch" button
  // is the only caller.
  const handleNextBatch = () => {
    if (isProcessing) return;
    setIsProcessing(true);
    setSessionState(advanceToNextBatch(sessionState));
    setTypedValue('');
    setUserRevealedAnswer(false);
    setFeedback(null);
    setLastVerdict(null);
    setShowNextBtn(false);
    setIsProcessing(false);
  };

  const canOverride = lastVerdict === 'wrong';

  // Available whenever a trial is showing and no auto-advance dwell is
  // pending -- including presentation beats and the Continue state after a
  // manual-advance verdict (sessionState still points at the shown card).
  // Extra-pause case (pendingAdvanceStateRef set): sessionState.currentId
  // still names the just-answered item, but its already-advanced-past state
  // is waiting off to the side for Continue -- editing here would either
  // touch the wrong card's data or get silently clobbered when that pending
  // state lands, so editing is blocked until Continue is pressed.
  const canEdit = !!trial && !isProcessing && !isEditing && !pendingAdvanceStateRef.current;

  const handleOpenEditor = () => {
    if (!canEdit) return;
    const item = sessionState.items.find(i => i.id === sessionState.currentId);
    if (!item) return;
    // The full front/back, not trial.target (only a chunk while encoding).
    setEditFront(item.front);
    setEditBack(item.back);
    setEditExtra(item.extra ?? '');
    setEditRevealsOnClose(!isPresentation && !showNextBtn && lastVerdict === null && !userRevealedAnswer);
    setEditNotice(null);
    setIsEditing(true);
  };

  const closeEditor = (restarted: boolean) => {
    // Seeing the full answer and then typing it is copy-typing (see C5), so
    // an attempt that was pending when the editor opened now counts as
    // revealed. A restart starts a fresh attempt instead.
    if (editRevealsOnClose && !restarted) setUserRevealedAnswer(true);
    setIsEditing(false);
  };

  // Returns whether the edit was written back to the saved deck (see
  // writeBackCardEdit for when it is).
  const writeBackEdit = (before: DrillItem, after: DrillItem): boolean => {
    const updated = writeBackCardEdit(deckName, sourceDeckEditable, before, after);
    if (!updated) return false;
    onDeckCardEdited(updated);
    return true;
  };

  const canSaveEdit = editFront.trim().length > 0 && editBack.trim().length > 0;

  const handleSaveEdit = () => {
    if (!canSaveEdit) return;
    const before = sessionState.items.find(i => i.id === sessionState.currentId);
    if (!before) return;
    const { state, restarted } = editCurrentItem(sessionState, { front: editFront, back: editBack, extra: editExtra });
    const after = state.items.find(i => i.id === before.id)!;
    // Extra is display-only, but a change to it still needs writing back to
    // the saved deck (see writeBackCardEdit) -- otherwise it would only ever
    // live in this session's in-memory state.
    const textChanged =
      after.front !== before.front || after.back !== before.back || after.extra !== before.extra;

    if (restarted) {
      setTypedValue('');
      setFeedback(null);
      setLastVerdict(null);
      setShowNextBtn(false);
      setUserRevealedAnswer(false);
    }
    // Kept progress: feedback/Continue state is left exactly as it was.
    if (state !== sessionState) setSessionState(state);
    if (textChanged && !writeBackEdit(before, after)) {
      setEditNotice('Saved for this session only.');
    }
    closeEditor(restarted);
  };

  const handleEditorKeyDown = (e: React.KeyboardEvent) => {
    // Kept inside the editor: the answer input's own Enter/Esc handling
    // (Check answer, Show target) must never see these.
    e.stopPropagation();
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey)) {
      e.preventDefault();
      handleSaveEdit();
    } else if (e.key === 'Escape') {
      e.preventDefault();
      closeEditor(false);
    }
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter' && (e.ctrlKey || e.metaKey) && canOverride) {
      e.preventDefault();
      handleOverride();
    } else if (e.key === 'Enter') {
      if (showNextBtn) {
        handleNext();
      } else {
        handleCheck();
      }
    } else if (e.key === 'Escape' && !userRevealedAnswer && !isPresentation) {
      handleShowAnswer();
    }
  };

  const items = sessionState.items;
  const masteredCount = items.filter(i => i.status === 'mastered').length;
  const readyCount = items.filter(i => i.status === 'ready').length;
  const encodingCount = items.filter(i => i.status === 'encoding').length;
  const newCount = items.filter(i => i.status === 'new').length;
  const progressPercent = items.length
    ? Math.round((masteredCount / items.length) * 100)
    : 0;

  // C3: cheap pure computation (a partition + a couple of filters over this
  // batch's items), safe to call on every render regardless of phase --
  // used both for the interstitial's own numbers and the top bar's label.
  const batchSummary = computeBatchSummary(sessionState);
  const isBatched = batchSummary.totalBatches > 1;

  // Cold-start recalibration: null until at least one batch has been fully
  // completed this session (see computeCumulativeColdStartMultiplier) --
  // used below for the interstitial's remaining-range display. Same cost
  // class as batchSummary above, safe to recompute every render.
  const cumulativeMultiplier = computeCumulativeColdStartMultiplier(sessionState);

  // C4: honest progress -- unlike progressPercent (mastered/total, which
  // reads 0% through the entire encode phase), this credits partial ladder
  // completion, so it starts climbing on the very first correct chunk.
  const currentBatchItems =
    partitionIntoBatches(items, sessionState.config.batchSize ?? items.length)[sessionState.batchIndex] ?? items;
  const sessionProgress = computeSessionProgress(items, sessionState.config.encodeReps, currentBatchItems);
  const batchEncodedPercent = Math.round(sessionProgress.batchFraction * 100);
  const deckEncodedPercent = Math.round(sessionProgress.deckFraction * 100);

  return (
    <div className="space-y-4">
      {/* Top Session Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-[var(--text-secondary)] font-medium">
          <span className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                sessionState.phase === 'encode' ? 'bg-[var(--warning)]' : 'bg-[var(--accent)]'
              }`}
            />
            {sessionState.phase === 'batch-done'
              ? `Batch ${batchSummary.batchNumber} of ${batchSummary.totalBatches} complete`
              : phaseDetail}
            {isBatched && sessionState.phase !== 'batch-done' && (
              <span className="text-[var(--text-muted)]">
                {' '}• Batch {batchSummary.batchNumber}/{batchSummary.totalBatches}
              </span>
            )}
          </span>
          <span className="font-semibold text-[var(--text-primary)]">
            {masteredCount} / {items.length} Mastered ({progressPercent}%)
            {isBatched && (
              <span className="text-[var(--text-muted)] font-normal">
                {' '}• Batch encoded {batchEncodedPercent}%
              </span>
            )}
          </span>
        </div>

        {/* C4: batch progress -- primary/prominent, credits partial ladder
            completion (not just mastery) so it moves during the whole
            encode phase instead of sitting at 0%. */}
        <div className="h-2 w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--accent)] transition-all duration-300 ease-out"
            style={{ width: `${batchEncodedPercent}%` }}
          />
        </div>

        {/* C4: deck progress -- secondary/thin, only shown once there's more
            than one batch (otherwise it would just duplicate the bar above). */}
        {isBatched && (
          <div className="h-1 w-full bg-[var(--surface-1)]/70 rounded-full overflow-hidden">
            <div
              className="h-full bg-[var(--success)]/70 transition-all duration-300 ease-out"
              style={{ width: `${deckEncodedPercent}%` }}
            />
          </div>
        )}
      </div>

      {/* Batch Interstitial: shown between batches instead of the card */}
      {sessionState.phase === 'batch-done' ? (
        <div
          id="batch-interstitial"
          className="rounded-2xl p-6 sm:p-8 border border-[var(--border)] bg-[var(--surface-card)] shadow-[var(--shadow-card)] text-center space-y-5"
        >
          <div className="flex flex-col items-center space-y-2">
            <div className="w-14 h-14 rounded-2xl bg-gradient-to-br from-[var(--success)] to-emerald-600 text-white flex items-center justify-center shadow-lg ring-4 ring-[var(--success-bg)]">
              <CheckCircle2 size={28} strokeWidth={2.5} />
            </div>
            <h3 className="text-xl font-bold text-[var(--text-primary)]">
              Batch {batchSummary.batchNumber} of {batchSummary.totalBatches} complete!
            </h3>
          </div>

          <div className="grid grid-cols-3 gap-3 text-left bg-[var(--surface-1)] border border-[var(--border)] rounded-2xl p-4">
            <div className="space-y-1">
              <p className="text-[11px] font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
                Mastered
              </p>
              <p className="text-xl font-bold text-[var(--text-primary)]">
                {batchSummary.itemsMastered}{' '}
                <span className="text-xs text-[var(--text-muted)] font-normal">
                  / {batchSummary.batchSize}
                </span>
              </p>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
                Trials
              </p>
              <p className="text-xl font-bold text-[var(--text-primary)]">{batchSummary.trialsSpent}</p>
            </div>
            <div className="space-y-1">
              <p className="text-[11px] font-semibold text-[var(--text-secondary)] uppercase tracking-wider">
                Accuracy
              </p>
              <p className="text-xl font-bold text-[var(--text-primary)]">{batchSummary.accuracyPercent}%</p>
            </div>
          </div>

          {cumulativeMultiplier !== null &&
            (() => {
              const range = computeRemainingColdStartRange(sessionState, cumulativeMultiplier);
              if (range.floorTrials <= 0) return null;
              return (
                <p id="cold-start-recalibrated" className="text-xs text-[var(--text-muted)]">
                  Remaining time, recalibrated from this session:{' '}
                  {formatColdStartRange(range.floorSeconds, range.ceilingSeconds)}
                </p>
              );
            })()}

          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              id="next-batch-btn"
              onClick={handleNextBatch}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] hover:opacity-95 text-white font-semibold text-sm shadow-md active:scale-[0.98] transition-all cursor-pointer"
            >
              Next batch <ArrowRight size={16} strokeWidth={2.5} />
            </button>
            <button
              type="button"
              id="save-stop-btn"
              onClick={() => finishSession(sessionState)}
              className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[var(--surface-card)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] font-medium text-sm active:scale-[0.98] transition-all cursor-pointer shadow-xs"
            >
              <Save size={15} /> Save and stop
            </button>
          </div>
        </div>
      ) : (
        <>
      {/* Main Flash Card Container */}
      <div
        id="card"
        className={`rounded-2xl p-6 sm:p-8 border transition-all duration-200 min-h-[240px] flex flex-col justify-center relative shadow-[var(--shadow-card)] ${
          flash === 'success'
            ? 'bg-[var(--success-bg)] border-[var(--success)]'
            : flash === 'danger'
            ? 'bg-[var(--danger-bg)] border-[var(--danger)]'
            : 'bg-[var(--surface-card)] border-[var(--border)]'
        }`}
      >
        {/* Stage / Chunk indicator pill */}
        <div className="flex items-center justify-between mb-3">
          <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--accent)] bg-[var(--accent-bg)] px-2.5 py-0.5 rounded-full border border-[var(--accent)]/15">
            {trial?.label ?? ''}
          </span>
          {isPresentation && (
            <span className="text-[11px] font-medium text-[var(--text-muted)] flex items-center gap-1">
              <Eye size={12} /> Read &amp; Continue
            </span>
          )}
          {!userRevealedAnswer && cue.kind === 'firstLetter' && (
            <span className="text-[11px] font-medium text-[var(--text-muted)] flex items-center gap-1">
              <Eye size={12} /> First-Letter Cue
            </span>
          )}
          {!userRevealedAnswer && cue.kind === 'none' && (
            <span className="text-[11px] font-medium text-[var(--text-muted)] flex items-center gap-1">
              <Eye size={12} /> Blind Recall
            </span>
          )}
        </div>

        {/* Front Prompt */}
        <p
          id="prompt-text"
          className="text-xl sm:text-2xl font-bold text-[var(--text-primary)] mb-3 leading-snug tracking-tight"
        >
          {promptText}
        </p>

        {isEditing ? (
          <div id="card-editor" className="space-y-3" onKeyDown={handleEditorKeyDown}>
            <label className="block space-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Front</span>
              <input
                id="edit-front"
                autoFocus
                value={editFront}
                onChange={e => setEditFront(e.target.value)}
                autoComplete="off"
                className="w-full text-sm bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-4 py-2.5 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none shadow-xs transition-all"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Back</span>
              <textarea
                id="edit-back"
                value={editBack}
                // Decks are one card per line in the bulk editor, so an
                // answer can't hold a line break.
                onChange={e => setEditBack(e.target.value.replace(/\r?\n/g, ' '))}
                rows={3}
                spellCheck={false}
                className="w-full mono text-sm bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-4 py-2.5 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none shadow-xs transition-all resize-y"
              />
            </label>
            <label className="block space-y-1">
              <span className="text-[11px] font-semibold uppercase tracking-wider text-[var(--text-secondary)]">Extra (optional)</span>
              <textarea
                id="edit-extra"
                value={editExtra}
                onChange={e => setEditExtra(e.target.value)}
                rows={2}
                placeholder="Shown after you reveal the full answer -- not graded"
                spellCheck={false}
                className="w-full mono text-sm bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-4 py-2.5 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none shadow-xs transition-all resize-y"
              />
            </label>
            <div className="flex items-center gap-2 flex-wrap">
              <button
                type="button"
                id="edit-save-btn"
                onClick={handleSaveEdit}
                disabled={!canSaveEdit}
                className="flex items-center gap-1.5 px-4 py-2 rounded-xl bg-[var(--accent)] hover:opacity-95 text-white font-semibold text-sm shadow-md active:scale-[0.98] transition-all cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
              >
                <Check size={15} strokeWidth={2.5} /> Save
              </button>
              <button
                type="button"
                id="edit-cancel-btn"
                onClick={() => closeEditor(false)}
                className="px-4 py-2 rounded-xl bg-[var(--surface-card)] hover:bg-[var(--surface-1)] text-[var(--text-secondary)] border border-[var(--border)] text-sm font-medium transition-all cursor-pointer shadow-xs"
              >
                Cancel
              </button>
              <span className="text-[11px] text-[var(--text-muted)] ml-1">Ctrl+Enter to save • Esc to cancel</span>
            </div>
          </div>
        ) : (
          <>
        {/* Subtext Prompt / Revealed Answer */}
        <div className="min-h-[28px] mb-4 flex items-center">
          {subText ? (
            <p id="sub-text" className="mono text-sm sm:text-base text-[var(--accent)] font-semibold bg-[var(--surface-1)] px-3 py-1.5 rounded-lg border border-[var(--border)]">
              {subText}
            </p>
          ) : (
            <p className="text-xs text-[var(--text-muted)] italic flex items-center gap-1.5">
              {!userRevealedAnswer && cue.kind === 'none'
                ? 'Type from pure active recall • press Esc or click Show Answer if stuck'
                : ''}
            </p>
          )}
        </div>

        {/* Typing Input -- read-only during a presentation trial (C8b):
            nothing is typed, the chunk is just read and acknowledged. */}
        <input
          ref={inputRef}
          id="type-input"
          value={isPresentation ? '' : typedValue}
          onChange={e => {
            if (!isPresentation) setTypedValue(e.target.value);
          }}
          onKeyDown={handleKeyDown}
          placeholder={placeholderText}
          readOnly={isPresentation}
          autoComplete="off"
          spellCheck={false}
          className="w-full mono text-sm sm:text-base bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-4 py-3 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none shadow-xs transition-all"
        />
          </>
        )}

        {/* Feedback Area & Word Diff */}
        <div id="feedback" className="min-h-[30px] mt-3.5 text-xs sm:text-sm font-medium">
          {editNotice && (
            <p id="edit-notice" className="text-xs font-medium text-[var(--text-muted)] mb-2">
              {editNotice}
            </p>
          )}
          {feedback && (
            <div
              className={`flex flex-col gap-2 ${
                feedback.type === 'success'
                  ? 'text-[var(--success)]'
                  : feedback.type === 'danger'
                  ? 'text-[var(--danger)]'
                  : 'text-[var(--accent)]'
              }`}
            >
              <span className="font-semibold flex items-center gap-1.5">
                {feedback.type === 'success' ? '✓ ' : feedback.type === 'danger' ? '✕ ' : '• '}
                {feedback.text}
              </span>
              {feedback.diff && (
                <div className="mono text-sm bg-[var(--surface-1)] p-3 rounded-xl border border-[var(--border)] leading-relaxed flex flex-wrap gap-1.5 text-[var(--text-primary)] shadow-xs">
                  {feedback.diff.map((item, idx) =>
                    item.matched ? (
                      <span key={idx} className="opacity-90 font-medium">
                        {item.word}
                      </span>
                    ) : (
                      <span
                        key={idx}
                        className="text-[var(--danger)] font-bold underline decoration-2 underline-offset-4 bg-[var(--danger-bg)] px-1.5 py-0.5 rounded border border-[var(--danger)]/30"
                      >
                        {item.word}
                      </span>
                    )
                  )}
                </div>
              )}
              {showsFullBack && currentItem?.extra && (
                <div
                  id="extra-note"
                  className="text-base font-normal text-[var(--text-muted)] pt-2 mt-1 border-t border-[var(--border)]/60"
                >
                  <span className="font-bold uppercase tracking-wider text-xs mr-1.5">Extra</span>
                  {currentItem.extra}
                </div>
              )}
            </div>
          )}
        </div>
      </div>

      {/* Primary Action Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {isEditing ? null : !showNextBtn ? (
          <button
            type="button"
            id="check-btn"
            onClick={handleCheck}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] hover:opacity-95 text-white font-semibold text-sm shadow-md active:scale-[0.98] transition-all cursor-pointer"
          >
            {isPresentation ? (
              <>
                Continue <ArrowRight size={16} strokeWidth={2.5} />
              </>
            ) : (
              <>
                <Check size={16} strokeWidth={2.5} /> Check answer
              </>
            )}
          </button>
        ) : (
          <button
            type="button"
            id="next-btn"
            onClick={handleNext}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-[var(--success)] hover:opacity-95 text-white font-semibold text-sm shadow-md active:scale-[0.98] transition-all cursor-pointer"
          >
            Continue <ArrowRight size={16} strokeWidth={2.5} />
          </button>
        )}

        {!isEditing && !userRevealedAnswer && !showNextBtn && !isPresentation && (
          <button
            type="button"
            id="show-answer-btn"
            onClick={handleShowAnswer}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[var(--surface-card)] hover:bg-[var(--surface-1)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border)] text-sm font-medium transition-all cursor-pointer shadow-xs active:scale-[0.98]"
            title="Press Esc or click to reveal target phrase"
          >
            <Eye size={15} /> Show target
          </button>
        )}

        {!isEditing && canOverride && (
          <button
            type="button"
            id="override-btn"
            onClick={handleOverride}
            className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[var(--surface-card)] hover:bg-[var(--success-bg)] text-[var(--text-secondary)] hover:text-[var(--success)] border border-[var(--border)] hover:border-[var(--success)]/40 text-sm font-medium transition-all cursor-pointer shadow-xs active:scale-[0.98]"
            title="Ctrl+Enter: count this as correct anyway"
          >
            <CheckCheck size={15} /> Count as correct
          </button>
        )}

        <button
          type="button"
          id="edit-card-btn"
          onClick={handleOpenEditor}
          disabled={!canEdit}
          className="ml-auto flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--accent-bg)] rounded-xl transition-all cursor-pointer border border-transparent hover:border-[var(--accent)]/30 disabled:opacity-40 disabled:cursor-not-allowed disabled:hover:bg-transparent disabled:hover:text-[var(--text-secondary)] disabled:hover:border-transparent"
          title="Edit this card's front and back"
        >
          <Pencil size={14} /> Edit card
        </button>

        <button
          type="button"
          id="end-btn"
          onClick={() => finishSession(sessionState)}
          className="flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)] rounded-xl transition-all cursor-pointer border border-transparent hover:border-[var(--danger)]/30"
        >
          <LogOut size={14} /> End session
        </button>
      </div>
        </>
      )}

      {/* Item Status Strip and Dot Matrix */}
      <div className="pt-3 border-t border-[var(--border)] space-y-2.5">
        <div className="flex items-center justify-between text-[11.5px] text-[var(--text-secondary)]">
          <div className="flex items-center gap-3 flex-wrap">
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[var(--text-muted)]" /> New ({newCount})
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[var(--warning)]" /> Encoding ({encodingCount})
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[var(--accent)]" /> Ready ({readyCount})
            </span>
            <span className="flex items-center gap-1.5">
              <span className="w-2 h-2 rounded-full bg-[var(--success)]" /> Mastered ({masteredCount})
            </span>
          </div>

          <span className="text-[11px] font-medium hidden sm:inline text-[var(--text-muted)]">
            Attempts: {sessionState.stats.attempts} • Misses: {sessionState.stats.misses}
            {sessionState.stats.nearMisses > 0 && <> • Near: {sessionState.stats.nearMisses}</>}
            {sessionState.stats.overrides > 0 && <> • Overrides: {sessionState.stats.overrides}</>}
          </span>
        </div>

        {/* Matrix of dots */}
        <div id="item-status" className="flex flex-wrap gap-1.5">
          {items.map(it => {
            const isCurrent = it.id === trial?.itemId;
            const dotColor =
              it.status === 'mastered'
                ? 'bg-[var(--success)]'
                : it.status === 'ready'
                ? 'bg-[var(--accent)]'
                : it.status === 'encoding'
                ? 'bg-[var(--warning)]'
                : 'bg-[var(--text-muted)]/60';

            return (
              <span
                key={it.id}
                title={`${it.front}: ${it.status}`}
                className={`w-3 h-3 rounded-full ${dotColor} transition-all duration-150 ${
                  isCurrent ? 'ring-2 ring-[var(--text-primary)] ring-offset-2 scale-125' : ''
                }`}
              />
            );
          })}
        </div>
      </div>
    </div>
  );
};
