import React from 'react';
import { X } from 'lucide-react';

interface ModalShellProps {
  icon: React.ReactNode;
  title: React.ReactNode;
  subtitle?: React.ReactNode;
  onClose: () => void;
  // Tailwind max-width class for the card.
  widthClass?: string;
  children: React.ReactNode;
}

// The overlay, card, and title row shared by the deck library's modals.
export const ModalShell: React.FC<ModalShellProps> = ({
  icon,
  title,
  subtitle,
  onClose,
  widthClass = 'max-w-md',
  children,
}) => (
  <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/50 backdrop-blur-xs animate-in fade-in duration-150">
    <div
      className={`w-full ${widthClass} bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl p-6 shadow-2xl space-y-4`}
    >
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2 min-w-0">
          {icon}
          {subtitle ? (
            <div>
              <h3 className="text-base font-bold text-[var(--text-primary)]">{title}</h3>
              <p className="text-[11px] text-[var(--text-muted)]">{subtitle}</p>
            </div>
          ) : (
            <h3 className="text-base font-bold text-[var(--text-primary)] truncate">{title}</h3>
          )}
        </div>
        <button
          type="button"
          onClick={onClose}
          className="p-1 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer"
        >
          <X size={16} />
        </button>
      </div>
      {children}
    </div>
  </div>
);

export const secondaryButtonClass =
  'px-4 py-2 rounded-xl text-xs font-semibold text-[var(--text-secondary)] hover:bg-[var(--surface-2)] transition-colors cursor-pointer';

export const primaryButtonClass =
  'px-4 py-2 rounded-xl text-xs font-semibold bg-[var(--accent)] text-white hover:bg-[var(--accent-hover)] transition-all shadow-xs disabled:opacity-50 cursor-pointer';
