import React from 'react';
import { Sparkles, Moon, Sun, Monitor, HelpCircle, Layers, FolderHeart } from 'lucide-react';
import { ViewState } from '../types';

interface HeaderProps {
  deckName?: string;
  theme: 'light' | 'dark' | 'system';
  activeView: ViewState;
  onThemeChange: (t: 'light' | 'dark' | 'system') => void;
  onOpenHelp: () => void;
  onNavigateDecks: () => void;
  onGoHome?: () => void;
}

export const Header: React.FC<HeaderProps> = ({
  deckName,
  theme,
  activeView,
  onThemeChange,
  onOpenHelp,
  onNavigateDecks,
  onGoHome,
}) => {
  const nextTheme = theme === 'system' ? 'light' : theme === 'light' ? 'dark' : 'system';

  return (
    <header className="flex items-center justify-between py-4 border-b border-[var(--border)] mb-7 transition-colors">
      <div
        className={`flex items-center gap-3.5 ${onGoHome ? 'cursor-pointer select-none group' : ''}`}
        onClick={onGoHome}
      >
        <div className="w-9 h-9 rounded-xl bg-gradient-to-br from-[var(--accent)] to-[var(--accent-hover)] text-white flex items-center justify-center font-bold text-sm shadow-sm ring-1 ring-black/5 group-hover:scale-105 transition-transform duration-150">
          <Layers size={18} strokeWidth={2.5} />
        </div>
        <div>
          <div className="flex items-center gap-2">
            <h1 className="text-base font-bold tracking-tight text-[var(--text-primary)]">
              Recall Drill
            </h1>
            {deckName && (
              <span className="text-[11px] font-medium px-2.5 py-0.5 rounded-full bg-[var(--surface-1)] text-[var(--text-secondary)] border border-[var(--border)] tracking-tight truncate max-w-[170px] sm:max-w-xs">
                {deckName}
              </span>
            )}
          </div>
          <p className="text-[11.5px] text-[var(--text-secondary)] font-normal tracking-tight">
            Chunking &amp; spaced retrieval practice
          </p>
        </div>
      </div>

      <div className="flex items-center gap-2">
        {/* Decks Navigation Tab */}
        <button
          type="button"
          onClick={onNavigateDecks}
          className={`px-3 py-1.5 rounded-xl font-semibold text-xs flex items-center gap-1.5 transition-all border cursor-pointer shadow-xs ${
            activeView === 'decks'
              ? 'bg-[var(--accent)] text-white border-[var(--accent)]'
              : 'bg-[var(--surface-2)] hover:bg-[var(--surface-1)] text-[var(--text-primary)] border-[var(--border)]'
          }`}
          title="Browse saved decks library"
        >
          <FolderHeart size={14} />
          <span className="hidden sm:inline">Saved Decks</span>
          <span className="sm:hidden">Decks</span>
        </button>

        <button
          type="button"
          onClick={onOpenHelp}
          className="p-2 rounded-xl text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-1)] transition-all border border-transparent hover:border-[var(--border)] cursor-pointer"
          title="Keyboard shortcuts & syntax guide"
          aria-label="Help"
        >
          <HelpCircle size={17} />
        </button>

        <button
          type="button"
          onClick={() => onThemeChange(nextTheme)}
          className="px-2.5 py-1.5 rounded-xl text-[var(--text-secondary)] hover:text-[var(--text-primary)] bg-[var(--surface-2)] hover:bg-[var(--surface-1)] transition-all border border-[var(--border)] flex items-center gap-1.5 text-xs font-medium cursor-pointer shadow-xs"
          title={`Theme: ${theme}. Click to switch.`}
          aria-label="Toggle theme"
        >
          {theme === 'dark' ? (
            <Moon size={14} className="text-[var(--accent-text)]" />
          ) : theme === 'light' ? (
            <Sun size={14} className="text-amber-500" />
          ) : (
            <Monitor size={14} />
          )}
          <span className="capitalize hidden sm:inline text-[11.5px]">{theme}</span>
        </button>
      </div>
    </header>
  );
};

