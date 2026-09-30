// @vitest-environment jsdom
import { beforeEach, describe, expect, it } from 'vitest';
import { readSetting, SETTINGS, writeSetting } from '../utils/settings';

describe('settings', () => {
  beforeEach(() => localStorage.clear());

  it('returns each default when nothing is stored', () => {
    expect(readSetting('encodeReps')).toBe(3);
    expect(readSetting('chunkDifficulty')).toBe(35);
    expect(readSetting('batchSize')).toBe(5);
    expect(readSetting('stemTolerance')).toBe(true);
    expect(readSetting('ladderMode')).toBe('cumulative');
    expect(readSetting('cycleOrder')).toBe('shuffled');
    expect(readSetting('theme')).toBe('system');
  });

  it('round-trips values under the existing localStorage keys', () => {
    writeSetting('encodeReps', 5);
    writeSetting('batchSize', 0);
    writeSetting('stemTolerance', false);
    writeSetting('ladderMode', 'exhaustive');
    expect(localStorage.getItem('recall_drill_encode_reps')).toBe('5');
    expect(localStorage.getItem('recall_drill_stem_tolerance')).toBe('false');
    expect(readSetting('encodeReps')).toBe(5);
    expect(readSetting('batchSize')).toBe(0);
    expect(readSetting('stemTolerance')).toBe(false);
    expect(readSetting('ladderMode')).toBe('exhaustive');
  });

  it('falls back to the default for a malformed stored value', () => {
    localStorage.setItem(SETTINGS.encodeReps.key, 'abc');
    localStorage.setItem(SETTINGS.cycleOrder.key, 'backwards');
    expect(readSetting('encodeReps')).toBe(3);
    expect(readSetting('cycleOrder')).toBe('shuffled');
  });
});
