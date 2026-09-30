import React, { useState } from 'react';
import { Check, Folder, FolderPlus, FolderTree, Move } from 'lucide-react';
import { DeckFolder } from '../../types';
import { getFolderDescendantIds } from '../../utils/drillEngine';
import { ModalShell, primaryButtonClass, secondaryButtonClass } from './ModalShell';

export interface MovingItem {
  type: 'deck' | 'folder';
  id: string;
  name: string;
}

interface FolderOption {
  id: string | null;
  name: string;
  depth: number;
}

// Indented folder hierarchy for the destination picker, Root first.
// excludedIds (and their subtrees) are left out.
function buildFolderTreeOptions(
  folders: DeckFolder[],
  excludedIds: string[],
  parentId: string | null = null,
  depth: number = 0
): FolderOption[] {
  const list: FolderOption[] = depth === 0 ? [{ id: null, name: 'Root (All Decks)', depth: 0 }] : [];
  for (const child of folders.filter(f => f.parentId === parentId && !excludedIds.includes(f.id))) {
    list.push({ id: child.id, name: child.name, depth: depth + 1 });
    list.push(...buildFolderTreeOptions(folders, excludedIds, child.id, depth + 1));
  }
  return list;
}

interface MoveModalProps {
  item: MovingItem;
  folders: DeckFolder[];
  initialDestination: string | null;
  // Creates a folder under parentId and returns it (the caller refreshes
  // the library), so the new folder can be selected right away.
  onCreateFolder: (name: string, parentId: string | null) => DeckFolder;
  onConfirm: (destination: string | null) => void;
  onClose: () => void;
}

// Move a deck or a folder into another folder (or Root).
export const MoveModal: React.FC<MoveModalProps> = ({
  item,
  folders,
  initialDestination,
  onCreateFolder,
  onConfirm,
  onClose,
}) => {
  const [destination, setDestination] = useState<string | null>(initialDestination);
  const [showNewFolder, setShowNewFolder] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  // A folder can't move into itself or its own subtree.
  const excludedIds = item.type === 'folder' ? [item.id, ...getFolderDescendantIds(item.id, folders)] : [];

  const createFolder = () => {
    const trimmed = newFolderName.trim();
    if (!trimmed) return;
    const created = onCreateFolder(trimmed, destination);
    setDestination(created.id);
    setNewFolderName('');
    setShowNewFolder(false);
  };

  return (
    <ModalShell
      icon={<Move size={18} className="text-[var(--accent)]" />}
      title={item.type === 'deck' ? `Move or Add "${item.name}" to Folder` : `Move Folder "${item.name}"`}
      onClose={onClose}
    >
      <p className="text-xs text-[var(--text-secondary)]">
        Choose the target destination folder. Sub-decks and sub-folders can be nested to any depth:
      </p>

      <div className="max-h-60 overflow-y-auto space-y-1 pr-1 border border-[var(--border)] rounded-xl p-2 bg-[var(--surface-1)]">
        {buildFolderTreeOptions(folders, excludedIds).map(opt => {
          const isSelected = destination === opt.id;
          return (
            <button
              key={opt.id || 'root'}
              type="button"
              onClick={() => setDestination(opt.id)}
              className={`w-full text-left px-3 py-2 rounded-lg text-xs font-medium flex items-center justify-between transition-colors cursor-pointer ${
                isSelected
                  ? 'bg-[var(--accent)] text-white font-bold'
                  : 'hover:bg-[var(--surface-2)] text-[var(--text-primary)]'
              }`}
              style={{ paddingLeft: `${Math.max(12, opt.depth * 16 + 12)}px` }}
            >
              <span className="flex items-center gap-1.5 truncate">
                {opt.id === null ? (
                  <FolderTree size={14} className={isSelected ? 'text-white' : 'text-[var(--accent)]'} />
                ) : (
                  <Folder size={14} className={isSelected ? 'text-white' : 'text-[var(--accent)]'} />
                )}
                <span className="truncate">{opt.name}</span>
              </span>
              {isSelected && <Check size={14} className="shrink-0" />}
            </button>
          );
        })}
      </div>

      {/* Inline New Folder Creation */}
      <div className="pt-1 border-t border-[var(--border)]/60">
        {showNewFolder ? (
          <div className="space-y-2 bg-[var(--surface-1)] p-3 rounded-xl border border-[var(--border)]">
            <span className="text-[11px] font-semibold text-[var(--text-secondary)] block">
              Create new folder inside selected destination:
            </span>
            <div className="flex items-center gap-2">
              <input
                type="text"
                autoFocus
                value={newFolderName}
                onChange={e => setNewFolderName(e.target.value)}
                onKeyDown={e => {
                  if (e.key === 'Enter') createFolder();
                  if (e.key === 'Escape') setShowNewFolder(false);
                }}
                placeholder="Folder name..."
                className="flex-1 bg-[var(--surface-card)] text-[var(--text-primary)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-xs font-medium focus:border-[var(--accent)] outline-none"
              />
              <button
                type="button"
                disabled={!newFolderName.trim()}
                onClick={createFolder}
                className="px-3 py-1.5 rounded-lg text-xs font-semibold bg-[var(--accent)] text-white disabled:opacity-50 cursor-pointer"
              >
                Create
              </button>
              <button
                type="button"
                onClick={() => setShowNewFolder(false)}
                className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] px-1.5 cursor-pointer"
              >
                Cancel
              </button>
            </div>
          </div>
        ) : (
          <button
            type="button"
            onClick={() => setShowNewFolder(true)}
            className="text-xs text-[var(--accent)] hover:underline font-semibold flex items-center gap-1.5 cursor-pointer"
          >
            <FolderPlus size={14} />
            <span>+ Create new folder here</span>
          </button>
        )}
      </div>

      <div className="flex items-center justify-end gap-2 pt-2">
        <button type="button" onClick={onClose} className={secondaryButtonClass}>
          Cancel
        </button>
        <button type="button" onClick={() => onConfirm(destination)} className={primaryButtonClass}>
          Move Here
        </button>
      </div>
    </ModalShell>
  );
};
