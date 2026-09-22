import React, { useState, useEffect } from 'react';
import {
  DeckItem,
  DrillItem,
  LadderMode,
  CycleOrder,
  SavedSessionState,
  SessionState,
  SessionStats,
  ViewState,
} from './types';
import {
  buildItems,
  normalizeItem,
  slugify,
  clearSessionState,
  saveSessionState,
  recordDeckUsed,
  resolveBatchConfig,
  resolveSourceDeckEditable,
  loadDeckIndex,
} from './utils/drillEngine';
import { requestPersistentStorage, PersistenceStatus } from './utils/backup';
import { Header } from './components/Header';
import { SetupView } from './components/SetupView';
import { DecksView } from './components/DecksView';
import { SessionView } from './components/SessionView';
import { DoneView } from './components/DoneView';
import { HelpModal } from './components/HelpModal';

export default function App() {
  const [view, setView] = useState<ViewState>('setup');
  const [theme, setTheme] = useState<'light' | 'dark' | 'system'>('system');
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [storagePersistStatus, setStoragePersistStatus] = useState<PersistenceStatus>('checking');

  // Active session and editor parameters
  const [deckName, setDeckName] = useState<string>('');
  const [editorDeckItems, setEditorDeckItems] = useState<DeckItem[] | undefined>(undefined);
  const [autoOpenEditor, setAutoOpenEditor] = useState<boolean>(false);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [sessionItems, setSessionItems] = useState<DrillItem[]>([]);
  const [sessionPhase, setSessionPhase] = useState<'encode' | 'cycle' | 'batch-done'>('encode');
  const [sessionQueue, setSessionQueue] = useState<number[]>([]);
  const [sessionStats, setSessionStats] = useState<SessionStats>({
    attempts: 0,
    misses: 0,
    nearMisses: 0,
    overrides: 0,
  });
  // C3: batchSize 0 means "whole deck as one batch" (see partitionIntoBatches);
  // sessionBatchIndex/sessionBatchStartStats seed SessionView's initial
  // SessionState the same way sessionPhase/sessionQueue/sessionStats do.
  const [batchSize, setBatchSize] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('recall_drill_batch_size');
      if (saved) return parseInt(saved, 10);
    } catch {
      // ignore
    }
    return 5;
  });
  const [sessionBatchIndex, setSessionBatchIndex] = useState<number>(0);
  const [sessionBatchStartStats, setSessionBatchStartStats] = useState<SessionStats>({
    attempts: 0,
    misses: 0,
    nearMisses: 0,
    overrides: 0,
  });
  const [encodeReps, setEncodeReps] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('recall_drill_encode_reps');
      if (saved) return parseInt(saved, 10);
    } catch {
      // ignore
    }
    return 3;
  });
  const [chunkDifficulty, setChunkDifficulty] = useState<number>(() => {
    try {
      const saved = localStorage.getItem('recall_drill_chunk_difficulty');
      if (saved) return parseInt(saved, 10);
    } catch {
      // ignore
    }
    return 35;
  });
  const [stemTolerance, setStemTolerance] = useState<boolean>(() => {
    try {
      const saved = localStorage.getItem('recall_drill_stem_tolerance');
      if (saved !== null) return saved === 'true';
    } catch {
      // ignore
    }
    return true;
  });
  const [ladderMode, setLadderMode] = useState<LadderMode>(() => {
    try {
      const saved = localStorage.getItem('recall_drill_ladder_mode');
      if (saved === 'cumulative' || saved === 'exhaustive') return saved;
    } catch {
      // ignore
    }
    return 'cumulative';
  });
  const [cycleOrder, setCycleOrder] = useState<CycleOrder>(() => {
    try {
      const saved = localStorage.getItem('recall_drill_cycle_order');
      if (saved === 'shuffled' || saved === 'inOrder') return saved;
    } catch {
      // ignore
    }
    return 'shuffled';
  });
  // Phase 2: per-deck setting, not a global "last used" default like the
  // settings above -- SetupView reads/writes it on the selected deck's
  // SavedDeckEntry instead of localStorage. This just holds whatever the
  // active session/editor was started or resumed with.
  const [strictPunctuation, setStrictPunctuation] = useState<boolean>(false);
  // Whether the active session maps onto one saved deck (named deckName)
  // that a mid-session card edit may be written back to. Folder practice
  // pools several decks, so it's false there.
  const [sourceDeckEditable, setSourceDeckEditable] = useState<boolean>(true);

  // Request persistent storage once on app load so the browser is less
  // likely to evict decks under storage pressure.
  useEffect(() => {
    requestPersistentStorage().then(setStoragePersistStatus);
  }, []);

  // Setup theme listener & class assignment
  useEffect(() => {
    const savedTheme = (localStorage.getItem('recall_drill_theme') as
      | 'light'
      | 'dark'
      | 'system') || 'system';
    setTheme(savedTheme);
  }, []);

  useEffect(() => {
    localStorage.setItem('recall_drill_theme', theme);
    const root = document.documentElement;

    const applyDark = (isDark: boolean) => {
      if (isDark) {
        root.classList.add('dark');
      } else {
        root.classList.remove('dark');
      }
    };

    if (theme === 'system') {
      const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)');
      applyDark(mediaQuery.matches);
      const listener = (e: MediaQueryListEvent) => applyDark(e.matches);
      mediaQuery.addEventListener('change', listener);
      return () => mediaQuery.removeEventListener('change', listener);
    } else {
      applyDark(theme === 'dark');
    }
  }, [theme]);

  const handleStartSession = (
    parsed: DeckItem[],
    name: string,
    reps: number,
    difficultyPct?: number,
    stemToleranceParam?: boolean,
    ladderModeParam?: LadderMode,
    batchSizeParam?: number,
    cycleOrderParam?: CycleOrder,
    strictPunctuationParam?: boolean,
    // Folder practice pools cards from several decks: session-only, and
    // never seeded into the deck editor.
    fromFolder: boolean = false
  ) => {
    const diff = difficultyPct !== undefined ? difficultyPct : chunkDifficulty;
    const mode = ladderModeParam !== undefined ? ladderModeParam : ladderMode;
    const size = batchSizeParam !== undefined ? batchSizeParam : batchSize;
    // Deck order within each batch (no shuffle): encoding starts at card 1.
    const items = buildItems(parsed, diff, mode, size, undefined, false);
    const slug = slugify(name);
    // A folder is not a deck: recordDeckUsed's "no existing entry" branch
    // would otherwise create a payload-less deck-index entry named after
    // the folder (see drillEngine.ts's deckHasPayload for the read-side of
    // this same bug, for entries that already exist from before this
    // guard).
    if (!fromFolder) recordDeckUsed(slug, name, parsed.length);
    setDeckName(name);
    // Back to Setup remounts SetupView showing deckName with its cards seeded
    // from editorDeckItems, so that must be the deck this session actually
    // ran -- not whatever was last opened from the library, which a Save in
    // the editor would then write back over the saved deck.
    if (!fromFolder) setEditorDeckItems(parsed);
    setSessionItems(items);
    setSessionPhase('encode');
    setSessionQueue([]);
    setSessionStats({ attempts: 0, misses: 0, nearMisses: 0, overrides: 0, startTime: Date.now() });
    setSessionBatchIndex(0);
    setSessionBatchStartStats({ attempts: 0, misses: 0, nearMisses: 0, overrides: 0 });
    setEncodeReps(reps);
    try {
      localStorage.setItem('recall_drill_encode_reps', String(reps));
    } catch {
      // ignore
    }
    if (difficultyPct !== undefined) {
      setChunkDifficulty(difficultyPct);
    }
    if (stemToleranceParam !== undefined) {
      setStemTolerance(stemToleranceParam);
    }
    if (ladderModeParam !== undefined) {
      setLadderMode(ladderModeParam);
    }
    if (batchSizeParam !== undefined) {
      setBatchSize(batchSizeParam);
      try {
        localStorage.setItem('recall_drill_batch_size', String(batchSizeParam));
      } catch {
        // ignore
      }
    }
    if (cycleOrderParam !== undefined) {
      setCycleOrder(cycleOrderParam);
      try {
        localStorage.setItem('recall_drill_cycle_order', cycleOrderParam);
      } catch {
        // ignore
      }
    }
    // Phase 2: an explicit param (SetupView's toggle) always wins; otherwise
    // fall back to the target deck's own saved setting (quick-start /
    // practice-folder entry points don't know it) rather than defaulting to
    // false outright.
    const strict =
      strictPunctuationParam !== undefined
        ? strictPunctuationParam
        : loadDeckIndex().find(d => d.slug === slug)?.strictPunctuation ?? false;
    setStrictPunctuation(strict);
    setSourceDeckEditable(!fromFolder);
    setView('session');
  };

  // editorItems: the deck editor's cards at the moment Resume was clicked,
  // re-seeded for the same stale-reseed reason as in handleStartSession.
  const handleResumeSession = (state: SavedSessionState, editorItems?: DeckItem[]) => {
    const mode = state.ladderMode ?? ladderMode;
    const items = state.items.map(it => normalizeItem(it, mode));
    const { batchIndex, batchSize: resolvedBatchSize } = resolveBatchConfig(state, items);
    setDeckName(state.deckName);
    if (editorItems?.length) setEditorDeckItems(editorItems);
    setSessionItems(items);
    setSessionPhase(state.phase);
    setSessionQueue(state.queue || []);
    setSessionStats(state.stats || { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 });
    setSessionBatchIndex(batchIndex);
    setSessionBatchStartStats(state.batchStartStats ?? state.stats ?? { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 });
    setBatchSize(resolvedBatchSize);
    setEncodeReps(state.encodeReps || 3);
    if (state.chunkDifficulty !== undefined) {
      setChunkDifficulty(state.chunkDifficulty);
    }
    if (state.stemTolerance !== undefined) {
      setStemTolerance(state.stemTolerance);
    }
    if (state.ladderMode !== undefined) {
      setLadderMode(state.ladderMode);
    }
    setCycleOrder(state.cycleOrder ?? 'shuffled');
    setStrictPunctuation(state.strictPunctuation ?? false);
    setSourceDeckEditable(resolveSourceDeckEditable(state));
    setView('session');
  };

  // Takes SessionView's full internal SessionState (not just items/stats) so
  // the save below persists the ACTUAL current phase/queue/batchIndex --
  // SessionView's own persistState effect already keeps localStorage current
  // on every change, but App-level sessionPhase/sessionQueue/etc. are only
  // ever seeded once at session start/resume and go stale the moment the
  // session moves on, so re-deriving this save from them (instead of from
  // `state`) would silently regress a fresh save back to session-start
  // values -- exactly the failure mode C3's "Save and stop restores the
  // same batch" acceptance criterion would catch.
  const handleFinishSession = (state: SessionState) => {
    setSessionItems(state.items);
    setSessionStats(state.stats);
    setSessionPhase(state.phase);
    setSessionQueue(state.queue);
    setSessionBatchIndex(state.batchIndex);
    setSessionBatchStartStats(state.batchStartStats);
    const mastered = state.items.filter(i => i.status === 'mastered').length;
    const slug = slugify(deckName);

    if (mastered >= state.items.length) {
      clearSessionState(slug);
    } else {
      saveSessionState(slug, {
        deckName,
        phase: state.phase,
        queue: state.queue,
        stats: state.stats,
        items: state.items,
        encodeReps,
        chunkDifficulty,
        stemTolerance,
        ladderMode,
        strictPunctuation: state.config.strictPunctuation,
        cycleOrder: state.config.cycleOrder,
        batchIndex: state.batchIndex,
        batchSize: state.config.batchSize,
        batchStartStats: state.batchStartStats,
        sourceDeckEditable,
        timestamp: Date.now(),
      });
    }

    setView('done');
  };

  // Regression B fix: a folder-practice session never seeds editorDeckItems
  // (fromFolder in handleStartSession), but deckName always gets set to the
  // folder's name -- unconditionally, since SessionView/DoneView need it for
  // display and session-storage keying regardless of session type. Left
  // alone, that pairing goes stale the moment SetupView remounts here:
  // its cards/rawText fall back to "most recently used real deck" (since
  // initialItems is empty), while its deck-name field is pre-filled with
  // the FOLDER's name via initialDeckName -- a real, unrelated deck's
  // cards, shown and save-able under the folder's name. Clicking Save deck
  // from there creates a genuine phantom deck with a REAL payload (unlike
  // 723ec28's payload-less phantom, deckHasPayload can't filter this one).
  // Resetting both together when the ending session had no single source
  // deck (sourceDeckEditable) keeps them in sync -- both fall back to the
  // same "most recently used real deck" default, so title and cards always
  // describe the same thing.
  const handleBackToSetup = () => {
    setAutoOpenEditor(false);
    if (!sourceDeckEditable) {
      setDeckName('');
      setEditorDeckItems(undefined);
    }
    setView('setup');
  };

  const handleOpenDecksScreen = () => {
    setView('decks');
  };

  const handleSelectDeckFromLibrary = (
    name: string,
    items: DeckItem[],
    startInEditMode: boolean = true,
    folderId?: string | null
  ) => {
    setDeckName(name);
    setEditorDeckItems(items);
    setAutoOpenEditor(startInEditMode);
    setActiveFolderId(folderId ?? null);
    setView('setup');
  };

  const handleQuickStartFromLibrary = (name: string, items: DeckItem[]) => {
    handleStartSession(items, name, encodeReps, chunkDifficulty);
  };

  const handleCreateNewDeckFromLibrary = (folderId?: string | null) => {
    setDeckName('Untitled deck');
    setEditorDeckItems([
      { front: '', back: '' },
      { front: '', back: '' },
    ]);
    setAutoOpenEditor(true);
    setActiveFolderId(folderId ?? null);
    setView('setup');
  };

  const handlePracticeFolder = (folderName: string, items: DeckItem[]) => {
    handleStartSession(
      items,
      folderName,
      encodeReps,
      chunkDifficulty,
      undefined,
      undefined,
      undefined,
      undefined,
      undefined,
      true
    );
  };

  // A mid-session edit was written back to the session's deck. After Back
  // to Setup, SetupView remounts showing deckName and seeding its cards from
  // editorDeckItems, so that has to be the updated deck -- otherwise the
  // editor would show the pre-edit cards and its next Save would undo the fix.
  const handleDeckCardEdited = (items: DeckItem[]) => {
    setEditorDeckItems(items);
  };

  const handleRestartFresh = () => {
    if (!sessionItems.length) {
      setView('setup');
      return;
    }
    const freshItems = buildItems(
      sessionItems.map(i => ({ front: i.front, back: i.back })),
      chunkDifficulty,
      ladderMode,
      batchSize,
      undefined,
      false
    );
    const slug = slugify(deckName);
    clearSessionState(slug);
    setSessionItems(freshItems);
    setSessionPhase('encode');
    setSessionQueue([]);
    setSessionStats({ attempts: 0, misses: 0, nearMisses: 0, overrides: 0, startTime: Date.now() });
    setSessionBatchIndex(0);
    setSessionBatchStartStats({ attempts: 0, misses: 0, nearMisses: 0, overrides: 0 });
    setView('session');
  };

  return (
    <div className="min-h-screen bg-[var(--bg-page)] text-[var(--text-primary)] transition-colors duration-200">
      <div className="max-w-3xl mx-auto px-4 sm:px-6 py-6 sm:py-8">
        <Header
          deckName={view !== 'setup' && view !== 'decks' ? deckName : undefined}
          theme={theme}
          activeView={view}
          onThemeChange={setTheme}
          onOpenHelp={() => setIsHelpOpen(true)}
          onNavigateDecks={handleOpenDecksScreen}
          onGoHome={view !== 'setup' ? handleBackToSetup : undefined}
        />

        <main>
          {view === 'decks' && (
            <DecksView
              onSelectDeck={handleSelectDeckFromLibrary}
              onQuickStartDeck={handleQuickStartFromLibrary}
              onCreateNewDeck={handleCreateNewDeckFromLibrary}
              onPracticeFolder={handlePracticeFolder}
              storagePersistStatus={storagePersistStatus}
            />
          )}

          {view === 'setup' && (
            <SetupView
              onStartSession={handleStartSession}
              onResumeSession={handleResumeSession}
              onNavigateDecks={handleOpenDecksScreen}
              initialDeckName={deckName}
              initialItems={editorDeckItems}
              initialEncodeReps={encodeReps}
              initialChunkDifficulty={chunkDifficulty}
              initialStemTolerance={stemTolerance}
              initialLadderMode={ladderMode}
              initialStrictPunctuation={strictPunctuation}
              initialCycleOrder={cycleOrder}
              initialBatchSize={batchSize}
              initialIsEditingCards={autoOpenEditor}
              initialFolderId={activeFolderId}
            />
          )}

          {view === 'session' && (
            <SessionView
              deckName={deckName}
              initialItems={sessionItems}
              initialPhase={sessionPhase}
              initialQueue={sessionQueue}
              initialStats={sessionStats}
              encodeReps={encodeReps}
              chunkDifficulty={chunkDifficulty}
              stemTolerance={stemTolerance}
              ladderMode={ladderMode}
              strictPunctuation={strictPunctuation}
              cycleOrder={cycleOrder}
              batchSize={batchSize}
              initialBatchIndex={sessionBatchIndex}
              initialBatchStartStats={sessionBatchStartStats}
              onFinishSession={handleFinishSession}
              sourceDeckEditable={sourceDeckEditable}
              onDeckCardEdited={handleDeckCardEdited}
            />
          )}

          {view === 'done' && (
            <DoneView
              deckName={deckName}
              items={sessionItems}
              stats={sessionStats}
              onBackToSetup={handleBackToSetup}
              onRestartFresh={handleRestartFresh}
            />
          )}
        </main>

        <HelpModal
          isOpen={isHelpOpen}
          onClose={() => setIsHelpOpen(false)}
        />
      </div>
    </div>
  );
}
