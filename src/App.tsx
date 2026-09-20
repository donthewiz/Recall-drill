import React, { useState, useEffect } from 'react';
import {
  DeckItem,
  DrillItem,
  SavedSessionState,
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
} from './utils/drillEngine';
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

  // Active session and editor parameters
  const [deckName, setDeckName] = useState<string>('');
  const [editorDeckItems, setEditorDeckItems] = useState<DeckItem[] | undefined>(undefined);
  const [autoOpenEditor, setAutoOpenEditor] = useState<boolean>(false);
  const [activeFolderId, setActiveFolderId] = useState<string | null>(null);
  const [sessionItems, setSessionItems] = useState<DrillItem[]>([]);
  const [sessionPhase, setSessionPhase] = useState<'encode' | 'cycle'>('encode');
  const [sessionQueue, setSessionQueue] = useState<number[]>([]);
  const [sessionStats, setSessionStats] = useState<SessionStats>({
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
    stemToleranceParam?: boolean
  ) => {
    const diff = difficultyPct !== undefined ? difficultyPct : chunkDifficulty;
    const items = buildItems(parsed, diff);
    const slug = slugify(name);
    recordDeckUsed(slug, name, parsed.length);
    setDeckName(name);
    setSessionItems(items);
    setSessionPhase('encode');
    setSessionQueue([]);
    setSessionStats({ attempts: 0, misses: 0, nearMisses: 0, overrides: 0, startTime: Date.now() });
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
    setView('session');
  };

  const handleResumeSession = (state: SavedSessionState) => {
    setDeckName(state.deckName);
    setSessionItems(state.items.map(normalizeItem));
    setSessionPhase(state.phase);
    setSessionQueue(state.queue || []);
    setSessionStats(state.stats || { attempts: 0, misses: 0, nearMisses: 0, overrides: 0 });
    setEncodeReps(state.encodeReps || 3);
    if (state.chunkDifficulty !== undefined) {
      setChunkDifficulty(state.chunkDifficulty);
    }
    if (state.stemTolerance !== undefined) {
      setStemTolerance(state.stemTolerance);
    }
    setView('session');
  };

  const handleFinishSession = (items: DrillItem[], stats: SessionStats) => {
    setSessionItems(items);
    setSessionStats(stats);
    const mastered = items.filter(i => i.status === 'mastered').length;
    const slug = slugify(deckName);

    if (mastered >= items.length) {
      clearSessionState(slug);
    } else {
      saveSessionState(slug, {
        deckName,
        phase: sessionPhase,
        queue: sessionQueue,
        stats,
        items,
        encodeReps,
        chunkDifficulty,
        stemTolerance,
        timestamp: Date.now(),
      });
    }

    setView('done');
  };

  const handleBackToSetup = () => {
    setAutoOpenEditor(false);
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
    handleStartSession(items, folderName, encodeReps, chunkDifficulty);
  };

  const handleRestartFresh = () => {
    if (!sessionItems.length) {
      setView('setup');
      return;
    }
    const freshItems = buildItems(
      sessionItems.map(i => ({ front: i.front, back: i.back })),
      chunkDifficulty
    );
    const slug = slugify(deckName);
    clearSessionState(slug);
    setSessionItems(freshItems);
    setSessionPhase('encode');
    setSessionQueue([]);
    setSessionStats({ attempts: 0, misses: 0, nearMisses: 0, overrides: 0, startTime: Date.now() });
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
              onFinishSession={handleFinishSession}
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
