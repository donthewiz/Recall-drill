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
  SESSION_COMPLETE_ID,
  emptyStats,
  appendSessionHistory,
  buildHistoryEntry,
} from './utils/drillEngine';
import { readSetting, writeSetting, ThemeSetting } from './utils/settings';
import { requestPersistentStorage, PersistenceStatus } from './utils/backup';
import { Header } from './components/Header';
import { SetupView } from './components/SetupView';
import { DecksView } from './components/DecksView';
import { SessionView } from './components/SessionView';
import { DoneView } from './components/DoneView';
import { HelpModal } from './components/HelpModal';

export default function App() {
  const [view, setView] = useState<ViewState>('setup');
  const [theme, setTheme] = useState<ThemeSetting>(() => readSetting('theme'));
  const [isHelpOpen, setIsHelpOpen] = useState(false);
  const [storagePersistStatus, setStoragePersistStatus] = useState<PersistenceStatus>('checking');

  // Active session and editor parameters
  const [deckName, setDeckName] = useState<string>('');
  const [editorDeckItems, setEditorDeckItems] = useState<DeckItem[] | undefined>(undefined);
  const [autoOpenEditor, setAutoOpenEditor] = useState<boolean>(false);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [sessionItems, setSessionItems] = useState<DrillItem[]>([]);
  const [sessionPhase, setSessionPhase] = useState<'encode' | 'cycle' | 'batch-done' | 'final'>('encode');
  const [sessionQueue, setSessionQueue] = useState<number[]>([]);
  const [sessionStats, setSessionStats] = useState<SessionStats>(emptyStats);
  // C3: batchSize 0 means "whole deck as one batch" (see partitionIntoBatches);
  // sessionBatchIndex/sessionBatchStartStats seed SessionView's initial
  // SessionState the same way sessionPhase/sessionQueue/sessionStats do.
  const [batchSize, setBatchSize] = useState<number>(() => readSetting('batchSize'));
  const [sessionBatchIndex, setSessionBatchIndex] = useState<number>(0);
  const [sessionBatchStartStats, setSessionBatchStartStats] = useState<SessionStats>(emptyStats);
  // Phase 3: seeds SessionView's initial SessionState the same way, for
  // computeCumulativeColdStartMultiplier's numerator during the Final check
  // (see its doc comment in drillEngine.ts).
  const [sessionFinalCheckStartAttempts, setSessionFinalCheckStartAttempts] = useState<number | undefined>(
    undefined
  );
  // Resume position: seeds SessionView's currentId so a resumed encode phase
  // stays on the card that was on screen (see SavedSessionState.currentId).
  const [sessionCurrentId, setSessionCurrentId] = useState<number | undefined>(undefined);
  const [encodeReps, setEncodeReps] = useState<number>(() => readSetting('encodeReps'));
  const [chunkDifficulty, setChunkDifficulty] = useState<number>(() => readSetting('chunkDifficulty'));
  const [stemTolerance, setStemTolerance] = useState<boolean>(() => readSetting('stemTolerance'));
  const [ladderMode, setLadderMode] = useState<LadderMode>(() => readSetting('ladderMode'));
  const [cycleOrder, setCycleOrder] = useState<CycleOrder>(() => readSetting('cycleOrder'));
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

  // Theme class assignment (and the system-theme listener)
  useEffect(() => {
    writeSetting('theme', theme);
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
    setSessionStats({ ...emptyStats(), startTime: Date.now() });
    setSessionBatchIndex(0);
    setSessionBatchStartStats(emptyStats());
    setSessionFinalCheckStartAttempts(undefined);
    setSessionCurrentId(undefined);
    setEncodeReps(reps);
    writeSetting('encodeReps', reps);
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
      writeSetting('batchSize', batchSizeParam);
    }
    if (cycleOrderParam !== undefined) {
      setCycleOrder(cycleOrderParam);
      writeSetting('cycleOrder', cycleOrderParam);
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
    // Spread over emptyStats so a save from before a stats field existed
    // (e.g. reveals) resumes with it at 0.
    setSessionStats({ ...emptyStats(), ...state.stats });
    setSessionBatchIndex(batchIndex);
    setSessionBatchStartStats({ ...emptyStats(), ...(state.batchStartStats ?? state.stats) });
    setSessionFinalCheckStartAttempts(state.finalCheckStartAttempts);
    setSessionCurrentId(state.currentId);
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
    setSessionFinalCheckStartAttempts(state.finalCheckStartAttempts);
    setSessionCurrentId(state.currentId);
    const slug = slugify(deckName);

    // Phase 3: "complete" means the Final check has finished too, not just
    // every item reaching 'mastered' -- the last batch's cycle mastering
    // every item no longer ends the session (see advanceBatchState), so
    // clearing on `mastered >= items.length` would wipe a save mid-Final-
    // check, losing finalDone progress and stranding the resume prompt.
    if (state.currentId === SESSION_COMPLETE_ID) {
      clearSessionState(slug);
      // Only for a real deck: folder practice and "Drill these again" have
      // no deck-index entry, so their history would be unreachable (and
      // left out of backups).
      if (sourceDeckEditable) appendSessionHistory(slug, buildHistoryEntry(state));
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
        finalCheckStartAttempts: state.finalCheckStartAttempts,
        currentId: state.currentId,
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

  // DoneView's "Drill these again": a fresh session over just the cards
  // missed in the Final check. Run like folder practice (session-only, no
  // deck write-back) under its own name, so it never touches the source
  // deck's saved session or cards.
  const handleDrillAgain = (cards: DeckItem[]) => {
    if (!cards.length) return;
    const baseName = deckName.replace(/ \(missed cards\)$/, '');
    handleStartSession(
      cards,
      `${baseName} (missed cards)`,
      encodeReps,
      chunkDifficulty,
      undefined,
      undefined,
      undefined,
      undefined,
      strictPunctuation,
      true
    );
  };

  const handleRestartFresh = () => {
    if (!sessionItems.length) {
      setView('setup');
      return;
    }
    const freshItems = buildItems(
      sessionItems.map(i => ({ front: i.front, back: i.back, extra: i.extra })),
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
    setSessionStats({ ...emptyStats(), startTime: Date.now() });
    setSessionBatchIndex(0);
    setSessionBatchStartStats(emptyStats());
    setSessionFinalCheckStartAttempts(undefined);
    setSessionCurrentId(undefined);
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
              initialFinalCheckStartAttempts={sessionFinalCheckStartAttempts}
              initialCurrentId={sessionCurrentId}
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
              onDrillAgain={handleDrillAgain}
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
