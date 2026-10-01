// Per-deck session history: one entry per *completed* session (Final check
// done), built from the per-card telemetry applyAnswer records. Stopped
// sessions aren't logged -- they resume later and log once, on completion,
// with telemetry accumulated across every sitting.
//
// This is the real-usage data the handoff doc asks for when revisiting
// MIN_WORDS_TO_CHUNK: each card carries its word count and whether it was
// chunked, next to what it cost. It's included in backup exports.

import { DrillItem, LadderMode, SessionState, SessionStats } from '../types';
import { lsDelete, lsGet, lsSet } from './storage';

// Oldest entries drop off past this, to keep one deck's log bounded.
export const MAX_HISTORY_ENTRIES = 50;

export interface SessionHistoryCard {
  front: string;
  words: number;
  // Chunk count, or 0 for a card drilled whole (the 'full' stage).
  chunks: number;
  attempts: number;
  misses: number;
  reveals: number;
  nearMisses: number;
  finalMisses: number;
  hardSpans: string[];
}

export interface SessionHistoryEntry {
  startedAt?: string;
  finishedAt: string;
  stats: SessionStats;
  config: {
    encodeReps: number;
    chunkDifficulty: number;
    ladderMode: LadderMode;
    batchSize?: number;
  };
  cards: SessionHistoryCard[];
}

const historyKey = (slug: string) => `session-history:${slug}`;

export function getSessionHistory(slug: string): SessionHistoryEntry[] {
  if (!slug) return [];
  return lsGet<SessionHistoryEntry[]>(historyKey(slug)) ?? [];
}

export function setSessionHistory(slug: string, entries: SessionHistoryEntry[]): boolean {
  if (!slug) return false;
  return lsSet(historyKey(slug), entries.slice(-MAX_HISTORY_ENTRIES));
}

export function appendSessionHistory(slug: string, entry: SessionHistoryEntry): boolean {
  return setSessionHistory(slug, [...getSessionHistory(slug), entry]);
}

export function clearSessionHistory(slug: string): boolean {
  return lsDelete(historyKey(slug));
}

const wordCount = (s: string) => s.trim().split(/\s+/).filter(Boolean).length;

export function buildHistoryCard(item: DrillItem): SessionHistoryCard {
  return {
    front: item.front,
    words: wordCount(item.back),
    chunks: item.chunks?.length ?? 0,
    attempts: item.attempts ?? 0,
    misses: item.misses ?? 0,
    reveals: item.reveals ?? 0,
    nearMisses: item.nearMisses ?? 0,
    finalMisses: item.finalMisses ?? 0,
    hardSpans: item.hardSpans ?? [],
  };
}

export function buildHistoryEntry(state: SessionState, finishedAt: Date = new Date()): SessionHistoryEntry {
  return {
    startedAt: state.stats.startTime !== undefined ? new Date(state.stats.startTime).toISOString() : undefined,
    finishedAt: finishedAt.toISOString(),
    stats: state.stats,
    config: {
      encodeReps: state.config.encodeReps,
      chunkDifficulty: state.config.chunkDifficulty,
      ladderMode: state.config.ladderMode,
      batchSize: state.config.batchSize,
    },
    cards: state.items.map(buildHistoryCard),
  };
}

// How much trouble a card gave this session: misses and reveals, plus misses
// in the Final check (a card that slipped after being mastered is the
// clearest sign it isn't ready for Anki yet).
export function cardTroubleScore(item: DrillItem): number {
  return (item.misses ?? 0) + (item.reveals ?? 0) + (item.finalMisses ?? 0);
}

// The cards that cost the most, worst first: only cards with any trouble at
// all, ties broken by total attempts, then deck order.
export function rankHardestCards(items: DrillItem[], limit: number = 5): DrillItem[] {
  return items
    .filter(i => cardTroubleScore(i) > 0)
    .sort(
      (a, b) =>
        cardTroubleScore(b) - cardTroubleScore(a) ||
        (b.attempts ?? 0) - (a.attempts ?? 0) ||
        a.id - b.id
    )
    .slice(0, limit);
}
