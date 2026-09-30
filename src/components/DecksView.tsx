import React, { useState, useEffect, useRef } from 'react';
import {
  SavedDeckEntry,
  DeckItem,
  DeckFolder,
} from '../types';
import {
  loadDeckIndex,
  deckHasPayload,
  getDeckFromStorage,
  deleteDeckFromStorage,
  getSessionState,
  loadFolderIndex,
  createFolder,
  renameFolder,
  deleteFolder,
  moveFolder,
  moveDeckToFolder,
  moveMultipleDecksToFolder,
  getFolderPath,
  getFolderFullPath,
  getAllCardsInFolderTree,
} from '../utils/drillEngine';
import {
  BackupPayload,
  PersistenceStatus,
  exportAllDecks,
  triggerBackupDownload,
  getLastExportDate,
  daysSince,
  EXPORT_STALE_DAYS,
  validateBackupPayload,
  importBackupPayload,
} from '../utils/backup';
import {
  FolderOpen,
  Folder,
  FolderPlus,
  Plus,
  Play,
  Trash2,
  Edit3,
  Layers,
  Search,
  ArrowRight,
  CheckCircle2,
  ChevronRight,
  Move,
  X,
  FolderTree,
  FolderInput,
  FolderDown,
  GripVertical,
  Download,
  Upload,
  ShieldCheck,
  ShieldAlert,
  ShieldQuestion,
  AlertTriangle,
} from 'lucide-react';
import { FolderNameModal } from './decks/FolderNameModal';
import { MoveModal, MovingItem } from './decks/MoveModal';
import { AddExistingDecksModal } from './decks/AddExistingDecksModal';
import { ImportBackupModal } from './decks/ImportBackupModal';

interface DecksViewProps {
  onSelectDeck: (deckName: string, items: DeckItem[], startInEditMode?: boolean, folderId?: string | null) => void;
  onQuickStartDeck: (deckName: string, items: DeckItem[]) => void;
  onCreateNewDeck: (folderId?: string | null) => void;
  onPracticeFolder?: (folderName: string, items: DeckItem[]) => void;
  storagePersistStatus?: PersistenceStatus;
}

export const DecksView: React.FC<DecksViewProps> = ({
  onSelectDeck,
  onQuickStartDeck,
  onCreateNewDeck,
  onPracticeFolder,
  storagePersistStatus = 'checking',
}) => {
  const [folders, setFolders] = useState<DeckFolder[]>([]);
  const [savedDecks, setSavedDecks] = useState<SavedDeckEntry[]>([]);
  const [currentFolderId, setCurrentFolderId] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');

  // Drag and Drop state
  const [draggedDeckSlug, setDraggedDeckSlug] = useState<string | null>(null);
  const [dragOverTargetId, setDragOverTargetId] = useState<string | null | 'ROOT'>(null);

  // Toast notifications for user actions
  const [toastMessage, setToastMessage] = useState<{ text: string; type: 'success' | 'info' } | null>(null);

  // Add Existing Decks to Folder modal state
  const [showAddExistingModal, setShowAddExistingModal] = useState(false);

  // Deletion confirm states
  const [confirmDeleteSlug, setConfirmDeleteSlug] = useState<string | null>(null);
  const [confirmDeleteFolderId, setConfirmDeleteFolderId] = useState<string | null>(null);

  // Folder creation / rename modal (the modal owns its own input state)
  const [folderModal, setFolderModal] = useState<{ mode: 'create' } | { mode: 'rename'; folder: DeckFolder } | null>(null);

  // Move modal target (a deck or a folder)
  const [movingItem, setMovingItem] = useState<MovingItem | null>(null);

  // Backup / restore state
  const [lastExportAt, setLastExportAt] = useState<string | null>(null);
  const [pendingImport, setPendingImport] = useState<BackupPayload | null>(null);
  const [importError, setImportError] = useState<string | null>(null);
  const importFileInputRef = useRef<HTMLInputElement>(null);

  const refreshData = () => {
    // deckHasPayload: drop any phantom deck-index entry left behind by a
    // pre-fix folder-practice session (a folder is not a deck) so it
    // doesn't render as a dead 0-card deck -- see drillEngine.ts.
    const idx = loadDeckIndex().filter(deckHasPayload);
    const flds = loadFolderIndex();
    setSavedDecks(idx);
    setFolders(flds);
    setLastExportAt(getLastExportDate());
  };

  useEffect(() => {
    refreshData();
  }, []);

  // Handle deck deletion
  const handleDeleteDeck = (e: React.MouseEvent, slug: string) => {
    e.stopPropagation();
    deleteDeckFromStorage(slug);
    refreshData();
    setConfirmDeleteSlug(null);
  };

  // Handle folder deletion
  const handleDeleteFolder = (e: React.MouseEvent, folderId: string) => {
    e.stopPropagation();
    deleteFolder(folderId, true);
    if (currentFolderId === folderId) {
      // If we're inside the folder being deleted, jump up to parent
      const current = folders.find(f => f.id === folderId);
      setCurrentFolderId(current ? current.parentId : null);
    }
    refreshData();
    setConfirmDeleteFolderId(null);
  };

  const handleOpenDeck = (slug: string, name: string, folderId?: string | null) => {
    const items = getDeckFromStorage(slug);
    if (items && items.length > 0) {
      onSelectDeck(name, items, true, folderId);
    } else {
      onSelectDeck(name, [], true, folderId);
    }
  };

  const handleQuickStart = (e: React.MouseEvent, slug: string, name: string) => {
    e.stopPropagation();
    const items = getDeckFromStorage(slug);
    if (items && items.length > 0) {
      onQuickStartDeck(name, items);
    }
  };

  // Practice all cards in the current folder tree
  const handlePracticeCurrentFolder = () => {
    const allCards = getAllCardsInFolderTree(currentFolderId);
    if (allCards.length === 0) return;
    const folderName = currentFolderId
      ? folders.find(f => f.id === currentFolderId)?.name || 'Folder practice'
      : 'All Decks';

    if (onPracticeFolder) {
      onPracticeFolder(folderName, allCards);
    } else {
      onQuickStartDeck(folderName, allCards);
    }
  };

  // Folder modal handlers
  const openCreateFolderModal = () => setFolderModal({ mode: 'create' });

  const openRenameFolderModal = (e: React.MouseEvent, folder: DeckFolder) => {
    e.stopPropagation();
    setFolderModal({ mode: 'rename', folder });
  };

  const handleSaveFolderModal = (name: string) => {
    if (!folderModal) return;
    if (folderModal.mode === 'create') {
      createFolder(name, currentFolderId);
    } else {
      renameFolder(folderModal.folder.id, name);
    }
    refreshData();
    setFolderModal(null);
  };

  // Move handlers
  const openMoveModal = (e: React.MouseEvent, type: 'deck' | 'folder', id: string, name: string) => {
    e.stopPropagation();
    setMovingItem({ type, id, name });
  };

  const handleConfirmMove = (destination: string | null) => {
    if (!movingItem) return;
    const targetFolder = destination ? folders.find(f => f.id === destination) : null;
    const targetName = targetFolder ? `"${targetFolder.name}"` : 'Root';
    if (movingItem.type === 'deck') {
      moveDeckToFolder(movingItem.id, destination);
      showToast(`Moved "${movingItem.name}" to ${targetName}`);
    } else {
      moveFolder(movingItem.id, destination);
      showToast(`Moved folder "${movingItem.name}" to ${targetName}`);
    }
    refreshData();
    setMovingItem(null);
  };

  const showToast = (text: string, type: 'success' | 'info' = 'success') => {
    setToastMessage({ text, type });
    setTimeout(() => {
      setToastMessage(prev => (prev?.text === text ? null : prev));
    }, 3200);
  };

  // Drag and Drop handlers
  const handleDragStartDeck = (e: React.DragEvent, slug: string) => {
    e.dataTransfer.setData('text/plain', slug);
    e.dataTransfer.effectAllowed = 'move';
    setDraggedDeckSlug(slug);
  };

  const handleDragEndDeck = () => {
    setDraggedDeckSlug(null);
    setDragOverTargetId(null);
  };

  const handleDragOverTarget = (e: React.DragEvent, targetId: string | null) => {
    e.preventDefault();
    e.dataTransfer.dropEffect = 'move';
    const targetKey = targetId === null ? 'ROOT' : targetId;
    if (dragOverTargetId !== targetKey) {
      setDragOverTargetId(targetKey);
    }
  };

  const handleDragLeaveTarget = (e: React.DragEvent, targetId: string | null) => {
    e.preventDefault();
    const targetKey = targetId === null ? 'ROOT' : targetId;
    if (dragOverTargetId === targetKey) {
      setDragOverTargetId(null);
    }
  };

  const handleDropOnTarget = (e: React.DragEvent, targetFolderId: string | null) => {
    e.preventDefault();
    const slug = e.dataTransfer.getData('text/plain') || draggedDeckSlug;
    if (!slug) {
      setDraggedDeckSlug(null);
      setDragOverTargetId(null);
      return;
    }

    const deck = savedDecks.find(d => d.slug === slug);
    if (!deck) {
      setDraggedDeckSlug(null);
      setDragOverTargetId(null);
      return;
    }

    // If deck is already in target folder, no-op
    if ((deck.folderId || null) === (targetFolderId || null)) {
      setDraggedDeckSlug(null);
      setDragOverTargetId(null);
      return;
    }

    const ok = moveDeckToFolder(slug, targetFolderId);
    if (ok) {
      refreshData();
      const targetFolder = targetFolderId ? folders.find(f => f.id === targetFolderId) : null;
      const targetName = targetFolder ? `"${targetFolder.name}"` : 'Root (All Decks)';
      showToast(`Moved "${deck.name}" into ${targetName}`);
    }
    setDraggedDeckSlug(null);
    setDragOverTargetId(null);
  };

  // Add Existing Decks handlers
  const openAddExistingModal = () => setShowAddExistingModal(true);

  const handleAddSingleExistingDeck = (slug: string): boolean => {
    if (!currentFolderId) return false;
    const deck = savedDecks.find(d => d.slug === slug);
    const ok = moveDeckToFolder(slug, currentFolderId);
    if (ok) {
      refreshData();
      showToast(`Added "${deck?.name || 'Deck'}" to "${currentFolder?.name || 'folder'}"`);
    }
    return ok;
  };

  const handleAddSelectedDecks = (slugs: string[]): boolean => {
    if (!currentFolderId || slugs.length === 0) return false;
    const ok = moveMultipleDecksToFolder(slugs, currentFolderId);
    if (ok) {
      refreshData();
      showToast(`Added ${slugs.length} deck${slugs.length > 1 ? 's' : ''} to "${currentFolder?.name || 'folder'}"`);
      setShowAddExistingModal(false);
    }
    return ok;
  };

  const handleCreateFolderInMoveModal = (name: string, parentId: string | null) => {
    const created = createFolder(name, parentId);
    refreshData();
    showToast(`Created folder "${created.name}"`);
    return created;
  };

  // Export / Import handlers
  const handleExportAllDecks = () => {
    const payload = exportAllDecks();
    triggerBackupDownload(payload);
    refreshData();
    showToast(`Exported ${payload.decks.length} deck${payload.decks.length === 1 ? '' : 's'}`);
  };

  const handleImportButtonClick = () => {
    importFileInputRef.current?.click();
  };

  const handleImportFileSelected = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    e.target.value = '';
    if (!file) return;

    const reader = new FileReader();
    reader.onload = () => {
      try {
        const parsed = JSON.parse(String(reader.result));
        const result = validateBackupPayload(parsed);
        if (!result.valid) {
          setImportError(result.error || 'This file could not be imported.');
          return;
        }
        setImportError(null);
        setPendingImport(parsed as BackupPayload);
      } catch {
        setImportError('This file is not valid JSON.');
      }
    };
    reader.onerror = () => setImportError('Could not read that file.');
    reader.readAsText(file);
  };

  const handleConfirmImport = (payload: BackupPayload, mode: 'merge' | 'replace') => {
    const summary = importBackupPayload(payload, mode);
    refreshData();
    setPendingImport(null);
    const parts = [`Imported ${summary.decksImported} deck${summary.decksImported === 1 ? '' : 's'}`];
    if (summary.decksSkipped > 0) {
      parts.push(`skipped ${summary.decksSkipped} already present`);
    }
    showToast(parts.join(', '));
  };

  const exportIsStale =
    savedDecks.length > 0 && (!lastExportAt || daysSince(lastExportAt) > EXPORT_STALE_DAYS);

  // Calculations for current level
  const currentFolder = currentFolderId ? folders.find(f => f.id === currentFolderId) : null;
  const breadcrumbs = getFolderPath(currentFolderId, folders);

  // Items at current level
  const subFolders = folders.filter(f => f.parentId === currentFolderId);
  const decksInCurrentFolder = savedDecks.filter(
    d => (d.folderId || null) === currentFolderId
  );

  // Total cards in current folder and all descendants
  const totalCardsInCurrentFolderTree = getAllCardsInFolderTree(currentFolderId).length;

  // Search filtering
  const isSearching = searchQuery.trim().length > 0;
  const filteredDecks = isSearching
    ? savedDecks.filter(d => d.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];
  const filteredFolders = isSearching
    ? folders.filter(f => f.name.toLowerCase().includes(searchQuery.toLowerCase()))
    : [];

  return (
    <div className="space-y-6">
      {/* Toast notification */}
      {toastMessage && (
        <div className="flex items-center justify-between p-3 px-4 rounded-xl bg-[var(--accent)] text-white text-xs font-semibold shadow-lg animate-in fade-in slide-in-from-top-2 duration-200">
          <div className="flex items-center gap-2">
            <CheckCircle2 size={16} />
            <span>{toastMessage.text}</span>
          </div>
          <button
            type="button"
            onClick={() => setToastMessage(null)}
            className="p-1 hover:opacity-80 cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Import error notification */}
      {importError && (
        <div className="flex items-center justify-between p-3 px-4 rounded-xl bg-red-500/10 border border-red-500/30 text-red-600 dark:text-red-400 text-xs font-semibold shadow-xs animate-in fade-in duration-150">
          <div className="flex items-center gap-2">
            <AlertTriangle size={15} />
            <span>{importError}</span>
          </div>
          <button
            type="button"
            onClick={() => setImportError(null)}
            className="p-1 hover:opacity-80 cursor-pointer"
          >
            <X size={14} />
          </button>
        </div>
      )}

      {/* Dragging visual indicator alert */}
      {draggedDeckSlug && (
        <div className="flex items-center justify-between p-2.5 px-4 rounded-xl bg-[var(--accent-bg)] border border-[var(--accent)]/40 text-[var(--accent-text)] text-xs font-semibold shadow-xs animate-in fade-in duration-150">
          <div className="flex items-center gap-2">
            <GripVertical size={15} className="animate-pulse text-[var(--accent)]" />
            <span>Dragging deck &mdash; drop directly onto any folder card or breadcrumb above to move it!</span>
          </div>
          <span className="text-[11px] text-[var(--text-muted)] font-normal hidden sm:inline">
            Release outside to cancel
          </span>
        </div>
      )}

      {/* Top Banner / Breadcrumb & Controls */}
      <div className="bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl p-5 sm:p-6 shadow-[var(--shadow-card)] space-y-4">
        {/* Breadcrumbs Navigation with Drop Targets */}
        <div className="flex items-center flex-wrap gap-1.5 text-xs font-medium text-[var(--text-secondary)] border-b border-[var(--border)]/60 pb-3.5">
          <button
            type="button"
            onClick={() => setCurrentFolderId(null)}
            onDragOver={e => handleDragOverTarget(e, null)}
            onDragLeave={e => handleDragLeaveTarget(e, null)}
            onDrop={e => handleDropOnTarget(e, null)}
            className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg transition-all cursor-pointer ${
              dragOverTargetId === 'ROOT'
                ? 'bg-[var(--accent)] text-white font-bold ring-2 ring-[var(--accent)] scale-105 shadow-sm'
                : draggedDeckSlug
                ? 'border border-dashed border-[var(--accent)]/50 text-[var(--text-primary)] hover:border-[var(--accent)]'
                : currentFolderId === null
                ? 'bg-[var(--surface-2)] text-[var(--text-primary)] font-bold'
                : 'hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)]'
            }`}
            title={draggedDeckSlug ? 'Drop here to move deck to Root level' : 'All Decks'}
          >
            <FolderTree size={13} className={dragOverTargetId === 'ROOT' ? 'text-white' : 'text-[var(--accent)]'} />
            <span>All Decks {dragOverTargetId === 'ROOT' && '(Drop here for Root)'}</span>
          </button>

          {breadcrumbs.map((crumb, idx) => {
            const isLast = idx === breadcrumbs.length - 1;
            const isDragOverCrumb = dragOverTargetId === crumb.id;
            return (
              <React.Fragment key={crumb.id}>
                <ChevronRight size={13} className="text-[var(--text-muted)] shrink-0" />
                <button
                  type="button"
                  onClick={() => setCurrentFolderId(crumb.id)}
                  onDragOver={e => handleDragOverTarget(e, crumb.id)}
                  onDragLeave={e => handleDragLeaveTarget(e, crumb.id)}
                  onDrop={e => handleDropOnTarget(e, crumb.id)}
                  className={`px-2.5 py-1 rounded-lg transition-all cursor-pointer truncate max-w-[150px] sm:max-w-xs ${
                    isDragOverCrumb
                      ? 'bg-[var(--accent)] text-white font-bold ring-2 ring-[var(--accent)] scale-105 shadow-sm'
                      : draggedDeckSlug
                      ? 'border border-dashed border-[var(--accent)]/50 text-[var(--text-primary)] hover:border-[var(--accent)]'
                      : isLast
                      ? 'bg-[var(--surface-2)] text-[var(--text-primary)] font-bold'
                      : 'hover:bg-[var(--surface-1)] hover:text-[var(--text-primary)]'
                  }`}
                  title={draggedDeckSlug ? `Drop here to move deck into "${crumb.name}"` : crumb.name}
                >
                  {crumb.name} {isDragOverCrumb && '(Drop here)'}
                </button>
              </React.Fragment>
            );
          })}
        </div>

        {/* Current Folder Info & Primary Actions */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
          <div>
            <div className="flex items-center gap-2 flex-wrap">
              <div className="flex items-center gap-2">
                {currentFolder ? (
                  <FolderOpen size={20} className="text-[var(--accent)] shrink-0" />
                ) : (
                  <Layers size={20} className="text-[var(--accent)] shrink-0" />
                )}
                <h2 className="text-xl font-bold tracking-tight text-[var(--text-primary)]">
                  {currentFolder ? currentFolder.name : 'Deck Library'}
                </h2>
              </div>

              {/* Status Badges */}
              <div className="flex items-center gap-1.5 text-xs text-[var(--text-secondary)] font-medium">
                {subFolders.length > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-[var(--surface-1)] border border-[var(--border)]">
                    {subFolders.length} {subFolders.length === 1 ? 'sub-folder' : 'sub-folders'}
                  </span>
                )}
                <span className="px-2 py-0.5 rounded-full bg-[var(--surface-1)] border border-[var(--border)]">
                  {decksInCurrentFolder.length} {decksInCurrentFolder.length === 1 ? 'deck' : 'decks'}
                </span>
                {totalCardsInCurrentFolderTree > 0 && (
                  <span className="px-2 py-0.5 rounded-full bg-[var(--accent-bg)] text-[var(--accent-text)] border border-[var(--accent)]/30 font-semibold">
                    {totalCardsInCurrentFolderTree} cards total
                  </span>
                )}
              </div>
            </div>

            <p className="text-xs text-[var(--text-secondary)] mt-1">
              {currentFolder
                ? `Organize nested sub-decks, drag decks into folders, or practice all cards in "${currentFolder.name}".`
                : 'Manage your decks, drag and drop into folders, and nest sub-decks to any depth.'}
            </p>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-2 flex-wrap shrink-0">
            {/* Practice Folder Button (if cards exist in this tree) */}
            {totalCardsInCurrentFolderTree > 0 && (
              <button
                type="button"
                onClick={handlePracticeCurrentFolder}
                className="flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] hover:border-[var(--accent)] shadow-xs transition-all cursor-pointer active:scale-[0.98]"
                title="Practice all cards in this folder and its sub-decks"
              >
                <Play size={14} fill="currentColor" className="text-[var(--accent)]" />
                <span>Practice Folder</span>
              </button>
            )}

            {/* Add Existing Deck into Folder Button (when inside a folder) */}
            {currentFolder && (
              <button
                type="button"
                onClick={openAddExistingModal}
                className="flex items-center justify-center gap-1.5 px-3.5 py-2 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] hover:border-[var(--accent)]/50 shadow-xs transition-all cursor-pointer active:scale-[0.98]"
                title={`Add pre-existing decks into "${currentFolder.name}"`}
              >
                <FolderInput size={15} className="text-[var(--accent)]" />
                <span>Add Existing Deck</span>
              </button>
            )}

            {/* New Folder Button */}
            <button
              type="button"
              onClick={openCreateFolderModal}
              className="flex items-center justify-center gap-1.5 px-3 py-2 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] hover:border-[var(--accent)]/50 shadow-xs transition-all cursor-pointer active:scale-[0.98]"
              title={currentFolder ? 'Create a sub-folder here' : 'Create a new top-level folder'}
            >
              <FolderPlus size={15} className="text-[var(--accent)]" />
              <span>{currentFolder ? 'New Sub-folder' : 'New Folder'}</span>
            </button>

            {/* New Deck Button */}
            <button
              type="button"
              onClick={() => onCreateNewDeck(currentFolderId)}
              className="flex items-center justify-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] text-white font-semibold text-xs shadow-md hover:opacity-95 active:scale-[0.98] transition-all cursor-pointer"
            >
              <Plus size={15} strokeWidth={2.5} />
              <span>{currentFolder ? 'Add Deck Here' : 'Create Deck'}</span>
            </button>
          </div>
        </div>

        {/* Storage & Backup Bar */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pt-3.5 border-t border-[var(--border)]/70 text-xs">
          <div className="flex items-center gap-2 flex-wrap text-[var(--text-secondary)]">
            <span
              className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-semibold ${
                storagePersistStatus === 'protected'
                  ? 'bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border-emerald-500/25'
                  : storagePersistStatus === 'not-protected'
                  ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/25'
                  : 'bg-[var(--surface-1)] text-[var(--text-muted)] border-[var(--border)]'
              }`}
              title={
                storagePersistStatus === 'protected'
                  ? "The browser granted persistent storage -- your decks are protected from automatic eviction under storage pressure."
                  : storagePersistStatus === 'not-protected'
                  ? 'The browser did not grant persistent storage. Decks could be evicted under storage pressure -- export a backup periodically.'
                  : storagePersistStatus === 'checking'
                  ? 'Checking storage persistence...'
                  : "This browser doesn't support the Storage API -- persistence status is unknown."
              }
            >
              {storagePersistStatus === 'protected' ? (
                <ShieldCheck size={13} />
              ) : storagePersistStatus === 'not-protected' ? (
                <ShieldAlert size={13} />
              ) : (
                <ShieldQuestion size={13} />
              )}
              <span>
                Storage:{' '}
                {storagePersistStatus === 'protected'
                  ? 'protected'
                  : storagePersistStatus === 'not-protected'
                  ? 'not protected'
                  : storagePersistStatus === 'checking'
                  ? 'checking…'
                  : 'unsupported'}
              </span>
            </span>

            {savedDecks.length > 0 && (
              <span
                className={`flex items-center gap-1.5 px-2.5 py-1 rounded-lg border font-medium ${
                  exportIsStale
                    ? 'bg-amber-500/10 text-amber-600 dark:text-amber-400 border-amber-500/25'
                    : 'bg-[var(--surface-1)] text-[var(--text-muted)] border-[var(--border)]'
                }`}
              >
                {exportIsStale && <AlertTriangle size={13} />}
                <span>
                  {lastExportAt
                    ? `Last backup: ${new Date(lastExportAt).toLocaleDateString()}${
                        exportIsStale ? ` (${Math.floor(daysSince(lastExportAt))}d ago — back up soon)` : ''
                      }`
                    : "You haven't exported a backup yet"}
                </span>
              </span>
            )}
          </div>

          <div className="flex items-center gap-2 shrink-0">
            <button
              type="button"
              onClick={handleExportAllDecks}
              disabled={savedDecks.length === 0}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] hover:border-[var(--accent)]/50 shadow-xs transition-all cursor-pointer active:scale-[0.98] disabled:opacity-40 disabled:cursor-not-allowed"
              title="Download a JSON backup of every deck and folder"
            >
              <Download size={14} className="text-[var(--accent)]" />
              <span>Export all decks</span>
            </button>
            <button
              type="button"
              onClick={handleImportButtonClick}
              className="flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] hover:border-[var(--accent)]/50 shadow-xs transition-all cursor-pointer active:scale-[0.98]"
              title="Restore decks from a previously exported backup file"
            >
              <Upload size={14} className="text-[var(--accent)]" />
              <span>Import decks</span>
            </button>
            <input
              ref={importFileInputRef}
              type="file"
              accept=".json,application/json"
              onChange={handleImportFileSelected}
              className="hidden"
            />
          </div>
        </div>
      </div>

      {/* Global Search */}
      {(savedDecks.length > 0 || folders.length > 0) && (
        <div className="relative">
          <Search
            size={16}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]"
          />
          <input
            type="text"
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
            placeholder="Search decks or folders across entire library..."
            className="w-full bg-[var(--surface-card)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl pl-10 pr-4 py-2.5 text-sm font-medium focus:border-[var(--accent)] focus:bg-[var(--surface-1)] outline-none transition-all placeholder:text-[var(--text-muted)] shadow-xs"
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => setSearchQuery('')}
              className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] px-1.5 py-0.5 cursor-pointer"
            >
              Clear
            </button>
          )}
        </div>
      )}

      {/* SEARCH RESULTS VIEW */}
      {isSearching ? (
        <div className="space-y-6">
          <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
            <span className="font-semibold">
              Search results for &ldquo;{searchQuery}&rdquo;
            </span>
            <span>
              {filteredFolders.length} folders, {filteredDecks.length} decks found
            </span>
          </div>

          {/* Matched Folders */}
          {filteredFolders.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                Matching Folders
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                {filteredFolders.map(f => {
                  const pathStr = getFolderFullPath(f.id, folders);
                  const cardsCount = getAllCardsInFolderTree(f.id).length;
                  return (
                    <div
                      key={f.id}
                      onClick={() => {
                        setCurrentFolderId(f.id);
                        setSearchQuery('');
                      }}
                      className="p-3.5 bg-[var(--surface-card)] hover:bg-[var(--surface-1)] border border-[var(--border)] hover:border-[var(--accent)] rounded-xl transition-all cursor-pointer flex items-center justify-between group"
                    >
                      <div className="flex items-center gap-2.5 min-w-0">
                        <Folder size={18} className="text-[var(--accent)] shrink-0" />
                        <div className="min-w-0">
                          <h4 className="text-sm font-bold text-[var(--text-primary)] group-hover:text-[var(--accent)] truncate">
                            {f.name}
                          </h4>
                          <p className="text-[11px] text-[var(--text-muted)] truncate">
                            {pathStr}
                          </p>
                        </div>
                      </div>
                      <span className="text-[11px] font-medium text-[var(--text-muted)] bg-[var(--surface-1)] px-2 py-0.5 rounded-md border border-[var(--border)] shrink-0 ml-2">
                        {cardsCount} cards
                      </span>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Matched Decks */}
          {filteredDecks.length > 0 && (
            <div className="space-y-2">
              <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-muted)]">
                Matching Decks
              </h3>
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {filteredDecks.map(deck => {
                  const pathStr = getFolderFullPath(deck.folderId || null, folders);
                  const isBeingDragged = draggedDeckSlug === deck.slug;
                  return (
                    <div
                      key={deck.slug}
                      draggable={true}
                      onDragStart={e => handleDragStartDeck(e, deck.slug)}
                      onDragEnd={handleDragEndDeck}
                      onClick={() => handleOpenDeck(deck.slug, deck.name, deck.folderId)}
                      className={`group relative bg-[var(--surface-card)] hover:bg-[var(--surface-1)] border rounded-2xl p-4 shadow-[var(--shadow-card)] transition-all cursor-pointer flex flex-col justify-between ${
                        isBeingDragged
                          ? 'opacity-40 ring-2 ring-[var(--accent)] cursor-grabbing'
                          : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                      }`}
                    >
                      <div>
                        <div className="flex items-start justify-between gap-2 mb-1.5">
                          <div className="flex items-center gap-1.5 min-w-0">
                            <div
                              className="p-1 -ml-1 text-[var(--text-muted)] hover:text-[var(--accent)] cursor-grab active:cursor-grabbing rounded-md hover:bg-[var(--surface-2)] transition-colors shrink-0"
                              title="Drag deck into a folder or breadcrumb"
                              onMouseDown={e => e.stopPropagation()}
                            >
                              <GripVertical size={15} />
                            </div>
                            <h4 className="text-sm font-bold text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors leading-snug line-clamp-1">
                              {deck.name}
                            </h4>
                          </div>
                          <span className="text-[11px] font-medium text-[var(--text-muted)] shrink-0">
                            {deck.count} cards
                          </span>
                        </div>
                        <div className="flex items-center gap-1.5 truncate mb-3">
                          <button
                            type="button"
                            onClick={e => openMoveModal(e, 'deck', deck.slug, deck.name)}
                            className="text-[11px] text-[var(--text-secondary)] hover:text-[var(--accent)] flex items-center gap-1 truncate px-2 py-0.5 rounded-md bg-[var(--surface-1)] border border-[var(--border)] cursor-pointer"
                            title="Add or move this deck to a folder"
                          >
                            <Folder size={12} className="text-[var(--accent)] shrink-0" />
                            <span className="truncate">{pathStr}</span>
                          </button>
                        </div>
                      </div>

                      <div className="pt-2.5 border-t border-[var(--border)]/60 flex items-center justify-between text-xs">
                        <div className="flex items-center gap-3">
                          <span className="text-[var(--text-muted)] group-hover:text-[var(--text-primary)] transition-colors flex items-center gap-1 font-medium">
                            <Edit3 size={13} /> Edit cards
                          </span>
                          <button
                            type="button"
                            onClick={e => openMoveModal(e, 'deck', deck.slug, deck.name)}
                            className="text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors flex items-center gap-1 font-medium cursor-pointer"
                            title="Choose folder for this deck"
                          >
                            <FolderInput size={13} />
                            <span>{deck.folderId ? 'Move' : 'Add to folder'}</span>
                          </button>
                        </div>
                        <button
                          type="button"
                          onClick={e => handleQuickStart(e, deck.slug, deck.name)}
                          className="flex items-center gap-1 px-3 py-1 rounded-lg bg-[var(--surface-2)] hover:bg-[var(--accent)] text-[var(--text-primary)] hover:text-white transition-all font-semibold cursor-pointer border border-[var(--border)] hover:border-transparent active:scale-[0.97]"
                        >
                          <Play size={12} fill="currentColor" /> Practice
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {filteredFolders.length === 0 && filteredDecks.length === 0 && (
            <div className="text-center py-10 bg-[var(--surface-card)] rounded-2xl border border-[var(--border)]">
              <p className="text-sm text-[var(--text-secondary)]">
                No decks or folders matched &ldquo;{searchQuery}&rdquo;.
              </p>
              <button
                type="button"
                onClick={() => setSearchQuery('')}
                className="mt-2 text-xs font-semibold text-[var(--accent)] hover:underline cursor-pointer"
              >
                Clear search
              </button>
            </div>
          )}
        </div>
      ) : (
        /* HIERARCHICAL FOLDERS & DECKS VIEW */
        <div className="space-y-7">
          {/* Sub-Folders Section */}
          {subFolders.length > 0 && (
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)] flex items-center gap-1.5">
                  <Folder size={14} className="text-[var(--accent)]" />
                  <span>{currentFolder ? 'Sub-Folders' : 'Folders'} ({subFolders.length})</span>
                </h3>
              </div>

              <div className="grid grid-cols-1 sm:grid-cols-2 gap-3.5">
                {subFolders.map(folder => {
                  const childFoldersCount = folders.filter(f => f.parentId === folder.id).length;
                  const childDecksCount = savedDecks.filter(d => d.folderId === folder.id).length;
                  const totalCards = getAllCardsInFolderTree(folder.id).length;
                  const isConfirming = confirmDeleteFolderId === folder.id;
                  const isDragOverFolder = dragOverTargetId === folder.id;

                  return (
                    <div
                      key={folder.id}
                      onClick={() => setCurrentFolderId(folder.id)}
                      onDragOver={e => handleDragOverTarget(e, folder.id)}
                      onDragLeave={e => handleDragLeaveTarget(e, folder.id)}
                      onDrop={e => handleDropOnTarget(e, folder.id)}
                      className={`group relative bg-[var(--surface-card)] hover:bg-[var(--surface-1)] border rounded-2xl p-4 shadow-[var(--shadow-card)] transition-all cursor-pointer flex items-center justify-between ${
                        isDragOverFolder
                          ? 'border-[var(--accent)] ring-2 ring-[var(--accent)] bg-[var(--accent-bg)]/40 scale-[1.02] shadow-lg'
                          : draggedDeckSlug
                          ? 'border-dashed border-[var(--accent)]/50 bg-[var(--accent-bg)]/10 hover:border-[var(--accent)]'
                          : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                      }`}
                    >
                      <div className="flex items-center gap-3 min-w-0 pr-2">
                        <div className="w-10 h-10 rounded-xl bg-[var(--accent-bg)] text-[var(--accent)] border border-[var(--accent)]/20 flex items-center justify-center shrink-0 group-hover:scale-105 transition-transform">
                          <Folder size={20} />
                        </div>
                        <div className="min-w-0">
                          <div className="flex items-center gap-2">
                            <h4 className="text-sm font-bold text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors truncate">
                              {folder.name}
                            </h4>
                            {isDragOverFolder && (
                              <span className="text-[10px] font-bold text-[var(--accent)] bg-[var(--surface-card)] px-2 py-0.5 rounded-full border border-[var(--accent)]/40 animate-pulse flex items-center gap-1 shrink-0">
                                <FolderDown size={11} /> Drop here
                              </span>
                            )}
                          </div>
                          <p className="text-[11px] text-[var(--text-secondary)] flex items-center gap-1.5 mt-0.5">
                            {childFoldersCount > 0 && (
                              <span>{childFoldersCount} sub-folders • </span>
                            )}
                            <span>{childDecksCount} {childDecksCount === 1 ? 'deck' : 'decks'}</span>
                            {totalCards > 0 && (
                              <span className="text-[var(--text-muted)]">({totalCards} cards)</span>
                            )}
                          </p>
                        </div>
                      </div>

                      {/* Folder Actions */}
                      <div className="flex items-center gap-1 shrink-0" onClick={e => e.stopPropagation()}>
                        {isConfirming ? (
                          <div className="flex items-center gap-1 bg-[var(--danger-bg)] border border-[var(--danger)]/30 rounded-lg p-1 animate-subtle-bounce">
                            <button
                              type="button"
                              onClick={e => handleDeleteFolder(e, folder.id)}
                              className="text-[11px] font-bold text-[var(--danger)] px-2 py-0.5 hover:underline cursor-pointer"
                            >
                              Delete all
                            </button>
                            <button
                              type="button"
                              onClick={e => {
                                e.stopPropagation();
                                setConfirmDeleteFolderId(null);
                              }}
                              className="text-[11px] text-[var(--text-muted)] px-1 hover:text-[var(--text-primary)] cursor-pointer"
                            >
                              Cancel
                            </button>
                          </div>
                        ) : (
                          <>
                            <button
                              type="button"
                              onClick={e => openMoveModal(e, 'folder', folder.id, folder.name)}
                              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)] transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                              title="Move folder"
                            >
                              <Move size={14} />
                            </button>
                            <button
                              type="button"
                              onClick={e => openRenameFolderModal(e, folder)}
                              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)] transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                              title="Rename folder"
                            >
                              <Edit3 size={14} />
                            </button>
                            <button
                              type="button"
                              onClick={e => {
                                e.stopPropagation();
                                setConfirmDeleteFolderId(folder.id);
                              }}
                              className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)] transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                              title="Delete folder and contents"
                            >
                              <Trash2 size={14} />
                            </button>
                            <ArrowRight size={15} className="text-[var(--text-muted)] group-hover:text-[var(--accent)] transition-colors ml-1" />
                          </>
                        )}
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>
          )}

          {/* Decks in Current Level Section */}
          <div className="space-y-3">
            <div className="flex items-center justify-between">
              <h3 className="text-xs font-bold uppercase tracking-wider text-[var(--text-secondary)] flex items-center gap-1.5">
                <Layers size={14} className="text-[var(--accent)]" />
                <span>
                  {currentFolder ? `Decks in "${currentFolder.name}"` : 'Top-Level Decks'} (
                  {decksInCurrentFolder.length})
                </span>
              </h3>

              {currentFolder && (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={openAddExistingModal}
                    className="text-xs text-[var(--accent)] hover:underline flex items-center gap-1 font-semibold cursor-pointer"
                  >
                    <FolderInput size={13} /> Add existing deck
                  </button>
                  <span className="text-[var(--border)]">•</span>
                  <button
                    type="button"
                    onClick={e => openRenameFolderModal(e, currentFolder)}
                    className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    <Edit3 size={12} /> Rename folder
                  </button>
                  <span className="text-[var(--border)]">•</span>
                  <button
                    type="button"
                    onClick={e => openMoveModal(e, 'folder', currentFolder.id, currentFolder.name)}
                    className="text-xs text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    <Move size={12} /> Move folder
                  </button>
                  <span className="text-[var(--border)]">•</span>
                  <button
                    type="button"
                    onClick={() => setConfirmDeleteFolderId(currentFolder.id)}
                    className="text-xs text-[var(--danger)] hover:underline flex items-center gap-1 cursor-pointer"
                  >
                    <Trash2 size={12} /> Delete folder
                  </button>
                </div>
              )}
            </div>

            {decksInCurrentFolder.length > 0 ? (
              <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                {decksInCurrentFolder.map(deck => {
                  const session = getSessionState(deck.slug);
                  const mastered = session?.items?.filter(i => i.status === 'mastered').length || 0;
                  const hasActiveSession = session && session.items && session.items.length > 0;
                  const isConfirming = confirmDeleteSlug === deck.slug;
                  const isBeingDragged = draggedDeckSlug === deck.slug;

                  return (
                    <div
                      key={deck.slug}
                      draggable={true}
                      onDragStart={e => handleDragStartDeck(e, deck.slug)}
                      onDragEnd={handleDragEndDeck}
                      onClick={() => handleOpenDeck(deck.slug, deck.name, deck.folderId)}
                      className={`group relative bg-[var(--surface-card)] hover:bg-[var(--surface-1)] border rounded-2xl p-5 shadow-[var(--shadow-card)] transition-all cursor-pointer flex flex-col justify-between ${
                        isBeingDragged
                          ? 'opacity-40 ring-2 ring-[var(--accent)] cursor-grabbing'
                          : 'border-[var(--border)] hover:border-[var(--accent)]/50'
                      }`}
                    >
                      <div>
                        <div className="flex items-start justify-between gap-3 mb-2.5">
                          <div className="flex items-start gap-2.5 min-w-0">
                            <div
                              className="p-1 -ml-1 mt-1 text-[var(--text-muted)] hover:text-[var(--accent)] cursor-grab active:cursor-grabbing rounded-md hover:bg-[var(--surface-2)] transition-colors shrink-0"
                              title="Drag deck to drop into any folder or breadcrumb"
                              onMouseDown={e => e.stopPropagation()}
                            >
                              <GripVertical size={16} />
                            </div>
                            <div className="w-8 h-8 rounded-xl bg-[var(--surface-2)] group-hover:bg-[var(--accent-bg)] text-[var(--text-secondary)] group-hover:text-[var(--accent)] border border-[var(--border)] flex items-center justify-center transition-colors shrink-0">
                              <Layers size={16} />
                            </div>
                            <div className="min-w-0">
                              <h3 className="text-base font-bold text-[var(--text-primary)] group-hover:text-[var(--accent)] transition-colors leading-snug truncate">
                                {deck.name}
                              </h3>
                              <div className="flex items-center gap-2 mt-1 flex-wrap">
                                <span className="text-[11px] font-medium text-[var(--text-muted)]">
                                  {deck.count} {deck.count === 1 ? 'card' : 'cards'}
                                </span>
                                <span className="text-[var(--border)] text-[10px]">•</span>
                                {deck.folderId ? (
                                  <button
                                    type="button"
                                    onClick={e => openMoveModal(e, 'deck', deck.slug, deck.name)}
                                    className="inline-flex items-center gap-1 text-[11px] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--surface-2)] hover:bg-[var(--surface-1)] border border-[var(--border)] hover:border-[var(--accent)]/40 rounded-md px-2 py-0.5 transition-all cursor-pointer truncate max-w-[170px]"
                                    title="Folder: Click to change or move"
                                  >
                                    <Folder size={11} className="text-[var(--accent)] shrink-0" />
                                    <span className="truncate">{getFolderFullPath(deck.folderId, folders)}</span>
                                  </button>
                                ) : (
                                  <button
                                    type="button"
                                    onClick={e => openMoveModal(e, 'deck', deck.slug, deck.name)}
                                    className="inline-flex items-center gap-1 text-[11px] font-semibold text-[var(--accent)] hover:text-white bg-[var(--accent-bg)] hover:bg-[var(--accent)] border border-[var(--accent)]/30 rounded-md px-2 py-0.5 transition-all cursor-pointer shadow-2xs active:scale-[0.97]"
                                    title="Add this deck to a folder"
                                  >
                                    <FolderPlus size={11} />
                                    <span>Add to folder</span>
                                  </button>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* Deck Actions */}
                          <div className="flex items-center gap-1 shrink-0">
                            {isConfirming ? (
                              <div
                                onClick={e => e.stopPropagation()}
                                className="flex items-center gap-1 bg-[var(--danger-bg)] border border-[var(--danger)]/30 rounded-lg p-1 animate-subtle-bounce"
                              >
                                <button
                                  type="button"
                                  onClick={e => handleDeleteDeck(e, deck.slug)}
                                  className="text-[11px] font-bold text-[var(--danger)] px-2 py-0.5 hover:underline cursor-pointer"
                                >
                                  Confirm
                                </button>
                                <button
                                  type="button"
                                  onClick={e => {
                                    e.stopPropagation();
                                    setConfirmDeleteSlug(null);
                                  }}
                                  className="text-[11px] text-[var(--text-muted)] px-1 hover:text-[var(--text-primary)] cursor-pointer"
                                >
                                  Cancel
                                </button>
                              </div>
                            ) : (
                              <>
                                <button
                                  type="button"
                                  onClick={e => openMoveModal(e, 'deck', deck.slug, deck.name)}
                                  className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)] transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                                  title="Add or move deck to a folder"
                                >
                                  <Move size={14} />
                                </button>
                                <button
                                  type="button"
                                  onClick={e => {
                                    e.stopPropagation();
                                    setConfirmDeleteSlug(deck.slug);
                                  }}
                                  className="p-1.5 rounded-lg text-[var(--text-muted)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)] transition-colors cursor-pointer opacity-0 group-hover:opacity-100"
                                  title="Delete deck"
                                >
                                  <Trash2 size={15} />
                                </button>
                              </>
                            )}
                          </div>
                        </div>

                        {/* Practice Progress Bar / Info */}
                        {hasActiveSession && (
                          <div className="mt-3 pt-3 border-t border-[var(--border)]/70">
                            <div className="flex items-center justify-between text-[11px] text-[var(--text-secondary)] mb-1.5">
                              <span className="flex items-center gap-1 text-[var(--accent-text)] font-medium">
                                <CheckCircle2 size={12} /> {mastered} of {session.items.length} mastered
                              </span>
                              <span className="text-[var(--text-muted)]">
                                {Math.round((mastered / session.items.length) * 100)}%
                              </span>
                            </div>
                            <div className="h-1.5 w-full bg-[var(--surface-2)] rounded-full overflow-hidden">
                              <div
                                className="h-full bg-[var(--accent)] rounded-full transition-all"
                                style={{
                                  width: `${Math.round((mastered / session.items.length) * 100)}%`,
                                }}
                              />
                            </div>
                          </div>
                        )}
                      </div>

                      {/* Card Action Footer */}
                      <div className="mt-4 pt-3 border-t border-[var(--border)]/60 flex items-center justify-between text-xs">
                        <div className="flex items-center gap-3">
                          <span className="text-[var(--text-muted)] group-hover:text-[var(--text-primary)] transition-colors flex items-center gap-1 font-medium">
                            <Edit3 size={13} /> Edit cards
                          </span>
                          <button
                            type="button"
                            onClick={e => openMoveModal(e, 'deck', deck.slug, deck.name)}
                            className="text-[var(--text-muted)] hover:text-[var(--accent)] transition-colors flex items-center gap-1 font-medium cursor-pointer"
                            title="Add or move deck to a folder"
                          >
                            <FolderInput size={13} />
                            <span>{deck.folderId ? 'Move' : 'Add to folder'}</span>
                          </button>
                        </div>

                        <button
                          type="button"
                          onClick={e => handleQuickStart(e, deck.slug, deck.name)}
                          className="flex items-center gap-1 px-3 py-1 rounded-lg bg-[var(--surface-2)] hover:bg-[var(--accent)] text-[var(--text-primary)] hover:text-white transition-all font-semibold cursor-pointer border border-[var(--border)] hover:border-transparent active:scale-[0.97]"
                        >
                          <Play size={12} fill="currentColor" /> Practice
                        </button>
                      </div>
                    </div>
                  );
                })}
              </div>
            ) : (
              <div className="text-center py-10 px-4 bg-[var(--surface-card)] rounded-2xl border border-[var(--border)] space-y-3">
                <p className="text-xs text-[var(--text-secondary)] max-w-sm mx-auto">
                  {currentFolder
                    ? `No decks directly in "${currentFolder.name}" yet. Add an existing deck, create a new one, or nest a sub-folder.`
                    : 'No decks at root level yet.'}
                </p>
                <div className="flex items-center justify-center gap-2 pt-1 flex-wrap">
                  <button
                    type="button"
                    onClick={() => onCreateNewDeck(currentFolderId)}
                    className="inline-flex items-center gap-1.5 px-4 py-2 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] text-white font-semibold text-xs shadow-xs hover:opacity-95 active:scale-[0.98] transition-all cursor-pointer"
                  >
                    <Plus size={14} strokeWidth={2.5} /> Add deck here
                  </button>
                  {currentFolder && (
                    <button
                      type="button"
                      onClick={openAddExistingModal}
                      className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[var(--surface-1)] hover:bg-[var(--surface-2)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] hover:border-[var(--accent)] shadow-xs transition-all cursor-pointer"
                    >
                      <FolderInput size={14} className="text-[var(--accent)]" /> Add existing deck
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={openCreateFolderModal}
                    className="inline-flex items-center gap-1.5 px-3.5 py-2 rounded-xl bg-[var(--surface-1)] hover:bg-[var(--surface-2)] text-[var(--text-primary)] font-semibold text-xs border border-[var(--border)] shadow-xs transition-all cursor-pointer"
                  >
                    <FolderPlus size={14} className="text-[var(--accent)]" /> Add folder
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      )}

      {folderModal && (
        <FolderNameModal
          title={
            folderModal.mode === 'create'
              ? currentFolder
                ? `Create Sub-folder in "${currentFolder.name}"`
                : 'Create New Folder'
              : 'Rename Folder'
          }
          initialName={folderModal.mode === 'rename' ? folderModal.folder.name : ''}
          submitLabel={folderModal.mode === 'create' ? 'Create Folder' : 'Save Changes'}
          onSave={handleSaveFolderModal}
          onClose={() => setFolderModal(null)}
        />
      )}

      {movingItem && (
        <MoveModal
          item={movingItem}
          folders={folders}
          initialDestination={currentFolderId}
          onCreateFolder={handleCreateFolderInMoveModal}
          onConfirm={handleConfirmMove}
          onClose={() => setMovingItem(null)}
        />
      )}

      {showAddExistingModal && currentFolder && (
        <AddExistingDecksModal
          folder={currentFolder}
          decks={savedDecks}
          folders={folders}
          onAddOne={handleAddSingleExistingDeck}
          onAddMany={handleAddSelectedDecks}
          onClose={() => setShowAddExistingModal(false)}
        />
      )}

      {pendingImport && (
        <ImportBackupModal
          payload={pendingImport}
          onConfirm={mode => handleConfirmImport(pendingImport, mode)}
          onClose={() => setPendingImport(null)}
        />
      )}
    </div>
  );
};
