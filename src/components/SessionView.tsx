import React, { useState, useEffect, useRef, useTransition } from 'react';
import { DrillItem, SessionStats, WordDiffResult } from '../types';
import {
  norm,
  computeWordDiff,
  findAllCulpritChunks,
  splitInHalf,
  culpritHalf,
  shuffle,
  slugify,
  saveSessionState,
} from '../utils/drillEngine';
import { Check, ArrowRight, Eye, LogOut, CheckCircle, AlertCircle, RefreshCw } from 'lucide-react';

interface SessionViewProps {
  deckName: string;
  initialItems: DrillItem[];
  initialPhase: 'encode' | 'cycle';
  initialQueue: number[];
  initialStats: SessionStats;
  encodeReps: number;
  chunkDifficulty?: number;
  onFinishSession: (items: DrillItem[], stats: SessionStats) => void;
}

export const SessionView: React.FC<SessionViewProps> = ({
  deckName,
  initialItems,
  initialPhase,
  initialQueue,
  initialStats,
  encodeReps,
  chunkDifficulty = 35,
  onFinishSession,
}) => {
  const [items, setItems] = useState<DrillItem[]>(initialItems);
  const [phase, setPhase] = useState<'encode' | 'cycle'>(initialPhase);
  const [queue, setQueue] = useState<number[]>(initialQueue);
  const [stats, setStats] = useState<SessionStats>(initialStats);
  const [currentId, setCurrentId] = useState<number>(0);
  const [typedValue, setTypedValue] = useState('');
  const [showNextBtn, setShowNextBtn] = useState(false);
  const [userRevealedAnswer, setUserRevealedAnswer] = useState(false);
  const [feedback, setFeedback] = useState<{
    text: string;
    type: 'success' | 'danger' | 'info';
    diff?: WordDiffResult[];
  } | null>(null);
  const [flash, setFlash] = useState<'idle' | 'success' | 'danger'>('idle');
  const [isProcessing, setIsProcessing] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const timeoutRef = useRef<NodeJS.Timeout | null>(null);

  // Keep state synced to localStorage automatically
  const persistState = (
    currentItems: DrillItem[],
    currentPhase: 'encode' | 'cycle',
    currentQueue: number[],
    currentStats: SessionStats
  ) => {
    if (!currentItems.length || !deckName) return;
    const slug = slugify(deckName);
    saveSessionState(slug, {
      deckName,
      phase: currentPhase,
      queue: currentQueue,
      stats: currentStats,
      items: currentItems,
      encodeReps,
      chunkDifficulty,
      timestamp: Date.now(),
    });
  };

  const currentItem = items.find(i => i.id === currentId) || items[0];

  // Pick initial item on mount
  useEffect(() => {
    if (initialPhase === 'cycle') {
      advanceCycle(initialItems, initialQueue, initialStats);
    } else {
      advanceEncode(initialItems, initialStats);
    }

    return () => {
      if (timeoutRef.current) clearTimeout(timeoutRef.current);
    };
  }, []);

  // Autofocus input on item transition
  useEffect(() => {
    if (inputRef.current) {
      inputRef.current.focus();
    }
  }, [currentId, feedback, showNextBtn]);

  const triggerFlash = (ok: boolean) => {
    setFlash(ok ? 'success' : 'danger');
    setTimeout(() => {
      setFlash('idle');
    }, 400);
  };

  // Determine current prompt, subtext, placeholder, and blind state
  let promptText = '';
  let subText = '';
  let placeholderText = '';
  let isBlind = false;
  let phaseDetail = '';

  if (currentItem) {
    promptText = currentItem.front;

    if (phase === 'encode') {
      if (currentItem.stage === 'chunks' && currentItem.chunks) {
        const chunk = currentItem.chunks[currentItem.chunkIndex];
        isBlind = currentItem.chunkStreak >= 1;
        phaseDetail = `Encoding • Part ${currentItem.chunkIndex + 1} of ${currentItem.chunks.length}`;
        if (isBlind) {
          subText = userRevealedAnswer ? chunk : '';
          placeholderText = 'Type this part from memory...';
        } else {
          subText = chunk;
          placeholderText = chunk;
        }
      } else if (currentItem.stage === 'combine' && currentItem.chunks && currentItem.combineSeq) {
        const seqItem = currentItem.combineSeq[currentItem.combineSeqIdx];
        const combined = currentItem.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
        isBlind = currentItem.combineStreak >= 1;
        phaseDetail = `Encoding • Combining parts ${seqItem.start}-${seqItem.end} (${currentItem.combineSeqIdx + 1}/${currentItem.combineSeq.length})`;
        if (isBlind) {
          subText = userRevealedAnswer ? combined : '';
          placeholderText = 'Type it from memory...';
        } else {
          subText = combined;
          placeholderText = combined;
        }
      } else if (currentItem.stage === 'remediate') {
        const rTop = currentItem.remediateStack[currentItem.remediateStack.length - 1];
        if (rTop) {
          isBlind = rTop.streak >= 1;
          const rWordCount = rTop.text.split(' ').length;
          const queueSuffix =
            currentItem.remediateQueue.length > 0
              ? ` (${currentItem.remediateQueue.length} more spot${currentItem.remediateQueue.length > 1 ? 's' : ''} after this)`
              : '';

          phaseDetail =
            currentItem.remediateStack.length > 1
              ? `Isolating exact spot • drilled down ${currentItem.remediateStack.length - 1} level${currentItem.remediateStack.length - 1 > 1 ? 's' : ''}, now on ${rWordCount} word${rWordCount === 1 ? '' : 's'}${queueSuffix}`
              : `Reinforcing this ${rWordCount}-word part before combining again${queueSuffix}`;

          if (isBlind) {
            subText = userRevealedAnswer ? rTop.text : '';
            placeholderText = 'Type this from memory...';
          } else {
            subText = rTop.text;
            placeholderText = rTop.text;
          }
        }
      } else {
        // Full (no chunks)
        isBlind = currentItem.encodeStreak >= 1;
        phaseDetail = 'Encoding • Full item';
        if (isBlind) {
          subText = userRevealedAnswer ? currentItem.back : '';
          placeholderText = 'Type the full answer from memory...';
        } else {
          subText = currentItem.back;
          placeholderText = currentItem.back;
        }
      }
    } else {
      // Cycle phase
      phaseDetail = 'Spaced Retrieval • Cycling review';
      isBlind = true;
      subText = userRevealedAnswer ? currentItem.back : '';
      placeholderText = 'Type the answer from memory...';
    }
  }

  const advanceEncode = (updatedItems: DrillItem[], updatedStats: SessionStats) => {
    const remaining = updatedItems.filter(i => i.status === 'new' || i.status === 'encoding');
    if (!remaining.length) {
      // Switch to cycling phase
      const newQueue = shuffle(
        updatedItems.filter(i => i.status !== 'mastered').map(i => i.id)
      );
      setPhase('cycle');
      setQueue(newQueue);
      persistState(updatedItems, 'cycle', newQueue, updatedStats);
      advanceCycle(updatedItems, newQueue, updatedStats);
      return;
    }

    const nextItem = remaining[0];
    const newItems = updatedItems.map(i =>
      i.id === nextItem.id ? { ...i, status: 'encoding' as const } : i
    );
    setItems(newItems);
    setCurrentId(nextItem.id);
    setTypedValue('');
    setUserRevealedAnswer(false);
    setShowNextBtn(false);
    setFeedback(null);
    setIsProcessing(false);
    persistState(newItems, 'encode', queue, updatedStats);
  };

  const advanceCycle = (
    updatedItems: DrillItem[],
    currentQueue: number[],
    updatedStats: SessionStats
  ) => {
    let q = [...currentQueue];
    if (!q.length) {
      const remaining = updatedItems.filter(i => i.status !== 'mastered');
      if (!remaining.length) {
        onFinishSession(updatedItems, updatedStats);
        return;
      }
      q = shuffle(remaining.map(i => i.id));
    }

    const nextId = q.shift()!;
    setQueue(q);
    setCurrentId(nextId);
    setTypedValue('');
    setUserRevealedAnswer(false);
    setShowNextBtn(false);
    setFeedback(null);
    setIsProcessing(false);
    persistState(updatedItems, 'cycle', q, updatedStats);
  };

  const handleShowAnswer = () => {
    setUserRevealedAnswer(true);
  };

  const handleCheck = () => {
    if (isProcessing || !currentItem) return;
    setIsProcessing(true);

    const typed = typedValue;
    const nextStats = { ...stats, attempts: stats.attempts + 1 };
    setStats(nextStats);

    const newItems = [...items];
    const itIdx = newItems.findIndex(i => i.id === currentItem.id);
    const it = { ...newItems[itIdx] };

    if (phase === 'encode') {
      if (it.stage === 'chunks' && it.chunks) {
        const targetChunk = it.chunks[it.chunkIndex];
        const isOk = norm(typed) === norm(targetChunk);
        triggerFlash(isOk);

        if (isOk) {
          it.chunkStreak++;
          if (it.chunkStreak >= encodeReps) {
            it.chunkIndex++;
            it.chunkStreak = 0;
            if (it.chunkIndex >= it.chunks.length) {
              it.stage = 'combine';
              it.combineSeqIdx = 0;
              it.combineStreak = 0;
              setFeedback({
                text: 'All parts learned — now combining them',
                type: 'success',
              });
            } else {
              setFeedback({ text: 'Part learned!', type: 'success' });
            }
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              advanceEncode(newItems, nextStats);
            }, 700);
          } else {
            setFeedback({
              text: `${it.chunkStreak} of ${encodeReps} streaks`,
              type: 'success',
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 500);
          }
        } else {
          nextStats.misses++;
          it.chunkStreak = 0;
          const diff = computeWordDiff(typed, targetChunk);
          setFeedback({
            text: 'Streak reset — compare your answer:',
            type: 'danger',
            diff,
          });
          newItems[itIdx] = it;
          setItems(newItems);
          timeoutRef.current = setTimeout(() => {
            setTypedValue('');
            setUserRevealedAnswer(false);
            setFeedback(null);
            setIsProcessing(false);
          }, 1800);
        }
        persistState(newItems, 'encode', queue, nextStats);
        return;
      }

      if (it.stage === 'combine' && it.chunks && it.combineSeq) {
        const seqItem = it.combineSeq[it.combineSeqIdx];
        const combinedTarget = it.chunks.slice(seqItem.start - 1, seqItem.end).join(' ');
        const wasBlind = it.combineStreak >= 1;
        const isOk = norm(typed) === norm(combinedTarget);
        triggerFlash(isOk);

        if (isOk) {
          it.combineStreak++;
          if (wasBlind) it.combineMissCount = 0;

          if (it.combineStreak >= encodeReps) {
            it.combineSeqIdx++;
            it.combineStreak = 0;
            if (it.combineSeqIdx >= it.combineSeq.length) {
              it.status = 'ready';
              setFeedback({ text: 'Encoded!', type: 'success' });
              newItems[itIdx] = it;
              setItems(newItems);
              timeoutRef.current = setTimeout(() => {
                advanceEncode(newItems, nextStats);
              }, 600);
            } else {
              setFeedback({ text: 'Combination learned!', type: 'success' });
              newItems[itIdx] = it;
              setItems(newItems);
              timeoutRef.current = setTimeout(() => {
                advanceEncode(newItems, nextStats);
              }, 700);
            }
          } else {
            setFeedback({
              text: `${it.combineStreak} of ${encodeReps} streaks`,
              type: 'success',
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 500);
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
            it.remediateStack = [
              { text: it.chunks[culprits[0]], streak: 0, missCount: 0 },
            ];
            it.remediateQueue = culprits.slice(1).map(idx => it.chunks![idx]);
            it.remediateReturnSeqIdx = it.combineSeqIdx;
            it.combineMissCount = 0;
            it.stage = 'remediate';

            const spotWord = culprits.length > 1 ? 'spots' : 'part';
            const missMsg =
              missThreshold === 1
                ? 'Missed it — isolating '
                : 'Repeated miss — isolating ';
            setFeedback({
              text: `${missMsg} ${culprits.length} trouble ${spotWord} to reinforce`,
              type: 'danger',
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 1800);
          } else {
            const diff = computeWordDiff(typed, combinedTarget);
            setFeedback({
              text: 'Streak reset — check the wording:',
              type: 'danger',
              diff,
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 1600);
          }
        }
        persistState(newItems, 'encode', queue, nextStats);
        return;
      }

      if (it.stage === 'remediate') {
        const rTop = it.remediateStack[it.remediateStack.length - 1];
        const isOk = norm(typed) === norm(rTop.text);
        triggerFlash(isOk);

        if (isOk) {
          rTop.streak++;
          rTop.missCount = 0;
          if (rTop.streak >= encodeReps) {
            it.remediateStack.pop();
            if (it.remediateStack.length === 0) {
              if (it.remediateQueue.length > 0) {
                const nextPiece = it.remediateQueue.shift()!;
                it.remediateStack = [{ text: nextPiece, streak: 0, missCount: 0 }];
                setFeedback({
                  text: 'Trouble spot solid! Now checking the next spot',
                  type: 'success',
                });
                newItems[itIdx] = it;
                setItems(newItems);
                timeoutRef.current = setTimeout(() => {
                  setTypedValue('');
                  setUserRevealedAnswer(false);
                  setFeedback(null);
                  setIsProcessing(false);
                }, 900);
              } else {
                it.stage = 'combine';
                it.combineSeqIdx = it.remediateReturnSeqIdx;
                it.combineStreak = 0;
                setFeedback({
                  text: 'Reinforced! Resuming progressive combining',
                  type: 'success',
                });
                newItems[itIdx] = it;
                setItems(newItems);
                timeoutRef.current = setTimeout(() => {
                  advanceEncode(newItems, nextStats);
                }, 700);
              }
            } else {
              const parentLevel = it.remediateStack[it.remediateStack.length - 1];
              parentLevel.streak = 0;
              const parentWordCount = parentLevel.text.split(' ').length;
              setFeedback({
                text: `Isolated piece mastered — expanding to ${parentWordCount}-word parent`,
                type: 'success',
              });
              newItems[itIdx] = it;
              setItems(newItems);
              timeoutRef.current = setTimeout(() => {
                setTypedValue('');
                setUserRevealedAnswer(false);
                setFeedback(null);
                setIsProcessing(false);
              }, 1100);
            }
          } else {
            setFeedback({
              text: `${rTop.streak} of ${encodeReps} streaks`,
              type: 'success',
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 500);
          }
        } else {
          nextStats.misses++;
          rTop.streak = 0;
          rTop.missCount++;
          const rWordCount = rTop.text.split(' ').length;

          if (rTop.missCount >= 2 && rWordCount > 1) {
            const halves = splitInHalf(rTop.text);
            const culpritPiece = culpritHalf(typed, halves[0], halves[1]);
            it.remediateStack.push({
              text: culpritPiece,
              streak: 0,
              missCount: 0,
            });
            setFeedback({
              text: 'Still struggling — zooming into smaller sub-phrase',
              type: 'danger',
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 1800);
          } else {
            const diff = computeWordDiff(typed, rTop.text);
            setFeedback({
              text: 'Not quite — compare with target:',
              type: 'danger',
              diff,
            });
            newItems[itIdx] = it;
            setItems(newItems);
            timeoutRef.current = setTimeout(() => {
              setTypedValue('');
              setUserRevealedAnswer(false);
              setFeedback(null);
              setIsProcessing(false);
            }, 1600);
          }
        }
        persistState(newItems, 'encode', queue, nextStats);
        return;
      }

      // Stage: full (short phrase <= 5 words)
      const isOk = norm(typed) === norm(it.back);
      triggerFlash(isOk);

      if (isOk) {
        it.encodeStreak++;
        if (it.encodeStreak >= encodeReps) {
          it.status = 'ready';
          setFeedback({ text: 'Encoded!', type: 'success' });
          newItems[itIdx] = it;
          setItems(newItems);
          timeoutRef.current = setTimeout(() => {
            advanceEncode(newItems, nextStats);
          }, 600);
        } else {
          setFeedback({
            text: `${it.encodeStreak} of ${encodeReps} streaks`,
            type: 'success',
          });
          newItems[itIdx] = it;
          setItems(newItems);
          timeoutRef.current = setTimeout(() => {
            setTypedValue('');
            setUserRevealedAnswer(false);
            setFeedback(null);
            setIsProcessing(false);
          }, 500);
        }
      } else {
        nextStats.misses++;
        it.encodeStreak = 0;
        const diff = computeWordDiff(typed, it.back);
        setFeedback({
          text: 'Streak reset — compare your answer:',
          type: 'danger',
          diff,
        });
        newItems[itIdx] = it;
        setItems(newItems);
        timeoutRef.current = setTimeout(() => {
          setTypedValue('');
          setUserRevealedAnswer(false);
          setFeedback(null);
          setIsProcessing(false);
        }, 1600);
      }
      persistState(newItems, 'encode', queue, nextStats);
      return;
    }

    // Phase: Cycle (spaced retrieval interleaving)
    const isOkCycle = norm(typed) === norm(it.back);
    triggerFlash(isOkCycle);
    const updatedQueue = [...queue];

    if (isOkCycle) {
      it.cycleStreak++;
      if (it.cycleStreak >= 2) {
        it.status = 'mastered';
        setFeedback({ text: 'Mastered! Item retired.', type: 'success' });
      } else {
        setFeedback({
          text: 'Correct — will test once more later in the session.',
          type: 'success',
        });
        updatedQueue.splice(Math.min(3, updatedQueue.length), 0, it.id);
      }
    } else {
      nextStats.misses++;
      it.cycleStreak = 0;
      const diff = computeWordDiff(typed, it.back);
      setFeedback({
        text: 'Missed — review answer below before continuing:',
        type: 'danger',
        diff,
      });
      const gap = 2 + Math.floor(Math.random() * 2);
      updatedQueue.splice(Math.min(gap, updatedQueue.length), 0, it.id);
    }

    newItems[itIdx] = it;
    setItems(newItems);
    setQueue(updatedQueue);
    setShowNextBtn(true);
    setIsProcessing(false);
    persistState(newItems, 'cycle', updatedQueue, nextStats);
  };

  const handleNext = () => {
    setShowNextBtn(false);
    advanceCycle(items, queue, stats);
  };

  const handleKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === 'Enter') {
      if (showNextBtn) {
        handleNext();
      } else {
        handleCheck();
      }
    } else if (e.key === 'Escape' && isBlind) {
      handleShowAnswer();
    }
  };

  const masteredCount = items.filter(i => i.status === 'mastered').length;
  const readyCount = items.filter(i => i.status === 'ready').length;
  const encodingCount = items.filter(i => i.status === 'encoding').length;
  const newCount = items.filter(i => i.status === 'new').length;
  const progressPercent = Math.round((masteredCount / items.length) * 100);

  return (
    <div className="space-y-4">
      {/* Top Session Progress Bar */}
      <div className="space-y-1.5">
        <div className="flex items-center justify-between text-xs text-[var(--text-secondary)] font-medium">
          <span className="flex items-center gap-1.5">
            <span
              className={`w-2 h-2 rounded-full ${
                phase === 'encode' ? 'bg-[var(--warning)]' : 'bg-[var(--accent)]'
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
            {phase === 'encode'
              ? currentItem?.stage === 'chunks'
                ? `Chunk Practice • ${currentItem.chunkIndex + 1}/${currentItem.chunks?.length || 1}`
                : currentItem?.stage === 'combine'
                ? 'Combination Practice'
                : currentItem?.stage === 'remediate'
                ? 'Precision Repair'
                : 'Full Recall'
              : 'Spaced Retrieval Cycle'}
          </span>
          {isBlind && (
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
              {isBlind ? 'Type from pure active recall • press Esc or click Show Answer if stuck' : ''}
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

        {isBlind && !userRevealedAnswer && !showNextBtn && (
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

        <button
          type="button"
          id="end-btn"
          onClick={() => onFinishSession(items, stats)}
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
            Attempts: {stats.attempts} • Misses: {stats.misses}
          </span>
        </div>

        {/* Matrix of dots */}
        <div id="item-status" className="flex flex-wrap gap-1.5">
          {items.map(it => {
            const isCurrent = it.id === currentItem?.id;
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
