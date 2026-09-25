import React from 'react';
import { X, Keyboard, Split, RotateCw, CheckCircle2 } from 'lucide-react';

interface HelpModalProps {
  isOpen: boolean;
  onClose: () => void;
}

export const HelpModal: React.FC<HelpModalProps> = ({ isOpen, onClose }) => {
  if (!isOpen) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/40 backdrop-blur-xs">
      <div className="bg-[var(--surface-2)] border border-[var(--border)] rounded-2xl max-w-lg w-full p-6 shadow-xl space-y-4 max-h-[90vh] overflow-y-auto">
        <div className="flex items-center justify-between border-b border-[var(--border)] pb-3">
          <h3 className="font-semibold text-base text-[var(--text-primary)] flex items-center gap-2">
            How Recall Drill Works
          </h3>
          <button
            type="button"
            onClick={onClose}
            className="p-1 rounded-lg text-[var(--text-secondary)] hover:bg-[var(--surface-1)]"
          >
            <X size={18} />
          </button>
        </div>

        <div className="space-y-3.5 text-xs text-[var(--text-secondary)] leading-relaxed">
          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-lg bg-[var(--accent-bg)] text-[var(--accent)] flex items-center justify-center shrink-0 mt-0.5">
              <Split size={15} />
            </div>
            <div>
              <h4 className="font-semibold text-[var(--text-primary)] mb-0.5">
                1. Chunking &amp; the Cue Ladder
              </h4>
              <p>
                Answers longer than 8 words are split into chunks (the typing-difficulty slider controls how big); answers at or under that length are tested as a whole from the start — a chunk-by-chunk ladder is only worth the overhead once an answer is too long to hold in your head at once. Each chunk opens with a quick read: its text is shown once, nothing to type, just press Enter to continue — then needs exactly one correct answer typed fully from memory to move on, no matter how high the &ldquo;blind typings&rdquo; slider is set. Once every chunk is learned, combining them uses forward chaining by default: it only re-checks the growing prefix of the answer — parts 1-2, then 1-3, and so on — instead of every possible combination, and your first attempt at any new combination shows a first-letter cue (e.g. &ldquo;T__ h____ p____ b____&rdquo;) rather than the answer itself, so you're always retrieving, never copying.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-lg bg-[var(--warning-bg)] text-[var(--warning)] flex items-center justify-center shrink-0 mt-0.5">
              <CheckCircle2 size={15} />
            </div>
            <div>
              <h4 className="font-semibold text-[var(--text-primary)] mb-0.5">
                2. Lenient Grading &amp; Precision Remediation
              </h4>
              <p>
                Small slips are forgiven: dropping or swapping a small filler word like &ldquo;the&rdquo; or &ldquo;and&rdquo; counts as a close match, and so does a minor plural/verb-ending difference — both still advance your streak (tracked separately from real misses). The ending-forgiveness is a global setting, and any deck with &ldquo;Punctuation must match&rdquo; turned on disables it and requires every word exactly, with no close-match forgiveness at all. If you get a combination wrong, Recall Drill aligns your answer against the target word by word to find exactly which chunk you missed, isolates it, and — if you keep missing — splits it into smaller and smaller sub-phrases, down to a single word if needed, before returning you to the full combination. A wrong answer pauses so you can compare against the target before continuing; if you're sure your answer was right, &ldquo;Count as correct&rdquo; overrides it — the streak advances, but the miss still counts in your stats.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-lg bg-[var(--success-bg)] text-[var(--success)] flex items-center justify-center shrink-0 mt-0.5">
              <RotateCw size={15} />
            </div>
            <div>
              <h4 className="font-semibold text-[var(--text-primary)] mb-0.5">
                3. Batched Encoding &amp; Spaced Cycling
              </h4>
              <p>
                Cards are encoded a batch at a time (5 by default, adjustable from 3-10, or the whole deck at once) instead of one card being drilled to completion before the next begins — within a batch you rotate to the next unfinished card after every chunk, combination, or fixed weak spot. Once a batch is fully encoded you get a summary and a choice to continue or stop before the next batch. From there, encoded cards enter a review cycle — shuffled by default, or in deck order if you choose &ldquo;In order&rdquo; — and a card is marked <strong>Mastered</strong> once you recall it correctly twice, with the rest of the pass in between. The exception is when only one card in the batch is left to master — it comes straight back with nothing in between.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-lg bg-[var(--surface-1)] text-[var(--text-primary)] flex items-center justify-center shrink-0 mt-0.5 border border-[var(--border)]">
              <Keyboard size={15} />
            </div>
            <div>
              <h4 className="font-semibold text-[var(--text-primary)] mb-0.5">
                Keyboard Shortcuts
              </h4>
              <ul className="list-disc list-inside space-y-1">
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Enter</kbd>: Check your answer, or continue once it's graded</li>
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Esc</kbd>: Show the answer — resets your streak on this part to zero, but never counts as a miss (still counts as an attempt)</li>
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Ctrl+Enter</kbd>: &ldquo;Count as correct&rdquo; override, right after a wrong answer (the miss still shows in your stats)</li>
                <li><strong>Edit card</strong>: fix the current card's front or back mid-session (<kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Ctrl+Enter</kbd> saves, <kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Esc</kbd> cancels) — a real answer change restarts that card; a wording-only fix keeps your progress</li>
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Tab</kbd>: Inserts a real tab character inside the bulk deck editor</li>
              </ul>
            </div>
          </div>
        </div>

        <div className="pt-2 border-t border-[var(--border)] flex justify-end">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-2 bg-[var(--accent)] text-white text-xs font-semibold rounded-lg hover:opacity-90 cursor-pointer"
          >
            Got it
          </button>
        </div>
      </div>
    </div>
  );
};
