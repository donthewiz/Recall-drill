import React, { useState } from 'react';
import { DrillItem, SessionStats } from '../types';
import { CheckCircle2, RotateCcw, ChevronDown, ChevronUp, BookOpen, Target, Check, AlertTriangle } from 'lucide-react';

interface DoneViewProps {
  deckName: string;
  items: DrillItem[];
  stats: SessionStats;
  onBackToSetup: () => void;
  onRestartFresh: () => void;
}

export const DoneView: React.FC<DoneViewProps> = ({
  deckName,
  items,
  stats,
  onBackToSetup,
  onRestartFresh,
}) => {
  const [showItemList, setShowItemList] = useState(false);

  const masteredCount = items.filter(i => i.status === 'mastered').length;
  // Phase 3: cards that took at least one miss/reveal during the Final
  // check -- undefined finalMisses (an old save, or a card never reached in
  // an ended-early session) reads as 0, so it's simply left out.
  const missedInFinal = items.filter(i => (i.finalMisses ?? 0) > 0);
  const isAllMastered = masteredCount >= items.length;
  const accuracy =
    stats.attempts > 0
      ? Math.round(((stats.attempts - stats.misses) / stats.attempts) * 100)
      : 100;

  return (
    <div id="done-view" className="py-6 max-w-lg mx-auto space-y-6 text-center">
      <div className="flex flex-col items-center space-y-2.5">
        <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-[var(--success)] to-emerald-600 text-white flex items-center justify-center shadow-lg ring-4 ring-[var(--success-bg)]">
          <CheckCircle2 size={34} strokeWidth={2.5} />
        </div>
        <h2 className="text-2xl font-bold tracking-tight text-[var(--text-primary)]">
          {isAllMastered ? 'Deck Mastered!' : 'Session Saved'}
        </h2>
        <p className="text-xs font-medium text-[var(--text-secondary)] bg-[var(--surface-1)] px-3 py-1 rounded-full border border-[var(--border)] inline-block">
          {deckName}
        </p>
      </div>

      {/* Stats Summary Grid */}
      <div className="grid grid-cols-3 gap-3 bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl p-4 sm:p-5 text-left shadow-[var(--shadow-card)]">
        <div className="space-y-1">
          <p className="text-[11px] font-semibold text-[var(--text-secondary)] flex items-center gap-1.5 uppercase tracking-wider">
            <Target size={12} className="text-[var(--accent)]" /> Mastered
          </p>
          <p className="text-xl font-bold text-[var(--text-primary)]">
            {masteredCount} <span className="text-xs text-[var(--text-muted)] font-normal">/ {items.length}</span>
          </p>
        </div>

        <div className="space-y-1">
          <p className="text-[11px] font-semibold text-[var(--text-secondary)] flex items-center gap-1.5 uppercase tracking-wider">
            <Check size={12} className="text-[var(--success)]" /> Attempts
          </p>
          <p className="text-xl font-bold text-[var(--text-primary)]">
            {stats.attempts}
          </p>
        </div>

        <div className="space-y-1">
          <p className="text-[11px] font-semibold text-[var(--text-secondary)] flex items-center gap-1.5 uppercase tracking-wider">
            <AlertTriangle size={12} className="text-[var(--warning)]" /> Accuracy
          </p>
          <p className="text-xl font-bold text-[var(--text-primary)]">
            {accuracy}%
          </p>
        </div>
      </div>

      <p id="done-stats" className="text-xs sm:text-sm text-[var(--text-secondary)] leading-relaxed px-2">
        {isAllMastered ? (
          <span>
            Terrific work! All {items.length} items were successfully encoded and verified through spaced retrieval.
          </span>
        ) : (
          <span>
            {masteredCount} of {items.length} items mastered so far ({stats.misses} misses). You can resume this session anytime by selecting &ldquo;{deckName}&rdquo; on the setup screen.
          </span>
        )}
      </p>

      {/* Collapsible Card List */}
      <div className="text-left bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl overflow-hidden shadow-xs">
        <button
          type="button"
          onClick={() => setShowItemList(!showItemList)}
          className="w-full px-4 py-3 text-xs font-semibold text-[var(--text-secondary)] flex items-center justify-between hover:bg-[var(--surface-1)] transition-colors cursor-pointer"
        >
          <span className="flex items-center gap-2">
            <BookOpen size={14} /> Review deck cards ({items.length})
          </span>
          {showItemList ? <ChevronUp size={14} /> : <ChevronDown size={14} />}
        </button>

        {showItemList && (
          <div className="p-3.5 divide-y divide-[var(--border)] text-xs max-h-64 overflow-y-auto bg-[var(--surface-1)]">
            {items.map(it => (
              <div key={it.id} className="py-2.5 first:pt-0 last:pb-0 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-[var(--text-primary)]">{it.front}</span>
                  <span
                    className={`text-[10px] px-2 py-0.5 rounded-full capitalize font-semibold ${
                      it.status === 'mastered'
                        ? 'bg-[var(--success-bg)] text-[var(--success)] border border-[var(--success)]/30'
                        : it.status === 'ready'
                        ? 'bg-[var(--accent-bg)] text-[var(--accent)] border border-[var(--accent)]/30'
                        : 'bg-[var(--warning-bg)] text-[var(--warning)] border border-[var(--warning)]/30'
                    }`}
                  >
                    {it.status}
                  </span>
                </div>
                <p className="mono text-[var(--text-secondary)]">{it.back}</p>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Phase 3: cards that took at least one miss/reveal during the Final
          check -- omitted entirely when nothing qualifies. */}
      {missedInFinal.length > 0 && (
        <div
          id="final-check-misses"
          className="text-left bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl p-3.5 space-y-2 shadow-xs"
        >
          <p className="text-xs font-semibold text-[var(--text-secondary)] flex items-center gap-1.5">
            <AlertTriangle size={13} className="text-[var(--warning)]" /> Missed in final check
          </p>
          <div className="divide-y divide-[var(--border)] text-xs">
            {missedInFinal.map(it => (
              <div key={it.id} className="py-2 first:pt-0 last:pb-0 space-y-1">
                <div className="flex items-center justify-between">
                  <span className="font-semibold text-[var(--text-primary)]">{it.front}</span>
                  <span className="text-[10px] text-[var(--text-muted)]">
                    {it.finalMisses} miss{it.finalMisses === 1 ? '' : 'es'}
                  </span>
                </div>
                <p className="mono text-[var(--text-secondary)]">{it.back}</p>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Actions */}
      <div className="flex items-center justify-center gap-3 pt-2">
        <button
          type="button"
          id="restart-btn"
          onClick={onBackToSetup}
          className="px-6 py-2.5 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] hover:opacity-95 text-white font-semibold text-xs shadow-md active:scale-[0.98] transition-all cursor-pointer"
        >
          Back to setup
        </button>

        <button
          type="button"
          onClick={onRestartFresh}
          className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[var(--surface-card)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] font-medium text-xs active:scale-[0.98] transition-all cursor-pointer shadow-xs"
        >
          <RotateCcw size={14} /> Practice again
        </button>
      </div>
    </div>
  );
};
