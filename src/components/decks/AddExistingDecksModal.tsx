import React, { useState } from 'react';
import { CheckSquare, FolderInput, Search, Square } from 'lucide-react';
import { DeckFolder, SavedDeckEntry } from '../../types';
import { getFolderFullPath } from '../../utils/drillEngine';
import { ModalShell, primaryButtonClass, secondaryButtonClass } from './ModalShell';

interface AddExistingDecksModalProps {
  folder: DeckFolder;
  decks: SavedDeckEntry[];
  folders: DeckFolder[];
  // Each returns whether the move succeeded.
  onAddOne: (slug: string) => boolean;
  onAddMany: (slugs: string[]) => boolean;
  onClose: () => void;
}

// Pick library decks from other folders to move into `folder`.
export const AddExistingDecksModal: React.FC<AddExistingDecksModalProps> = ({
  folder,
  decks,
  folders,
  onAddOne,
  onAddMany,
  onClose,
}) => {
  const [search, setSearch] = useState('');
  const [selected, setSelected] = useState<string[]>([]);

  const eligibleDecks = decks.filter(d => (d.folderId || null) !== folder.id);
  const filteredEligible = eligibleDecks.filter(d => d.name.toLowerCase().includes(search.toLowerCase()));
  const allFilteredSelected = filteredEligible.length > 0 && filteredEligible.every(d => selected.includes(d.slug));

  const toggle = (slug: string) =>
    setSelected(prev => (prev.includes(slug) ? prev.filter(s => s !== slug) : [...prev, slug]));

  const toggleAll = (slugs: string[]) => setSelected(selected.length === slugs.length ? [] : slugs);

  const addOne = (slug: string) => {
    if (onAddOne(slug)) setSelected(prev => prev.filter(s => s !== slug));
  };

  const addSelected = () => {
    if (selected.length > 0) onAddMany(selected);
  };

  return (
    <ModalShell
      icon={<FolderInput size={20} className="text-[var(--accent)]" />}
      title={<>Add Existing Decks to &ldquo;{folder.name}&rdquo;</>}
      subtitle="Select existing decks from your library to add or move into this folder."
      widthClass="max-w-lg"
      onClose={onClose}
    >
      {eligibleDecks.length > 0 ? (
        <div className="space-y-3">
          <div className="flex items-center gap-2">
            <div className="relative flex-1">
              <Search size={14} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
              <input
                type="text"
                value={search}
                onChange={e => setSearch(e.target.value)}
                placeholder="Filter existing decks..."
                className="w-full bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl pl-8 pr-3 py-1.5 text-xs font-medium focus:border-[var(--accent)] outline-none"
              />
            </div>

            {filteredEligible.length > 0 && (
              <button
                type="button"
                onClick={() => toggleAll(filteredEligible.map(d => d.slug))}
                className="px-2.5 py-1.5 rounded-xl text-xs font-semibold bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] shrink-0 cursor-pointer"
              >
                {allFilteredSelected ? 'Deselect All' : `Select All (${filteredEligible.length})`}
              </button>
            )}
          </div>

          {/* Decks Selection List */}
          <div className="max-h-72 overflow-y-auto space-y-2 pr-1 border border-[var(--border)] rounded-xl p-2 bg-[var(--surface-1)]">
            {filteredEligible.length > 0 ? (
              filteredEligible.map(deck => {
                const isSelected = selected.includes(deck.slug);
                return (
                  <div
                    key={deck.slug}
                    onClick={() => toggle(deck.slug)}
                    className={`p-3 rounded-xl border transition-all cursor-pointer flex items-center justify-between gap-3 ${
                      isSelected
                        ? 'bg-[var(--accent-bg)] border-[var(--accent)] ring-1 ring-[var(--accent)]'
                        : 'bg-[var(--surface-card)] hover:bg-[var(--surface-2)] border-[var(--border)]'
                    }`}
                  >
                    <div className="flex items-center gap-3 min-w-0">
                      <div className="text-[var(--accent)] shrink-0">
                        {isSelected ? <CheckSquare size={18} /> : <Square size={18} className="text-[var(--text-muted)]" />}
                      </div>
                      <div className="min-w-0">
                        <h4 className="text-xs font-bold text-[var(--text-primary)] truncate">{deck.name}</h4>
                        <p className="text-[11px] text-[var(--text-muted)] flex items-center gap-1.5 mt-0.5">
                          <span>
                            {deck.count} {deck.count === 1 ? 'card' : 'cards'}
                          </span>
                          <span>•</span>
                          <span className="truncate">
                            Currently in: {getFolderFullPath(deck.folderId || null, folders)}
                          </span>
                        </p>
                      </div>
                    </div>

                    <button
                      type="button"
                      onClick={e => {
                        e.stopPropagation();
                        addOne(deck.slug);
                      }}
                      className="px-2.5 py-1 rounded-lg text-xs font-semibold bg-[var(--surface-2)] hover:bg-[var(--accent)] text-[var(--text-primary)] hover:text-white border border-[var(--border)] hover:border-transparent transition-all shrink-0 cursor-pointer"
                      title="Add this deck immediately"
                    >
                      + Add
                    </button>
                  </div>
                );
              })
            ) : (
              <div className="text-center py-6 text-xs text-[var(--text-muted)]">
                No decks match &ldquo;{search}&rdquo;.
              </div>
            )}
          </div>
        </div>
      ) : (
        <div className="text-center py-8 px-4 bg-[var(--surface-1)] rounded-xl border border-[var(--border)]">
          <p className="text-xs font-semibold text-[var(--text-primary)]">All library decks are already in this folder!</p>
          <p className="text-[11px] text-[var(--text-secondary)] mt-1">
            To add more decks, create a new deck or move decks from other folders.
          </p>
        </div>
      )}

      <div className="flex items-center justify-between pt-2 border-t border-[var(--border)]/60">
        <span className="text-xs text-[var(--text-muted)]">
          {selected.length} of {eligibleDecks.length} selected
        </span>

        <div className="flex items-center gap-2">
          <button type="button" onClick={onClose} className={secondaryButtonClass}>
            Cancel
          </button>
          <button type="button" disabled={selected.length === 0} onClick={addSelected} className={primaryButtonClass}>
            Add {selected.length > 0 ? `Selected (${selected.length})` : 'Selected'}
          </button>
        </div>
      </div>
    </ModalShell>
  );
};
