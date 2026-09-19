import React, { useState, useEffect, useMemo } from 'react';
import {
  DeckItem,
  SavedDeckEntry,
  SavedSessionState,
  DeckFolder,
} from '../types';
import {
  parseDeck,
  slugify,
  saveDeckToStorage,
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
} from '../utils/drillEngine';
import { CardEditor, CardRowItem } from './CardEditor';
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
  SlidersHorizontal,
  Clock,
  Folder,
  FolderPlus,
} from 'lucide-react';

interface SetupViewProps {
  onStartSession: (parsed: DeckItem[], name: string, reps: number, chunkDifficulty: number) => void;
  onResumeSession: (state: SavedSessionState) => void;
  onNavigateDecks: () => void;
  initialDeckName?: string;
  initialItems?: DeckItem[];
  initialRawText?: string;
  initialEncodeReps?: number;
  initialChunkDifficulty?: number;
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
  }));
}

function cardRowsToDeckItems(rows: CardRowItem[]): DeckItem[] {
  return rows
    .map(r => ({ front: r.front.trim(), back: r.back.trim() }))
    .filter(r => r.front.length > 0 && r.back.length > 0);
}

function cardRowsToRawText(rows: CardRowItem[]): string {
  return rows
    .filter(r => r.front.trim() || r.back.trim())
    .map(r => `${r.front.trim()}\t${r.back.trim()}`)
    .join('\n');
}

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

function getRepsDescription(reps: number): string {
  if (reps === 1) return '1 blind completion per chunk (quick practice & warmup)';
  if (reps === 2) return '2 consecutive blind completions before advancing';
  if (reps === 3) return 'Standard 3 consecutive blind completions (recommended for retention)';
  return `${reps} consecutive blind completions for rock-solid memory locks`;
}

function getDifficultyDescription(pct: number, avgWords: number): string {
  if (pct >= 100) {
    return 'Full card at once — no sub-chunks (maximum difficulty)';
  }
  const sampleWords = avgWords > 0 ? avgWords : 12;
  const chunkWords = Math.max(2, Math.round(sampleWords * (pct / 100)));
  return `~${chunkWords} of ${sampleWords} words at once per chunk (${pct}%)`;
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
      return initialItems.map(i => `${i.front}\t${i.back}`).join('\n');
    }
    if (initialRawText) return initialRawText;
    const recents = getRecentlyUsedDecks();
    if (recents.length > 0) {
      const topDeck = getDeckFromStorage(recents[0].slug);
      if (topDeck && topDeck.length > 0) {
        return topDeck.map(i => `${i.front}\t${i.back}`).join('\n');
      }
    }
    return '';
  });
  const [savedDecks, setSavedDecks] = useState<SavedDeckEntry[]>(() => {
    return loadDeckIndex().filter(d => !isPremadeDeck(d.slug, d.name));
  });
  const [selectedSlug, setSelectedSlug] = useState(() => {
    if (initialDeckName) return slugify(initialDeckName);
    const recents = getRecentlyUsedDecks();
    if (recents.length > 0) return recents[0].slug;
    return '';
  });
  const [encodeReps, setEncodeReps] = useState<number>(() => {
    if (initialEncodeReps !== undefined) return initialEncodeReps;
    try {
      const saved = localStorage.getItem('recall_drill_encode_reps');
      if (saved) return parseInt(saved, 10);
    } catch {
      // ignore
    }
    return 3;
  });
  const [chunkDifficulty, setChunkDifficulty] = useState<number>(() => {
    if (initialChunkDifficulty !== undefined) return initialChunkDifficulty;
    try {
      const saved = localStorage.getItem('recall_drill_chunk_difficulty');
      if (saved) return parseInt(saved, 10);
    } catch {
      // ignore
    }
    return 35;
  });
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
    try {
      localStorage.setItem('recall_drill_encode_reps', String(clamped));
    } catch {
      // ignore
    }
  };

  const handleChunkDifficultyChange = (val: number) => {
    const clamped = Math.max(20, Math.min(100, val));
    setChunkDifficulty(clamped);
    try {
      localStorage.setItem('recall_drill_chunk_difficulty', String(clamped));
    } catch {
      // ignore
    }
  };

  const avgWordsPerCard = useMemo(() => {
    const currentItems =
      editMode === 'cards' ? cardRowsToDeckItems(cards) : parseDeck(rawText);
    if (!currentItems.length) return 12;
    const totalWords = currentItems.reduce(
      (acc, it) => acc + it.back.trim().split(/\s+/).filter(Boolean).length,
      0
    );
    return Math.max(4, Math.round(totalWords / currentItems.length));
  }, [cards, rawText, editMode]);

  // Sync if parent passes updated initialItems, initialDeckName, or initialIsEditingCards
  useEffect(() => {
    if (initialDeckName) {
      setDeckName(initialDeckName);
      setSelectedSlug(slugify(initialDeckName));
    }
    if (initialItems && initialItems.length > 0) {
      setCards(itemsToCardRows(initialItems));
      setRawText(initialItems.map(i => `${i.front}\t${i.back}`).join('\n'));
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
    const idx = loadDeckIndex().filter(d => !isPremadeDeck(d.slug, d.name));
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
    }
    const parsed = getDeckFromStorage(slug);
    if (parsed && parsed.length > 0) {
      setCards(itemsToCardRows(parsed));
      setRawText(parsed.map(p => `${p.front}\t${p.back}`).join('\n'));
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
      setCards(itemsToCardRows(parsed));
      setRawText(parsed.map(p => `${p.front}\t${p.back}`).join('\n'));
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
    const ok = saveDeckToStorage(name, currentItems, selectedFolderId);
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
      onStartSession(currentItems, name, reps, chunkDifficulty);
    }
  };

  const handleResume = () => {
    if (resumePrompt) {
      onResumeSession(resumePrompt.state);
    }
  };

  const handleStartFresh = () => {
    if (resumePrompt) {
      const slug = slugify(resumePrompt.name);
      clearSessionState(slug);
      onStartSession(resumePrompt.parsed, resumePrompt.name, encodeReps, chunkDifficulty);
    }
  };

  const validCardsCount =
    editMode === 'cards' ? cardRowsToDeckItems(cards).length : parseDeck(rawText).length;

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

        {/* View Mode Switcher: Cards View vs Bulk Import */}
        <div className="flex items-center justify-between border-t border-[var(--border)] pt-3 text-xs">
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

        {/* Reps Setting - Sliding Scale */}
        <div className="flex flex-col gap-2.5 border-t border-[var(--border)] pt-3.5">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-2">
            <label htmlFor="encode-reps-slider" className="text-xs text-[var(--text-secondary)] flex items-center gap-2">
              <span className="w-2 h-2 rounded-full bg-[var(--warning)]" />
              <span>Blind typings required to encode each chunk/card:</span>
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
                  Format: <code className="bg-[var(--surface-1)] border border-[var(--border)] px-1.5 py-0.5 rounded font-mono text-[var(--text-primary)]">front[TAB]back</code> or <code className="bg-[var(--surface-1)] border border-[var(--border)] px-1.5 py-0.5 rounded font-mono text-[var(--text-primary)]">front::back</code>
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

