import React, { useState } from 'react';
import { Folder } from 'lucide-react';
import { ModalShell, primaryButtonClass, secondaryButtonClass } from './ModalShell';

interface FolderNameModalProps {
  title: string;
  initialName: string;
  submitLabel: string;
  onSave: (name: string) => void;
  onClose: () => void;
}

// Create or rename a folder.
export const FolderNameModal: React.FC<FolderNameModalProps> = ({
  title,
  initialName,
  submitLabel,
  onSave,
  onClose,
}) => {
  const [name, setName] = useState(initialName);
  const save = () => {
    const trimmed = name.trim();
    if (trimmed) onSave(trimmed);
  };

  return (
    <ModalShell icon={<Folder size={18} className="text-[var(--accent)]" />} title={title} onClose={onClose}>
      <div>
        <label className="block text-xs font-semibold text-[var(--text-secondary)] mb-1.5">Folder name</label>
        <input
          type="text"
          autoFocus
          value={name}
          onChange={e => setName(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter') save();
            if (e.key === 'Escape') onClose();
          }}
          placeholder="e.g. Cardiology, Irregular Verbs, Calculus..."
          className="w-full bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-3.5 py-2.5 text-sm font-medium focus:border-[var(--accent)] outline-none transition-all placeholder:text-[var(--text-muted)]"
        />
      </div>

      <div className="flex items-center justify-end gap-2 pt-2">
        <button type="button" onClick={onClose} className={secondaryButtonClass}>
          Cancel
        </button>
        <button type="button" disabled={!name.trim()} onClick={save} className={primaryButtonClass}>
          {submitLabel}
        </button>
      </div>
    </ModalShell>
  );
};
