import React, { useState, useEffect, useMemo } from 'react';
import {
  DeckItem,
  LadderMode,
  CycleOrder,
  SavedDeckEntry,
  SavedSessionState,
  DeckFolder,
} from '../types';
import {
  parseDeck,
  slugify,
  saveDeckToStorage,
  deckHasPayload,
  deleteDeckFromStorage,
  loadDeckIndex,
  getDeckFromStorage,
  getSessionState,
  clearSessionState,
  getRecentlyUsedDecks,
  recordDeckUsed,
  isPremadeDeck,
  loadFolderIndex,
  createFolder,
  computeColdStartEstimate,
  getColdStartHistory,
  ExposureLevel,
} from '../utils/drillEngine';
import { readSetting, writeSetting } from '../utils/settings';
import { CardEditor, CardRowItem } from './CardEditor';
import { SessionSettings } from './setup/SessionSettings';
import { ColdStartEstimatePanel } from './setup/ColdStartEstimatePanel';
import {
  Play,
  Save,
  Trash2,
  RotateCcw,
  FileText,
  Layers,
  Edit3,
  ChevronDown,
  ChevronUp,
  Clock,
  Folder,
  FolderPlus,
} from 'lucide-react';

interface SetupViewProps {
  onStartSession: (
    parsed: DeckItem[],
    name: string,
    reps: number,
    chunkDifficulty: number,
    stemTolerance: boolean,
    ladderMode: LadderMode,
    batchSize: number,
    cycleOrder: CycleOrder,
    strictPunctuation: boolean
  ) => void;
  // editorItems: the editor's current cards, so App can re-seed the editor
  // from them after the session instead of from stale library data.
  onResumeSession: (state: SavedSessionState, editorItems?: DeckItem[]) => void;
  onNavigateDecks: () => void;
  initialDeckName?: string;
  initialItems?: DeckItem[];
  initialRawText?: string;
  initialEncodeReps?: number;
  initialChunkDifficulty?: number;
  initialStemTolerance?: boolean;
  initialLadderMode?: LadderMode;
  initialStrictPunctuation?: boolean;
  initialCycleOrder?: CycleOrder;
  // C3: 0 means "whole deck as one batch" (no interstitial checkpoint) --
  // see partitionIntoBatches.
  initialBatchSize?: number;
  initialIsEditingCards?: boolean;
  initialFolderId?: string | null;
}

function itemsToCardRows(items: DeckItem[]): CardRowItem[] {
  if (!items || items.length === 0) {
    return [
      { id: 'card_1', front: '', back: '' },
      { id: 'card_2', front: '', back: '' },
    ];
  }
  return items.map((it, idx) => ({
    id: `card_${idx}_${Math.random().toString(36).substring(2, 7)}`,
    front: it.front,
    back: it.back,
    extra: it.extra,
  }));
}

function cardRowsToDeckItems(rows: CardRowItem[]): DeckItem[] {
  return rows
    .map(r => {
      const extra = (r.extra || '').trim();
      const item: DeckItem = { front: r.front.trim(), back: r.back.trim() };
      return extra ? { ...item, extra } : item;
    })
    .filter(r => r.front.length > 0 && r.back.length > 0);
}

// Loaded-deck -> bulk-text serialization, shared by cardRowsToRawText (cards
// mode -> bulk) and every "load a saved deck straight into rawText" site
// below -- appends a third \t segment only when extra is present, so a
// no-extra deck's bulk text is unchanged.
function deckItemToRawLine(item: Pick<DeckItem, 'front' | 'back' | 'extra'>): string {
  return item.extra ? `${item.front}\t${item.back}\t${item.extra}` : `${item.front}\t${item.back}`;
}

function cardRowsToRawText(rows: CardRowItem[]): string {
  return rows
    .filter(r => r.front.trim() || r.back.trim())
    .map(r => deckItemToRawLine({ front: r.front.trim(), back: r.back.trim(), extra: (r.extra || '').trim() || undefined }))
    .join('\n');
}

export const SetupView: React.FC<SetupViewProps> = ({
  onStartSession,
  onResumeSession,
  onNavigateDecks,
  initialDeckName = '',
  initialItems,
  initialRawText = '',
  initialEncodeReps = 3,
  initialChunkDifficulty,
  initialStemTolerance,
  initialLadderMode,
  initialStrictPunctuation,
  initialCycleOrder,
  initialBatchSize,
  initialIsEditingCards = false,
  initialFolderId = null,
}) => {
  const [folders, setFolders] = useState<DeckFolder[]>(() => loadFolderIndex());
  const [selectedFolderId, setSelectedFolderId] = useState<string | null>(initialFolderId ?? null);
  const [showNewFolderInput, setShowNewFolderInput] = useState(false);
  const [newFolderName, setNewFolderName] = useState('');

  const [recentDecks, setRecentDecks] = useState<SavedDeckEntry[]>(() => {
    return getRecentlyUsedDecks();
  });
  const [deckName, setDeckName] = useState(() => {
    if (initialDeckName) return initialDeckName;
    const recents = getRecentlyUsedDecks();
    if (recents.length > 0) return recents[0].name;
    return '';
  });
  const [cards, setCards] = useState<CardRowItem[]>(() => {
    if (initialItems && initialItems.length > 0) {
      return itemsToCardRows(initialItems);
    }
    if (initialRawText) {
      const parsed = parseDeck(initialRawText);
      if (parsed.length > 0) return itemsToCardRows(parsed);
    }
    const recents = getRecentlyUsedDecks();
    if (recents.length > 0) {
      const topDeck = getDeckFromStorage(recents[0].slug);
      if (topDeck && topDeck.length > 0) {
        return itemsToCardRows(topDeck);
      }
    }
    return [
      { id: 'card_1', front: '', back: '' },
      { id: 'card_2', front: '', back: '' },
    ];
  });
  const [editMode, setEditMode] = useState<'cards' | 'bulk'>('cards');
  const [rawText, setRawText] = useState(() => {
    if (initialItems && initialItems.length > 0) {
      return initialItems.map(deckItemToRawLine).join('\n');
    }
    if (initialRawText) return initialRawText;
    const recents = getRecentlyUsedDecks();
    if (recents.length > 0) {
      const topDeck = getDeckFromStorage(recents[0].slug);
      if (topDeck && topDeck.length > 0) {
        return topDeck.map(deckItemToRawLine).join('\n');
      }
    }
    return '';
  });
  const [savedDecks, setSavedDecks] = useState<SavedDeckEntry[]>(() => {
    // deckHasPayload: see DecksView.refreshData's comment -- same phantom
    // entries, same filter, so a folder-practice ghost never shows up in
    // the "Quick switch..." picker either.
    return loadDeckIndex().filter(d => !isPremadeDeck(d.slug, d.name) && deckHasPayload(d));
  });
  const [selectedSlug, setSelectedSlug] = useState(() => {
    if (initialDeckName) return slugify(initialDeckName);
    const recents = getRecentlyUsedDecks();
    if (recents.length > 0) return recents[0].slug;
    return '';
  });
  const [encodeReps, setEncodeReps] = useState<number>(() => initialEncodeReps ?? readSetting('encodeReps'));
  const [chunkDifficulty, setChunkDifficulty] = useState<number>(() => initialChunkDifficulty ?? readSetting('chunkDifficulty'));
  const [stemTolerance, setStemTolerance] = useState<boolean>(() => initialStemTolerance ?? readSetting('stemTolerance'));
  const [ladderMode, setLadderMode] = useState<LadderMode>(() => initialLadderMode ?? readSetting('ladderMode'));
  // Phase 2: per-deck setting, not a global "last used" default like the
  // other settings above -- loaded from the selected deck's SavedDeckEntry
  // (see handleSelectDeck/handleSelectRecentDeck below), not localStorage.
  const [strictPunctuation, setStrictPunctuation] = useState<boolean>(
    () => initialStrictPunctuation ?? false
  );
  const [cycleOrder, setCycleOrder] = useState<CycleOrder>(() => initialCycleOrder ?? readSetting('cycleOrder'));
  // C3: 0 means "whole deck as one batch" (no interstitial checkpoint).
  const [batchSize, setBatchSize] = useState<number>(() => initialBatchSize ?? readSetting('batchSize'));
  // Cold-start estimate: no user-facing persistence of its own -- the picker
  // only matters when there's no personal history for this deck yet (see
  // personalHistory below), and defaults to the most conservative reading.
  const [exposureLevel, setExposureLevel] = useState<ExposureLevel>('fresh');
  const [msg, setMsg] = useState('');
  const [resumePrompt, setResumePrompt] = useState<{
    state: SavedSessionState;
    parsed: DeckItem[];
    name: string;
  } | null>(null);

  const [isEditingCards, setIsEditingCards] = useState(initialIsEditingCards);

  const handleEncodeRepsChange = (val: number) => {
    const clamped = Math.max(1, Math.min(10, val));
    setEncodeReps(clamped);
    writeSetting('encodeReps', clamped);
  };

  const handleChunkDifficultyChange = (val: number) => {
    const clamped = Math.max(20, Math.min(100, val));
    setChunkDifficulty(clamped);
    writeSetting('chunkDifficulty', clamped);
  };

  const handleStemToleranceChange = (val: boolean) => {
    setStemTolerance(val);
    writeSetting('stemTolerance', val);
  };

  const handleLadderModeChange = (val: LadderMode) => {
    setLadderMode(val);
    writeSetting('ladderMode', val);
  };

  const handleCycleOrderChange = (val: CycleOrder) => {
    setCycleOrder(val);
    writeSetting('cycleOrder', val);
  };

  const handleBatchSizeChange = (val: number) => {
    const clamped = val <= 0 ? 0 : Math.max(3, Math.min(10, val));
    setBatchSize(clamped);
    writeSetting('batchSize', clamped);
  };

  const currentDeckItems = useMemo(
    () => (editMode === 'cards' ? cardRowsToDeckItems(cards) : parseDeck(rawText)),
    [cards, rawText, editMode]
  );

  const avgWordsPerCard = useMemo(() => {
    if (!currentDeckItems.length) return 12;
    const totalWords = currentDeckItems.reduce(
      (acc, it) => acc + it.back.trim().split(/\s+/).filter(Boolean).length,
      0
    );
    return Math.max(4, Math.round(totalWords / currentDeckItems.length));
  }, [currentDeckItems]);

  // Personal history takes precedence over the exposure-picker seed (see
  // drillEngine.ts's cold-start precedence note) -- looked up by the slug
  // this deck would be saved/started under, whether or not it's saved yet.
  const historySlug = selectedSlug || slugify(deckName || 'untitled-deck');
  const personalHistory = useMemo(() => getColdStartHistory(historySlug), [historySlug]);

  const coldStartEstimate = useMemo(() => {
    if (!currentDeckItems.length) return null;
    return computeColdStartEstimate(
      currentDeckItems,
      encodeReps,
      chunkDifficulty,
      ladderMode,
      personalHistory ? personalHistory.multiplier : exposureLevel
    );
  }, [currentDeckItems, encodeReps, chunkDifficulty, ladderMode, personalHistory, exposureLevel]);

  // Sync if parent passes updated initialItems, initialDeckName, or initialIsEditingCards
  useEffect(() => {
    if (initialDeckName) {
      setDeckName(initialDeckName);
      setSelectedSlug(slugify(initialDeckName));
    }
    if (initialItems && initialItems.length > 0) {
      setCards(itemsToCardRows(initialItems));
      setRawText(initialItems.map(deckItemToRawLine).join('\n'));
    }
    if (initialIsEditingCards !== undefined) {
      setIsEditingCards(initialIsEditingCards);
    }
    if (initialEncodeReps !== undefined) {
      setEncodeReps(initialEncodeReps);
    }
    if (initialChunkDifficulty !== undefined) {
      setChunkDifficulty(initialChunkDifficulty);
    }
    if (initialFolderId !== undefined) {
      setSelectedFolderId(initialFolderId);
    }
  }, [initialDeckName, initialItems, initialIsEditingCards, initialChunkDifficulty, initialFolderId]);

  useEffect(() => {
    refreshDecks();
  }, []);

  const refreshDecks = () => {
    const recents = getRecentlyUsedDecks();
    setRecentDecks(recents);
    const idx = loadDeckIndex().filter(d => !isPremadeDeck(d.slug, d.name) && deckHasPayload(d));
    setSavedDecks(idx);
    setFolders(loadFolderIndex());
  };

  const handleQuickCreateFolder = () => {
    const trimmed = newFolderName.trim();
    if (!trimmed) return;
    const created = createFolder(trimmed, selectedFolderId || null);
    setFolders(loadFolderIndex());
    setSelectedFolderId(created.id);
    setNewFolderName('');
    setShowNewFolderInput(false);
    setMsg(`Created folder "${created.name}".`);
  };

  const buildFolderOptions = (
    parentId: string | null = null,
    depth: number = 0
  ): { id: string | null; label: string }[] => {
    const list: { id: string | null; label: string }[] = [];
    if (depth === 0) {
      list.push({ id: null, label: '📁 Root (No folder)' });
    }
    const children = folders.filter(f => f.parentId === parentId);
    for (const child of children) {
      const indent = '\u00A0\u00A0'.repeat(depth);
      list.push({ id: child.id, label: `${indent}📁 ${child.name}` });
      list.push(...buildFolderOptions(child.id, depth + 1));
    }
    return list;
  };

  // Sync cards state changes to rawText when in cards mode
  const handleCardsChange = (newCards: CardRowItem[]) => {
    setCards(newCards);
    setRawText(cardRowsToRawText(newCards));
  };

  // Switch between visual cards and bulk text
  const handleSwitchToBulk = () => {
    setRawText(cardRowsToRawText(cards));
    setEditMode('bulk');
  };

  const handleSwitchToCards = () => {
    const parsed = parseDeck(rawText);
    setCards(itemsToCardRows(parsed));
    setEditMode('cards');
  };

  const handleTabKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Tab') {
      e.preventDefault();
      const target = e.currentTarget;
      const start = target.selectionStart;
      const end = target.selectionEnd;
      const value = target.value;
      const nextValue = value.substring(0, start) + '\t' + value.substring(end);
      setRawText(nextValue);
      setTimeout(() => {
        target.selectionStart = target.selectionEnd = start + 1;
      }, 0);
    }
  };

  const handleSelectRecentDeck = (slug: string, name: string) => {
    setSelectedSlug(slug);
    setDeckName(name);
    const entry = savedDecks.find(d => d.slug === slug);
    if (entry) {
      setSelectedFolderId(entry.folderId || null);
      setStrictPunctuation(entry.strictPunctuation ?? false);
    }
    const parsed = getDeckFromStorage(slug);
    if (parsed && parsed.length > 0) {
      setCards(itemsToCardRows(parsed));
      setRawText(parsed.map(deckItemToRawLine).join('\n'));
      setMsg(`Loaded "${name}" with ${parsed.length} cards.`);
    } else {
      setCards([
        { id: 'card_1', front: '', back: '' },
        { id: 'card_2', front: '', back: '' },
      ]);
      setRawText('');
      setMsg(`Deck "${name}" is empty or not found.`);
    }
    recordDeckUsed(slug, name, parsed?.length || 0);
    refreshDecks();
    setResumePrompt(null);
  };

  const handleSelectDeck = (slug: string) => {
    setSelectedSlug(slug);
    if (!slug) return;
    const entry = savedDecks.find(d => d.slug === slug);
    const parsed = getDeckFromStorage(slug);
    if (parsed && entry) {
      setDeckName(entry.name);
      setSelectedFolderId(entry.folderId || null);
      setStrictPunctuation(entry.strictPunctuation ?? false);
      setCards(itemsToCardRows(parsed));
      setRawText(parsed.map(deckItemToRawLine).join('\n'));
      setMsg(`Loaded "${entry.name}" with ${parsed.length} cards.`);
      recordDeckUsed(slug, entry.name, parsed.length);
      refreshDecks();
      setResumePrompt(null);
    }
  };

  const handleSaveDeck = () => {
    const name = deckName.trim();
    if (!name) {
      setMsg('Please provide a deck title first.');
      return;
    }
    const currentItems =
      editMode === 'cards' ? cardRowsToDeckItems(cards) : parseDeck(rawText);

    if (!currentItems.length) {
      setMsg('No valid cards to save. Make sure each card has both term and definition.');
      return;
    }
    const ok = saveDeckToStorage(name, currentItems, selectedFolderId, strictPunctuation);
    if (ok) {
      refreshDecks();
      setSelectedSlug(slugify(name));
      setMsg(`Saved "${name}" with ${currentItems.length} cards.`);
    } else {
      setMsg('Unable to save deck. Check browser storage permissions.');
    }
  };

  const handleDeleteDeck = () => {
    const slug = selectedSlug || slugify(deckName.trim());
    if (!slug) {
      setMsg('Select or name a deck to delete.');
      return;
    }
    deleteDeckFromStorage(slug);
    refreshDecks();
    setSelectedSlug('');
    setResumePrompt(null);
    setMsg('Deck deleted.');
  };

  const handleStart = () => {
    const currentItems =
      editMode === 'cards' ? cardRowsToDeckItems(cards) : parseDeck(rawText);

    if (!currentItems.length) {
      setMsg('Please create or enter at least one card with front and back.');
      return;
    }
    const name = deckName.trim() || 'Untitled deck';
    const reps = Math.max(1, Math.min(10, encodeReps));
    const slug = slugify(name);
    recordDeckUsed(slug, name, currentItems.length);

    const existingState = getSessionState(slug);
    if (existingState && existingState.items && existingState.items.length > 0) {
      const mastered = existingState.items.filter(i => i.status === 'mastered').length;
      setResumePrompt({
        state: existingState,
        parsed: currentItems,
        name,
      });
      setMsg(`Found a previous session for "${name}" with ${mastered} of ${existingState.items.length} items mastered.`);
    } else {
      onStartSession(
        currentItems,
        name,
        reps,
        chunkDifficulty,
        stemTolerance,
        ladderMode,
        batchSize,
        cycleOrder,
        strictPunctuation
      );
    }
  };

  const handleResume = () => {
    if (resumePrompt) {
      onResumeSession(resumePrompt.state, resumePrompt.parsed);
    }
  };

  const handleStartFresh = () => {
    if (resumePrompt) {
      const slug = slugify(resumePrompt.name);
      clearSessionState(slug);
      onStartSession(
        resumePrompt.parsed,
        resumePrompt.name,
        encodeReps,
        chunkDifficulty,
        stemTolerance,
        ladderMode,
        batchSize,
        cycleOrder,
        strictPunctuation
      );
    }
  };

  const validCardsCount = currentDeckItems.length;

  return (
    <div className="space-y-6">
      {/* Most Recently Used Decks Bar */}
      <div className="flex items-center gap-2 overflow-x-auto pb-1 text-xs no-scrollbar">
        <span className="text-[var(--text-secondary)] font-medium shrink-0 flex items-center gap-1.5 pl-0.5">
          <Clock size={13} className="text-[var(--accent)]" /> Recent decks:
        </span>
        {recentDecks.length > 0 ? (
          recentDecks.map(deck => (
            <button
              key={deck.slug}
              type="button"
              onClick={() => handleSelectRecentDeck(deck.slug, deck.name)}
              className={`px-3 py-1.5 rounded-lg transition-all border shrink-0 font-medium cursor-pointer shadow-xs active:scale-[0.98] flex items-center gap-1.5 ${
                selectedSlug === deck.slug
                  ? 'bg-[var(--accent-bg)] text-[var(--accent)] border-[var(--accent)]/40 font-semibold'
                  : 'bg-[var(--surface-1)] hover:bg-[var(--surface-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:border-[var(--accent)]/30 border-[var(--border)]'
              }`}
            >
              <span>{deck.name}</span>
              <span className="text-[10px] opacity-70 px-1.5 py-0.2 rounded-full bg-[var(--surface-2)] border border-[var(--border)]">
                {deck.count}
              </span>
            </button>
          ))
        ) : (
          <span className="text-[var(--text-muted)] text-xs italic pl-1">
            No recent decks yet. Build or import your deck below.
          </span>
        )}
      </div>

      {/* Top Deck Info Bar */}
      <div className="bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl p-5 sm:p-6 shadow-[var(--shadow-card)] space-y-4 transition-colors">
        <div className="flex flex-col sm:flex-row gap-3">
          <input
            id="deck-name"
            value={deckName}
            onChange={e => setDeckName(e.target.value)}
            placeholder="Deck title (e.g. Spanish Vocabulary, AWS Solutions, History)"
            className="flex-1 bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-4 py-2.5 text-sm font-semibold focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none transition-all placeholder:text-[var(--text-muted)]"
          />
          <div className="flex items-center gap-2">
            <select
              id="saved-decks"
              value={selectedSlug}
              onChange={e => handleSelectDeck(e.target.value)}
              className="w-full sm:w-48 bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-3.5 py-2.5 text-sm font-medium focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none transition-all cursor-pointer"
            >
              <option value="">Quick switch...</option>
              {savedDecks.map(d => (
                <option key={d.slug} value={d.slug}>
                  {d.name} ({d.count})
                </option>
              ))}
            </select>

            <button
              type="button"
              onClick={onNavigateDecks}
              className="px-3 py-2.5 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] text-xs font-semibold cursor-pointer shadow-xs whitespace-nowrap transition-all"
              title="Browse all saved decks in full screen gallery"
            >
              All Decks →
            </button>
          </div>
        </div>

        {/* Folder / Sub-deck Organization Selector */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2.5 pt-2 text-xs border-t border-[var(--border)]/70">
          <div className="flex items-center gap-2 flex-wrap">
            <span className="text-[var(--text-secondary)] font-semibold flex items-center gap-1.5">
              <Folder size={14} className="text-[var(--accent)]" /> Folder / Hierarchy:
            </span>
            <select
              value={selectedFolderId || ''}
              onChange={e => setSelectedFolderId(e.target.value ? e.target.value : null)}
              className="bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-lg px-2.5 py-1.5 text-xs font-medium focus:border-[var(--accent)] outline-none transition-all cursor-pointer max-w-xs"
            >
              {buildFolderOptions().map(opt => (
                <option key={opt.id || 'root'} value={opt.id || ''}>
                  {opt.label}
                </option>
              ))}
            </select>
            {!showNewFolderInput ? (
              <button
                type="button"
                onClick={() => setShowNewFolderInput(true)}
                className="flex items-center gap-1 text-[var(--accent)] hover:underline font-semibold cursor-pointer px-1 py-0.5 text-xs"
              >
                <FolderPlus size={13} /> + New folder
              </button>
            ) : (
              <div className="flex items-center gap-1.5">
                <input
                  type="text"
                  value={newFolderName}
                  onChange={e => setNewFolderName(e.target.value)}
                  onKeyDown={e => {
                    if (e.key === 'Enter') handleQuickCreateFolder();
                    if (e.key === 'Escape') setShowNewFolderInput(false);
                  }}
                  placeholder="New folder name..."
                  className="bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-lg px-2.5 py-1 text-xs outline-none focus:border-[var(--accent)] w-36"
                />
                <button
                  type="button"
                  onClick={handleQuickCreateFolder}
                  disabled={!newFolderName.trim()}
                  className="px-2.5 py-1 rounded-lg bg-[var(--accent)] text-white text-[11px] font-semibold hover:bg-[var(--accent-hover)] disabled:opacity-50 cursor-pointer"
                >
                  Create
                </button>
                <button
                  type="button"
                  onClick={() => setShowNewFolderInput(false)}
                  className="text-xs text-[var(--text-muted)] hover:text-[var(--text-primary)] px-1 cursor-pointer"
                >
                  ✕
                </button>
              </div>
            )}
          </div>
        </div>

        <SessionSettings
          encodeReps={encodeReps}
          onEncodeRepsChange={handleEncodeRepsChange}
          chunkDifficulty={chunkDifficulty}
          onChunkDifficultyChange={handleChunkDifficultyChange}
          avgWordsPerCard={avgWordsPerCard}
          stemTolerance={stemTolerance}
          onStemToleranceChange={handleStemToleranceChange}
          strictPunctuation={strictPunctuation}
          onStrictPunctuationChange={setStrictPunctuation}
          ladderMode={ladderMode}
          onLadderModeChange={handleLadderModeChange}
          batchSize={batchSize}
          onBatchSizeChange={handleBatchSizeChange}
          cycleOrder={cycleOrder}
          onCycleOrderChange={handleCycleOrderChange}
        />

        <ColdStartEstimatePanel
          estimate={coldStartEstimate}
          hasPersonalHistory={!!personalHistory}
          exposureLevel={exposureLevel}
          onExposureLevelChange={setExposureLevel}
        />

        {/* View Mode Switcher: Cards View vs Bulk Import */}
        <div className="flex flex-wrap items-center justify-between gap-2 border-t border-[var(--border)] pt-3.5 text-xs">
          <div className="flex items-center gap-1.5 bg-[var(--surface-1)] p-1 rounded-xl border border-[var(--border)]">
            <button
              type="button"
              onClick={handleSwitchToCards}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
                editMode === 'cards'
                  ? 'bg-[var(--surface-2)] text-[var(--accent)] shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <Layers size={14} /> Individual Cards
            </button>
            <button
              type="button"
              onClick={handleSwitchToBulk}
              className={`flex items-center gap-1.5 px-3 py-1.5 rounded-lg font-semibold transition-all cursor-pointer ${
                editMode === 'bulk'
                  ? 'bg-[var(--surface-2)] text-[var(--accent)] shadow-xs'
                  : 'text-[var(--text-secondary)] hover:text-[var(--text-primary)]'
              }`}
            >
              <FileText size={14} /> Bulk Text / Import
            </button>
          </div>

          <span className="font-semibold text-[var(--accent)] bg-[var(--accent-bg)] px-3 py-1 rounded-full border border-[var(--accent)]/20">
            {validCardsCount} valid {validCardsCount === 1 ? 'card' : 'cards'}
          </span>
        </div>

        {/* Primary Action Buttons (Top Placement) */}
        <div className="flex flex-wrap items-center justify-between gap-3 pt-3 border-t border-[var(--border)]">
          <div className="flex flex-wrap items-center gap-2.5">
            <button
              type="button"
              id="start-btn"
              onClick={handleStart}
              className="flex items-center gap-2 px-6 py-2.5 rounded-xl bg-gradient-to-r from-[var(--accent)] to-[var(--accent-hover)] hover:opacity-95 active:scale-[0.98] text-white font-semibold text-sm shadow-md transition-all cursor-pointer"
            >
              <Play size={16} fill="currentColor" /> Start session
            </button>

            <button
              type="button"
              id="save-btn"
              onClick={handleSaveDeck}
              className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[var(--surface-1)] hover:bg-[var(--surface-2)] active:scale-[0.98] text-[var(--text-primary)] font-medium text-sm border border-[var(--border)] transition-all cursor-pointer shadow-xs"
            >
              <Save size={16} /> Save deck
            </button>

            <button
              type="button"
              id="delete-btn"
              onClick={handleDeleteDeck}
              className="flex items-center gap-1.5 px-4 py-2.5 rounded-xl bg-[var(--surface-1)] hover:bg-[var(--danger-bg)] hover:text-[var(--danger)] hover:border-[var(--danger)] active:scale-[0.98] text-[var(--text-secondary)] font-medium text-sm border border-[var(--border)] transition-all cursor-pointer shadow-xs"
            >
              <Trash2 size={16} /> Delete
            </button>
          </div>

          <button
            type="button"
            id="toggle-edit-deck-btn"
            onClick={() => setIsEditingCards(!isEditingCards)}
            className={`flex items-center gap-1.5 px-4 py-2.5 rounded-xl font-semibold text-xs sm:text-sm border transition-all cursor-pointer shadow-xs active:scale-[0.98] ${
              isEditingCards
                ? 'bg-[var(--accent)] text-white border-[var(--accent)] shadow-sm'
                : 'bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border-[var(--border)]'
            }`}
          >
            <Edit3 size={15} />
            <span>{isEditingCards ? 'Hide card editor' : 'Edit deck cards'}</span>
            {isEditingCards ? <ChevronUp size={15} /> : <ChevronDown size={15} />}
          </button>
        </div>

        {/* Setup Status / Guidance Notice (Top Placement) */}
        {msg && (
          <div
            id="setup-msg"
            className="text-xs font-medium text-[var(--text-primary)] bg-[var(--surface-1)] border border-[var(--border)] px-3.5 py-2.5 rounded-xl shadow-xs animate-subtle-bounce"
          >
            {msg}
          </div>
        )}

        {/* Resume Session Banner */}
        {resumePrompt && (
          <div
            id="resume-prompt"
            className="p-4 sm:p-5 rounded-2xl border border-[var(--accent)]/30 bg-[var(--accent-bg)] shadow-[var(--shadow-md)] transition-all"
          >
            <div className="flex items-start gap-3.5">
              <div className="w-8 h-8 rounded-xl bg-[var(--accent)] text-white flex items-center justify-center shrink-0 mt-0.5 shadow-xs">
                <RotateCcw size={16} />
              </div>
              <div className="space-y-3 flex-1">
                <div>
                  <h4 className="text-sm font-semibold text-[var(--text-primary)]">
                    Resume active session for &ldquo;{resumePrompt.name}&rdquo;?
                  </h4>
                  <p id="resume-msg" className="text-xs text-[var(--text-secondary)] mt-0.5">
                    You already mastered{' '}
                    <span className="font-semibold text-[var(--accent-text)]">
                      {resumePrompt.state.items.filter(i => i.status === 'mastered').length}
                    </span>{' '}
                    of {resumePrompt.state.items.length} cards. Would you like to pick up where you left off or start fresh?
                  </p>
                </div>
                <div className="flex items-center gap-2.5">
                  <button
                    type="button"
                    id="resume-btn"
                    onClick={handleResume}
                    className="px-4 py-2 rounded-xl bg-[var(--accent)] hover:bg-[var(--accent-hover)] text-white font-semibold text-xs shadow-xs cursor-pointer active:scale-[0.98] transition-all"
                  >
                    Resume session
                  </button>
                  <button
                    type="button"
                    id="fresh-btn"
                    onClick={handleStartFresh}
                    className="px-3.5 py-2 rounded-xl bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] font-medium text-xs cursor-pointer active:scale-[0.98] transition-all"
                  >
                    Start fresh
                  </button>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>

      {/* Editor Body: Only shown when "Edit deck cards" is toggled on */}
      {isEditingCards && (
        <div className="animate-fade-in space-y-4">
          {editMode === 'cards' ? (
            <CardEditor cards={cards} onChange={handleCardsChange} />
          ) : (
            <div className="bg-[var(--surface-card)] border border-[var(--border)] rounded-2xl p-5 shadow-[var(--shadow-card)] space-y-3">
              <div className="flex items-center justify-between text-xs text-[var(--text-secondary)]">
                <span>
                  Format: <code className="bg-[var(--surface-1)] border border-[var(--border)] px-1.5 py-0.5 rounded font-mono text-[var(--text-primary)]">front[TAB]back</code> or <code className="bg-[var(--surface-1)] border border-[var(--border)] px-1.5 py-0.5 rounded font-mono text-[var(--text-primary)]">front::back</code>, plus an optional <code className="bg-[var(--surface-1)] border border-[var(--border)] px-1.5 py-0.5 rounded font-mono text-[var(--text-primary)]">[TAB]extra</code> or <code className="bg-[var(--surface-1)] border border-[var(--border)] px-1.5 py-0.5 rounded font-mono text-[var(--text-primary)]">::extra</code>
                </span>
                <button
                  type="button"
                  onClick={handleSwitchToCards}
                  className="text-[var(--accent)] hover:underline font-medium cursor-pointer"
                >
                  Parse into cards →
                </button>
              </div>

              <div className="relative">
                <textarea
                  id="deck-input"
                  rows={10}
                  value={rawText}
                  onChange={e => setRawText(e.target.value)}
                  onKeyDown={handleTabKeyDown}
                  placeholder="front&#9;back&#10;Capital of France&#9;Paris&#10;git status&#9;Show the working tree status"
                  className="w-full mono text-sm bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl p-4 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none transition-all resize-y leading-relaxed"
                />
                <div className="absolute right-3.5 bottom-3.5 text-[11px] text-[var(--text-muted)] pointer-events-none bg-[var(--surface-2)]/90 backdrop-blur-xs px-2 py-0.5 rounded-md border border-[var(--border)] shadow-xs">
                  Tab key inserts \t
                </div>
              </div>
            </div>
          )}
        </div>
      )}
    </div>
  );
};

