// Global "last used" setup settings, persisted in localStorage. Reads fall
// back to the default on a missing, malformed, or unreadable value; writes
// fail silently (private mode, quota), matching every call site's old inline
// try/catch.
//
// Per-deck settings (strictPunctuation) live on the deck's SavedDeckEntry
// instead -- see storage.ts.

import { CycleOrder, LadderMode } from '../types';

export type ThemeSetting = 'light' | 'dark' | 'system';

interface SettingDef<T> {
  key: string;
  defaultValue: T;
  // Returns undefined for a stored string that isn't a valid value.
  parse: (raw: string) => T | undefined;
}

const intSetting = (key: string, defaultValue: number): SettingDef<number> => ({
  key,
  defaultValue,
  parse: raw => {
    const n = parseInt(raw, 10);
    return Number.isNaN(n) ? undefined : n;
  },
});

const oneOf = <T extends string>(key: string, defaultValue: T, values: readonly T[]): SettingDef<T> => ({
  key,
  defaultValue,
  parse: raw => (values.includes(raw as T) ? (raw as T) : undefined),
});

export const SETTINGS = {
  encodeReps: intSetting('recall_drill_encode_reps', 3),
  chunkDifficulty: intSetting('recall_drill_chunk_difficulty', 35),
  // C3: 0 means "whole deck as one batch" (see partitionIntoBatches).
  batchSize: intSetting('recall_drill_batch_size', 5),
  stemTolerance: {
    key: 'recall_drill_stem_tolerance',
    defaultValue: true,
    parse: (raw: string) => raw === 'true',
  } as SettingDef<boolean>,
  ladderMode: oneOf<LadderMode>('recall_drill_ladder_mode', 'cumulative', ['cumulative', 'exhaustive']),
  cycleOrder: oneOf<CycleOrder>('recall_drill_cycle_order', 'shuffled', ['shuffled', 'inOrder']),
  theme: oneOf<ThemeSetting>('recall_drill_theme', 'system', ['light', 'dark', 'system']),
};

type Settings = typeof SETTINGS;
export type SettingName = keyof Settings;
type SettingValue<K extends SettingName> = Settings[K]['defaultValue'];

export function readSetting<K extends SettingName>(name: K): SettingValue<K> {
  const def = SETTINGS[name] as SettingDef<SettingValue<K>>;
  try {
    const raw = localStorage.getItem(def.key);
    if (raw !== null && raw !== '') {
      const parsed = def.parse(raw);
      if (parsed !== undefined) return parsed;
    }
  } catch {
    // ignore
  }
  return def.defaultValue;
}

export function writeSetting<K extends SettingName>(name: K, value: SettingValue<K>): void {
  try {
    localStorage.setItem(SETTINGS[name].key, String(value));
  } catch {
    // ignore
  }
}
