import React from 'react';
import { Upload } from 'lucide-react';
import { BackupPayload } from '../../utils/backup';
import { ModalShell, secondaryButtonClass } from './ModalShell';

interface ImportBackupModalProps {
  payload: BackupPayload;
  onConfirm: (mode: 'merge' | 'replace') => void;
  onClose: () => void;
}

// Confirms how a validated backup file is brought in: merge or replace.
export const ImportBackupModal: React.FC<ImportBackupModalProps> = ({ payload, onConfirm, onClose }) => (
  <ModalShell icon={<Upload size={18} className="text-[var(--accent)]" />} title="Import Backup" onClose={onClose}>
    <p className="text-xs text-[var(--text-secondary)]">
      This file contains <strong>{payload.decks.length}</strong> deck{payload.decks.length === 1 ? '' : 's'} and{' '}
      <strong>{payload.folders.length}</strong> folder{payload.folders.length === 1 ? '' : 's'}, exported{' '}
      {new Date(payload.exportedAt).toLocaleString()}. Choose how to bring it in:
    </p>

    <div className="space-y-2.5">
      <button
        type="button"
        onClick={() => onConfirm('merge')}
        className="w-full text-left px-4 py-3 rounded-xl border border-[var(--border)] hover:border-[var(--accent)] bg-[var(--surface-1)] transition-all cursor-pointer"
      >
        <span className="block text-sm font-bold text-[var(--text-primary)]">Merge</span>
        <span className="block text-[11px] text-[var(--text-secondary)] mt-0.5">
          Add decks and folders from this file that you don&apos;t already have (matched by slug). Nothing existing is
          changed or removed.
        </span>
      </button>
      <button
        type="button"
        onClick={() => onConfirm('replace')}
        className="w-full text-left px-4 py-3 rounded-xl border border-red-500/30 hover:border-red-500 bg-red-500/5 transition-all cursor-pointer"
      >
        <span className="block text-sm font-bold text-red-600 dark:text-red-400">Replace everything</span>
        <span className="block text-[11px] text-[var(--text-secondary)] mt-0.5">
          Permanently deletes all of your current decks and folders, then restores exactly what&apos;s in this file.
        </span>
      </button>
    </div>

    <div className="flex items-center justify-end pt-1">
      <button type="button" onClick={onClose} className={secondaryButtonClass}>
        Cancel
      </button>
    </div>
  </ModalShell>
);
