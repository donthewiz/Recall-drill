import React, { useEffect, useRef, useState } from 'react';
import { DrillItem, Feedback, LadderMode, SessionState, SessionStats, Verdict } from '../types';
import {
  slugify,
  saveSessionState,
  selectTrial,
  applyAnswer,
  applyNext,
  initSession,
  SESSION_COMPLETE_ID,
  DWELL_MS,
} from '../utils/drillEngine';
import { Check, CheckCheck, ArrowRight, Eye, LogOut } from 'lucide-react';

interface SessionViewProps {
  deckName: string;
  initialItems: DrillItem[];
  initialPhase: 'encode' | 'cycle';
  initialQueue: number[];
  initialStats: SessionStats;
  encodeReps: number;
  chunkDifficulty?: number;
  stemTolerance?: boolean;
  ladderMode?: LadderMode;
  onFinishSession: (items: DrillItem[], stats: SessionStats) => void;
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
  onFinishSession,
}) => {
  const [sessionState, setSessionState] = useState<SessionState>(() =>
    initSession({
      items: initialItems,
      phase: initialPhase,
      queue: initialQueue,
      stats: initialStats,
      currentId: SESSION_COMPLETE_ID,
      batchIndex: 0,
      config: { encodeReps, chunkDifficulty, stemTolerance, ladderMode },
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

  const inputRef = useRef<HTMLInputElement>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);

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
      timestamp: Date.now(),
    });
  };

  // Persist on every state change, mirroring the original's persistState call
  // at the end of every handleCheck/advanceEncode/advanceCycle branch.
  useEffect(() => {
    persistState(sessionState);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionState]);

  // Session complete: selectTrial has no item left to show (currentId hit the
  // SESSION_COMPLETE_ID sentinel). Mirrors advanceCycle calling
  // onFinishSession directly once everything is mastered.
  useEffect(() => {
    if (sessionState.currentId === SESSION_COMPLETE_ID && sessionState.items.length) {
      onFinishSession(sessionState.items, sessionState.stats);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [sessionState.currentId]);

  useEffect(() => {
    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // Autofocus input on item transition.
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, [sessionState.currentId, feedback, showNextBtn]);

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

  // C5: cue-driven display replaces the old streak-derived isBlind toggle
  // between "show nothing" and "show the full target" (copy-typing).
  // Revealing (Esc / Show Answer) always wins regardless of cue level.
  let subText = '';
  let placeholderText = '';
  if (trial) {
    if (userRevealedAnswer) {
      subText = trial.target;
      placeholderText = trial.target;
    } else if (cue.kind === 'firstLetter') {
      subText = cue.pattern;
      placeholderText = cue.pattern;
    } else {
      subText = '';
      placeholderText = BLIND_PLACEHOLDER[trial.stage] ?? 'Type from memory...';
    }
  }

  const handleShowAnswer = () => {
    setUserRevealedAnswer(true);
  };

  const handleCheck = () => {
    if (isProcessing || !trial) return;
    setIsProcessing(true);

    const result = applyAnswer(sessionState, typedValue, { revealed: userRevealedAnswer });
    setFeedback(result.feedback);
    setLastVerdict(result.verdict);
    triggerFlash(result.verdict === 'exact' || result.verdict === 'near');
    persistState(result.state);

    if (result.advance === 'auto') {
      const delay = DWELL_MS[result.feedback.dwellKey] ?? 0;
      timeoutRef.current = setTimeout(() => {
        setSessionState(result.state);
        setTypedValue('');
        setUserRevealedAnswer(false);
        setFeedback(null);
        setLastVerdict(null);
        setIsProcessing(false);
      }, delay);
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

    if (result.advance === 'auto') {
      const delay = DWELL_MS[result.feedback.dwellKey] ?? 0;
      timeoutRef.current = setTimeout(() => {
        setSessionState(result.state);
        setTypedValue('');
        setUserRevealedAnswer(false);
        setFeedback(null);
        setLastVerdict(null);
        setIsProcessing(false);
      }, delay);
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
    // C5: a wrong verdict in the encode phase now also needs an explicit
    // advance, but sessionState already points at the right trial (same
    // item/stage, streak reset by applyAnswer) -- there's no queue to pop.
    // Only the cycle phase's manual advance needs applyNext.
    if (sessionState.phase === 'cycle') {
      setSessionState(applyNext(sessionState));
    }
    setTypedValue('');
    setUserRevealedAnswer(false);
    setFeedback(null);
    setLastVerdict(null);
    setIsProcessing(false);
  };

  const canOverride = lastVerdict === 'wrong';

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
    } else if (e.key === 'Escape' && !userRevealedAnswer) {
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
            {phaseDetail}
          </span>
          <span className="font-semibold text-[var(--text-primary)]">
            {masteredCount} / {items.length} Mastered ({progressPercent}%)
          </span>
        </div>

        <div className="h-1.5 w-full bg-[var(--surface-1)] border border-[var(--border)] rounded-full overflow-hidden">
          <div
            className="h-full bg-[var(--success)] transition-all duration-300 ease-out"
            style={{ width: `${progressPercent}%` }}
          />
        </div>
      </div>

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

        {/* Typing Input */}
        <input
          ref={inputRef}
          id="type-input"
          value={typedValue}
          onChange={e => setTypedValue(e.target.value)}
          onKeyDown={handleKeyDown}
          placeholder={placeholderText}
          autoComplete="off"
          spellCheck={false}
          className="w-full mono text-sm sm:text-base bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-4 py-3 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none shadow-xs transition-all"
        />

        {/* Feedback Area & Word Diff */}
        <div id="feedback" className="min-h-[30px] mt-3.5 text-xs sm:text-sm font-medium">
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
            </div>
          )}
        </div>
      </div>

      {/* Primary Action Controls */}
      <div className="flex items-center gap-3 flex-wrap">
        {!showNextBtn ? (
          <button
            type="button"
            id="check-btn"
            onClick={handleCheck}
            className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] hover:opacity-95 text-white font-semibold text-sm shadow-md active:scale-[0.98] transition-all cursor-pointer"
          >
            <Check size={16} strokeWidth={2.5} /> Check answer
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

        {!userRevealedAnswer && !showNextBtn && (
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

        {canOverride && (
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
          id="end-btn"
          onClick={() => onFinishSession(sessionState.items, sessionState.stats)}
          className="ml-auto flex items-center gap-1.5 px-3.5 py-2 text-xs font-medium text-[var(--text-secondary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)] rounded-xl transition-all cursor-pointer border border-transparent hover:border-[var(--danger)]/30"
        >
          <LogOut size={14} /> End session
        </button>
      </div>

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
