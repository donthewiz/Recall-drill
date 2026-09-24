import React, { useState } from 'react';
import { Trash2, GripVertical, Plus, Copy, ArrowUpDown } from 'lucide-react';

export interface CardRowItem {
  id: string;
  front: string;
  back: string;
  extra?: string;
}

interface CardEditorProps {
  cards: CardRowItem[];
  onChange: (cards: CardRowItem[]) => void;
}

export const CardEditor: React.FC<CardEditorProps> = ({ cards, onChange }) => {
  const [focusedIndex, setFocusedIndex] = useState<number | null>(null);

  const handleUpdateCard = (id: string, field: 'front' | 'back' | 'extra', value: string) => {
    const updated = cards.map(card => {
      if (card.id === id) {
        return { ...card, [field]: value };
      }
      return card;
    });
    onChange(updated);
  };

  const handleAddCard = (afterIndex?: number) => {
    const newCard: CardRowItem = {
      id: 'card_' + Math.random().toString(36).substring(2, 9) + Date.now().toString(36),
      front: '',
      back: '',
      extra: '',
    };
    if (typeof afterIndex === 'number' && afterIndex >= 0 && afterIndex < cards.length) {
      const copy = [...cards];
      copy.splice(afterIndex + 1, 0, newCard);
      onChange(copy);
      setFocusedIndex(afterIndex + 1);
    } else {
      onChange([...cards, newCard]);
      setFocusedIndex(cards.length);
    }
  };

  const handleDeleteCard = (id: string) => {
    if (cards.length <= 1) {
      // Don't leave with 0 cards, just clear it
      onChange([{ id: cards[0].id, front: '', back: '', extra: '' }]);
      return;
    }
    const updated = cards.filter(card => card.id !== id);
    onChange(updated);
  };

  const handleDuplicateCard = (index: number) => {
    const item = cards[index];
    if (!item) return;
    const duplicated: CardRowItem = {
      id: 'card_' + Math.random().toString(36).substring(2, 9),
      front: item.front,
      back: item.back,
      extra: item.extra,
    };
    const copy = [...cards];
    copy.splice(index + 1, 0, duplicated);
    onChange(copy);
  };

  const handleMoveCard = (index: number, direction: 'up' | 'down') => {
    const targetIndex = direction === 'up' ? index - 1 : index + 1;
    if (targetIndex < 0 || targetIndex >= cards.length) return;
    const copy = [...cards];
    const [moved] = copy.splice(index, 1);
    copy.splice(targetIndex, 0, moved);
    onChange(copy);
  };

  const handleSwapAll = () => {
    const swapped = cards.map(c => ({
      ...c,
      front: c.back,
      back: c.front,
    }));
    onChange(swapped);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center justify-between text-xs text-[var(--text-secondary)] px-1">
        <span className="font-semibold text-[var(--text-primary)]">
          {cards.length} {cards.length === 1 ? 'Card' : 'Cards'} in deck
        </span>
        <div className="flex items-center gap-2">
          <button
            type="button"
            onClick={handleSwapAll}
            className="flex items-center gap-1 px-2.5 py-1 rounded-lg bg-[var(--surface-1)] hover:bg-[var(--surface-2)] text-[var(--text-secondary)] hover:text-[var(--text-primary)] border border-[var(--border)] transition-all text-xs font-medium cursor-pointer shadow-xs active:scale-[0.98]"
            title="Swap front and back terms for all cards"
          >
            <ArrowUpDown size={12} /> Swap Terms / Definitions
          </button>
        </div>
      </div>

      {/* Individual Cards Stack - Quizlet Deck Maker Style */}
      <div className="space-y-3">
        {cards.map((card, index) => {
          const isFocused = focusedIndex === index;
          return (
            <div
              key={card.id}
              className={`rounded-2xl border transition-all duration-150 bg-[var(--surface-card)] shadow-xs ${
                isFocused
                  ? 'border-[var(--accent)] ring-2 ring-[var(--accent)]/15'
                  : 'border-[var(--border)] hover:border-[var(--border)]/80'
              }`}
            >
              {/* Card Header Bar */}
              <div className="flex items-center justify-between px-4 py-2 border-b border-[var(--border)]/70 bg-[var(--surface-1)]/50 rounded-t-2xl text-xs text-[var(--text-secondary)]">
                <div className="flex items-center gap-2">
                  <span className="w-6 h-6 rounded-md bg-[var(--surface-2)] border border-[var(--border)] flex items-center justify-center font-bold text-[11px] text-[var(--text-primary)]">
                    {index + 1}
                  </span>
                  <span className="text-[11px] font-medium text-[var(--text-muted)]">
                    Card #{index + 1}
                  </span>
                </div>

                <div className="flex items-center gap-1">
                  {/* Reorder Up/Down */}
                  <button
                    type="button"
                    disabled={index === 0}
                    onClick={() => handleMoveCard(index, 'up')}
                    className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-30 cursor-pointer disabled:cursor-not-allowed"
                    title="Move up"
                  >
                    ↑
                  </button>
                  <button
                    type="button"
                    disabled={index === cards.length - 1}
                    onClick={() => handleMoveCard(index, 'down')}
                    className="p-1 rounded text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-30 cursor-pointer disabled:cursor-not-allowed"
                    title="Move down"
                  >
                    ↓
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDuplicateCard(index)}
                    className="p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--surface-2)] transition-colors cursor-pointer"
                    title="Duplicate card"
                  >
                    <Copy size={13} />
                  </button>
                  <button
                    type="button"
                    onClick={() => handleDeleteCard(card.id)}
                    className="p-1.5 rounded-lg text-[var(--text-secondary)] hover:text-[var(--danger)] hover:bg-[var(--danger-bg)] transition-colors cursor-pointer"
                    title="Delete card"
                  >
                    <Trash2 size={13} />
                  </button>
                </div>
              </div>

              {/* Card Body - Front & Back Input Fields */}
              <div className="p-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                {/* Front Term */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] uppercase tracking-wider font-bold text-[var(--text-muted)]">
                      Term / Front (Prompt)
                    </label>
                  </div>
                  <textarea
                    rows={2}
                    value={card.front}
                    onFocus={() => setFocusedIndex(index)}
                    onChange={e => handleUpdateCard(card.id, 'front', e.target.value)}
                    placeholder="e.g. Capital of France"
                    className="w-full text-sm font-medium bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-3.5 py-2.5 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none transition-all resize-none placeholder:text-[var(--text-muted)]/70"
                  />
                </div>

                {/* Back Definition */}
                <div className="space-y-1.5">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] uppercase tracking-wider font-bold text-[var(--text-muted)]">
                      Definition / Back (Target Recall)
                    </label>
                  </div>
                  <textarea
                    rows={2}
                    value={card.back}
                    onFocus={() => setFocusedIndex(index)}
                    onChange={e => handleUpdateCard(card.id, 'back', e.target.value)}
                    placeholder="e.g. Paris"
                    className="w-full text-sm font-medium bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-3.5 py-2.5 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none transition-all resize-none placeholder:text-[var(--text-muted)]/70"
                  />
                </div>

                {/* Extra (optional, display-only) */}
                <div className="space-y-1.5 md:col-span-2">
                  <div className="flex items-center justify-between">
                    <label className="text-[11px] uppercase tracking-wider font-bold text-[var(--text-muted)]">
                      Extra (optional)
                    </label>
                  </div>
                  <textarea
                    rows={2}
                    value={card.extra ?? ''}
                    onFocus={() => setFocusedIndex(index)}
                    onChange={e => handleUpdateCard(card.id, 'extra', e.target.value)}
                    placeholder="Shown after you reveal the full answer -- not graded"
                    className="w-full text-sm font-medium bg-[var(--surface-1)] text-[var(--text-primary)] border border-[var(--border)] rounded-xl px-3.5 py-2.5 focus:border-[var(--accent)] focus:bg-[var(--surface-2)] outline-none transition-all resize-none placeholder:text-[var(--text-muted)]/70"
                  />
                </div>
              </div>
            </div>
          );
        })}
      </div>

      {/* Add Card Button */}
      <button
        type="button"
        onClick={() => handleAddCard()}
        className="w-full py-3 rounded-2xl border-2 border-dashed border-[var(--border)] hover:border-[var(--accent)] text-[var(--text-secondary)] hover:text-[var(--accent)] hover:bg-[var(--accent-bg)]/40 transition-all font-semibold text-sm flex items-center justify-center gap-2 cursor-pointer active:scale-[0.99] shadow-xs"
      >
        <Plus size={16} strokeWidth={2.5} /> + Add Card
      </button>
    </div>
  );
};
