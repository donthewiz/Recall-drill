import React from 'react';
import { CycleOrder, LadderMode } from '../../types';

function getDifficultyLabel(pct: number): string {
  if (pct <= 25) return 'Easy (Bite-sized)';
  if (pct <= 40) return 'Balanced';
  if (pct <= 65) return 'Medium';
  if (pct < 100) return 'Hard (Longer)';
  return 'Full Card (100%)';
}

function getDifficultyBadgeClass(pct: number): string {
  if (pct <= 25) return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
  if (pct <= 40) return 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20';
  if (pct <= 65) return 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
  if (pct < 100) return 'bg-orange-500/10 text-orange-600 dark:text-orange-400 border-orange-500/20';
  return 'bg-rose-500/10 text-rose-600 dark:text-rose-400 border-rose-500/20';
}

function getRepsBadgeClass(reps: number): string {
  if (reps === 1) return 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/20';
  if (reps === 2) return 'bg-teal-500/10 text-teal-600 dark:text-teal-400 border-teal-500/20';
  if (reps === 3) return 'bg-blue-500/10 text-blue-600 dark:text-blue-400 border-blue-500/20';
  if (reps <= 5) return 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/20';
  return 'bg-purple-500/10 text-purple-600 dark:text-purple-400 border-purple-500/20';
}

function getRepsLabel(reps: number): string {
  if (reps === 1) return '1 Rep • Quick';
  if (reps === 2) return '2 Reps • Light';
  if (reps === 3) return '3 Reps • Standard';
  if (reps <= 5) return `${reps} Reps • Deep`;
  return `${reps} Reps • Mastery`;
}

// C8a: individual chunks no longer scale with this setting -- every chunk
// always needs exactly one cued attempt and one blind success, regardless
// of encodeReps. This slider now only paces the final full-combination
// check and short (unchunked) cards.
function getRepsDescription(reps: number): string {
  if (reps === 1) return '1 blind completion for the full combination or a short card (each chunk still gets one warmup + one blind rep)';
  if (reps === 2) return '2 consecutive blind completions before the full combination is done';
  if (reps === 3) return 'Standard 3 consecutive blind completions for the full combination (recommended for retention)';
  return `${reps} consecutive blind completions on the full combination for rock-solid memory locks`;
}

function getDifficultyDescription(pct: number, avgWords: number): string {
  if (pct >= 100) {
    return 'Full card at once — no sub-chunks (maximum difficulty)';
  }
  const sampleWords = avgWords > 0 ? avgWords : 12;
  const chunkWords = Math.max(2, Math.round(sampleWords * (pct / 100)));
  return `~${chunkWords} of ${sampleWords} words at once per chunk (${pct}%)`;
}

interface SessionSettingsProps {
  encodeReps: number;
  onEncodeRepsChange: (val: number) => void;
  chunkDifficulty: number;
  onChunkDifficultyChange: (val: number) => void;
  // Average back length of the deck, for the difficulty slider's caption.
  avgWordsPerCard: number;
  stemTolerance: boolean;
  onStemToleranceChange: (val: boolean) => void;
  // Per-deck, unlike the rest (see SetupView).
  strictPunctuation: boolean;
  onStrictPunctuationChange: (val: boolean) => void;
  ladderMode: LadderMode;
  onLadderModeChange: (val: LadderMode) => void;
  batchSize: number;
  onBatchSizeChange: (val: number) => void;
  cycleOrder: CycleOrder;
  onCycleOrderChange: (val: CycleOrder) => void;
}

// The setup screen's session settings: reps, typing difficulty, grading,
// ladder, batch size, and cycle order.
export const SessionSettings: React.FC<SessionSettingsProps> = ({
  encodeReps,
  onEncodeRepsChange: handleEncodeRepsChange,
  chunkDifficulty,
  onChunkDifficultyChange: handleChunkDifficultyChange,
  avgWordsPerCard,
  stemTolerance,
  onStemToleranceChange: handleStemToleranceChange,
  strictPunctuation,
  onStrictPunctuationChange: setStrictPunctuation,
  ladderMode,
  onLadderModeChange: handleLadderModeChange,
  batchSize,
  onBatchSizeChange: handleBatchSizeChange,
  cycleOrder,
  onCycleOrderChange: handleCycleOrderChange,
}) => (
  <>
    {/* Reps Setting - Sliding Scale */}
    <div className="flex flex-col gap-2.5 border-t border-[var(--border)] pt-3.5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <label htmlFor="encode-reps-slider" className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--warning)]" />
          <span>Blind typings required for the full combination &amp; short cards:</span>
          <span className="text-[11px] text-[var(--text-muted)] hidden sm:inline">
            • consecutive blind completions
          </span>
        </label>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span
            className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border ${getRepsBadgeClass(
              encodeReps
            )}`}
          >
            {getRepsLabel(encodeReps)}
          </span>
          <span className="text-xs font-bold text-[var(--text-primary)] bg-[var(--surface-1)] border border-[var(--border)] px-2.5 py-0.5 rounded-lg min-w-[50px] text-center shadow-xs">
            {encodeReps} {encodeReps === 1 ? 'rep' : 'reps'}
          </span>
        </div>
      </div>

      <div className="space-y-2 bg-[var(--surface-1)]/50 p-3 rounded-xl border border-[var(--border)]">
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-medium text-[var(--text-muted)] w-20 shrink-0">
            1 rep (Quick)
          </span>
          <input
            id="encode-reps-slider"
            type="range"
            min={1}
            max={10}
            step={1}
            value={encodeReps}
            onChange={e => handleEncodeRepsChange(parseInt(e.target.value, 10) || 1)}
            className="w-full h-2 bg-[var(--surface-2)] border border-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--warning)]"
          />
          <span className="text-[11px] font-medium text-[var(--text-muted)] w-20 shrink-0 text-right">
            10 reps (Max)
          </span>
        </div>

        {/* Live Rep Impact */}
        <div className="text-[11px] font-medium text-[var(--text-secondary)] flex items-center gap-1.5 pt-0.5">
          <span className="text-[var(--warning)] font-bold">•</span>
          <span>{getRepsDescription(encodeReps)}</span>
        </div>
      </div>
    </div>

    {/* Difficulty Sliding Scale: Words Typed At Once (% of card) */}
    <div className="flex flex-col gap-2.5 border-t border-[var(--border)] pt-3.5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <label htmlFor="chunk-difficulty-slider" className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
          <span>Typing difficulty (words typed at once):</span>
          <span className="text-[11px] text-[var(--text-muted)] hidden sm:inline">
            • harder = more words at once
          </span>
        </label>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <span
            className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border ${getDifficultyBadgeClass(
              chunkDifficulty
            )}`}
          >
            {getDifficultyLabel(chunkDifficulty)}
          </span>
          <span className="text-xs font-bold text-[var(--text-primary)] bg-[var(--surface-1)] border border-[var(--border)] px-2.5 py-0.5 rounded-lg min-w-[50px] text-center shadow-xs">
            {chunkDifficulty}%
          </span>
        </div>
      </div>

      <div className="space-y-2 bg-[var(--surface-1)]/50 p-3 rounded-xl border border-[var(--border)]">
        <div className="flex items-center gap-3">
          <span className="text-[11px] font-medium text-[var(--text-muted)] w-20 shrink-0">
            Easier (20%)
          </span>
          <input
            id="chunk-difficulty-slider"
            type="range"
            min={20}
            max={100}
            step={5}
            value={chunkDifficulty}
            onChange={e => handleChunkDifficultyChange(parseInt(e.target.value, 10) || 35)}
            className="w-full h-2 bg-[var(--surface-2)] border border-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--accent)]"
          />
          <span className="text-[11px] font-medium text-[var(--text-muted)] w-20 shrink-0 text-right">
            Full card (100%)
          </span>
        </div>

        {/* Live Word Count Impact */}
        <div className="text-[11px] font-medium text-[var(--text-secondary)] flex items-center gap-1.5 pt-0.5">
          <span className="text-[var(--accent)] font-bold">•</span>
          <span>{getDifficultyDescription(chunkDifficulty, avgWordsPerCard)}</span>
        </div>
      </div>
    </div>

    {/* Lenient Grading: stem tolerance toggle -- disabled (but not
        overwritten) while the deck's strict punctuation mode is on,
        since strict mode's near-miss tier -- the only thing this
        setting affects -- is unconditionally off. */}
    <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3.5">
      <div className="flex items-center justify-between gap-2">
        <label
          htmlFor="stem-tolerance-toggle"
          className={`text-xs text-[var(--text-secondary)] flex items-center gap-2 ${
            strictPunctuation ? 'opacity-50' : 'cursor-pointer'
          }`}
        >
          <span className="w-2 h-2 rounded-full bg-[var(--success)]" />
          <span>Forgive minor word endings (e.g. plurals):</span>
        </label>
        <button
          type="button"
          id="stem-tolerance-toggle"
          role="switch"
          aria-checked={stemTolerance}
          aria-disabled={strictPunctuation}
          disabled={strictPunctuation}
          onClick={() => handleStemToleranceChange(!stemTolerance)}
          className={`relative w-10 h-5.5 rounded-full transition-colors shrink-0 ${
            strictPunctuation ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'
          } ${
            stemTolerance ? 'bg-[var(--success)]' : 'bg-[var(--surface-2)] border border-[var(--border)]'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
              stemTolerance ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        {strictPunctuation
          ? 'Not used — strict mode requires exact words.'
          : 'When on, a typo-free answer that only differs by a plural or verb ending ' +
            '(e.g. "cat" vs "cats") counts as a close match instead of a miss. Turn this ' +
            'off for terminology decks where exact word endings matter (e.g. medical or ' +
            'legal vocabulary).'}
      </p>
    </div>

    {/* Punctuation must match toggle (per-deck) */}
    <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3.5">
      <div className="flex items-center justify-between gap-2">
        <label htmlFor="strict-punctuation-toggle" className="text-xs text-[var(--text-secondary)] flex items-center gap-2 cursor-pointer">
          <span className="w-2 h-2 rounded-full bg-[var(--warning)]" />
          <span>Punctuation must match:</span>
        </label>
        <button
          type="button"
          id="strict-punctuation-toggle"
          role="switch"
          aria-checked={strictPunctuation}
          onClick={() => setStrictPunctuation(!strictPunctuation)}
          className={`relative w-10 h-5.5 rounded-full transition-colors shrink-0 cursor-pointer ${
            strictPunctuation ? 'bg-[var(--warning)]' : 'bg-[var(--surface-2)] border border-[var(--border)]'
          }`}
        >
          <span
            className={`absolute top-0.5 left-0.5 w-4 h-4 rounded-full bg-white shadow-sm transition-transform ${
              strictPunctuation ? 'translate-x-4' : 'translate-x-0'
            }`}
          />
        </button>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        Every word must be exact. Hyphens, slashes and symbols count; brackets,
        quotes, commas, accents and end punctuation don't.
      </p>
    </div>

    {/* Combine ladder mode */}
    <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--warning)]" />
          <span>Combine ladder:</span>
        </span>
        <div className="flex items-center gap-1 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg p-0.5">
          <button
            type="button"
            id="ladder-mode-cumulative"
            onClick={() => handleLadderModeChange('cumulative')}
            className={`px-3 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              ladderMode === 'cumulative'
                ? 'bg-[var(--accent)] text-white shadow-xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Forward chaining
          </button>
          <button
            type="button"
            id="ladder-mode-exhaustive"
            onClick={() => handleLadderModeChange('exhaustive')}
            className={`px-3 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              ladderMode === 'exhaustive'
                ? 'bg-[var(--accent)] text-white shadow-xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Exhaustive
          </button>
        </div>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        Forward chaining (recommended) only re-verifies the growing prefix of a
        card's parts, so it needs far fewer repetitions once you've combined them
        once. Exhaustive re-drills every possible combination of parts and is kept
        only for comparison.
      </p>
    </div>

    {/* Batch size: how many cards are encoded together before a checkpoint */}
    <div className="flex flex-col gap-2.5 border-t border-[var(--border)] pt-3.5">
      <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
        <label htmlFor="batch-size-slider" className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--accent)]" />
          <span>Cards per batch before a checkpoint:</span>
        </label>
        <div className="flex items-center gap-2 self-start sm:self-auto">
          <button
            type="button"
            id="whole-deck-toggle"
            onClick={() => handleBatchSizeChange(batchSize <= 0 ? 5 : 0)}
            className={`text-xs font-semibold px-2.5 py-0.5 rounded-full border transition-all cursor-pointer ${
              batchSize <= 0
                ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
                : 'bg-[var(--surface-1)] text-[var(--text-secondary)] border-[var(--border)] hover:text-[var(--text-primary)]'
            }`}
          >
            Whole deck
          </button>
          <span className="text-xs font-bold text-[var(--text-primary)] bg-[var(--surface-1)] border border-[var(--border)] px-2.5 py-0.5 rounded-lg min-w-[50px] text-center shadow-xs">
            {batchSize <= 0 ? 'All cards' : `${batchSize} cards`}
          </span>
        </div>
      </div>

      {batchSize > 0 && (
        <div className="space-y-2 bg-[var(--surface-1)]/50 p-3 rounded-xl border border-[var(--border)]">
          <div className="flex items-center gap-3">
            <span className="text-[11px] font-medium text-[var(--text-muted)] w-20 shrink-0">3 (Small)</span>
            <input
              id="batch-size-slider"
              type="range"
              min={3}
              max={10}
              step={1}
              value={batchSize}
              onChange={e => handleBatchSizeChange(parseInt(e.target.value, 10) || 5)}
              className="w-full h-2 bg-[var(--surface-2)] border border-[var(--border)] rounded-lg appearance-none cursor-pointer accent-[var(--accent)]"
            />
            <span className="text-[11px] font-medium text-[var(--text-muted)] w-20 shrink-0 text-right">10 (Large)</span>
          </div>
        </div>
      )}

      <p className="text-[11px] text-[var(--text-muted)]">
        Cards are encoded a batch at a time, interleaved with each other, with a
        summary screen (and a chance to stop) between batches. "Whole deck" removes
        the checkpoints and interleaves every card in the deck together, like a
        single big batch.
      </p>
    </div>

    {/* Cycle review order */}
    <div className="flex flex-col gap-2 border-t border-[var(--border)] pt-3.5">
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
          <span className="w-2 h-2 rounded-full bg-[var(--success)]" />
          <span>Cycle review order:</span>
        </span>
        <div className="flex items-center gap-1 bg-[var(--surface-1)] border border-[var(--border)] rounded-lg p-0.5">
          <button
            type="button"
            id="cycle-order-shuffled"
            aria-pressed={cycleOrder === 'shuffled'}
            onClick={() => handleCycleOrderChange('shuffled')}
            className={`px-3 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              cycleOrder === 'shuffled'
                ? 'bg-[var(--accent)] text-white shadow-xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            Shuffled
          </button>
          <button
            type="button"
            id="cycle-order-in-order"
            aria-pressed={cycleOrder === 'inOrder'}
            onClick={() => handleCycleOrderChange('inOrder')}
            className={`px-3 py-1 rounded-md text-xs font-semibold transition-all cursor-pointer ${
              cycleOrder === 'inOrder'
                ? 'bg-[var(--accent)] text-white shadow-xs'
                : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
            }`}
          >
            In order
          </button>
        </div>
      </div>
      <p className="text-[11px] text-[var(--text-muted)]">
        Shuffled mixes each batch's cards and brings misses back a few cards later.
        In order goes through the batch from its first card to its last, then starts
        another pass with whatever isn't mastered yet (misses included), still in
        order. Only affects the review cycle, not encoding.
      </p>
    </div>
  </>
);
