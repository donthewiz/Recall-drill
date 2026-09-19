import React from 'react';
import { X, Keyboard, Split, Layers, RotateCw, CheckCircle2 } from 'lucide-react';

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
                1. Automatic Chunking &amp; Progressive Chaining
              </h4>
              <p>
                Answers longer than 5 words are broken into small 4-word chunks. You first encode each piece individually until you type it from memory without prompts.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-lg bg-[var(--warning-bg)] text-[var(--warning)] flex items-center justify-center shrink-0 mt-0.5">
              <Layers size={15} />
            </div>
            <div>
              <h4 className="font-semibold text-[var(--text-primary)] mb-0.5">
                2. Hierarchical Remediation
              </h4>
              <p>
                When you combine chunks and make a mistake, Recall Drill uses sequence alignment to find the exact sub-phrase you missed, isolates it, and drills down to single words if needed before returning to the full sentence.
              </p>
            </div>
          </div>

          <div className="flex gap-3">
            <div className="w-7 h-7 rounded-lg bg-[var(--success-bg)] text-[var(--success)] flex items-center justify-center shrink-0 mt-0.5">
              <RotateCw size={15} />
            </div>
            <div>
              <h4 className="font-semibold text-[var(--text-primary)] mb-0.5">
                3. Interleaved Cycling (Spaced Retrieval)
              </h4>
              <p>
                Once encoded, items are shuffled into a review queue. An item is only marked <strong>Mastered</strong> after 2 correct recall trials separated by other items.
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
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Enter</kbd>: Check answer or advance to next item</li>
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Esc</kbd>: Show answer when blind prompt is active</li>
                <li><kbd className="px-1.5 py-0.5 bg-[var(--surface-1)] border border-[var(--border)] rounded mono">Tab</kbd>: Inserts a real tab character inside the deck editor</li>
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
