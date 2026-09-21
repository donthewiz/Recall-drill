// Statistical aggregation for the Part 4 harness: runs a given simulation
// N times under independent-but-reproducible seeds and reports mean/SD
// instead of a single sample. Generic over which underlying simulate
// function is used (simulate.ts's Cue-based one, or simulateLegacy.ts's
// isBlind-based Phase 0 one) -- both just need to produce a SimulationResult
// from a zero-argument thunk.
import { hashSeed, withSeededRandom } from './prng';
import type { SimulationResult } from './simulate';

export interface RunStats {
  mean: number;
  sd: number;
}

export interface AggregatedResult {
  totalTrials: RunStats;
  keystrokes: RunStats;
  wallClockEstimate: RunStats;
}

function meanSd(values: number[]): RunStats {
  const mean = values.reduce((a, b) => a + b, 0) / values.length;
  if (values.length < 2) return { mean, sd: 0 };
  // Sample standard deviation (n-1 denominator) -- these are N independent
  // draws from the same config, not the whole population of possible runs.
  const variance = values.reduce((acc, v) => acc + (v - mean) ** 2, 0) / (values.length - 1);
  return { mean, sd: Math.sqrt(variance) };
}

// seedLabel should uniquely identify the (deck, learner, [engine]) config so
// re-running the report reproduces the exact same N seeds -- and so a
// "current engine" run and a "legacy engine" run for the same deck/learner
// don't accidentally share a seed sequence.
export function runSeeded(seedLabel: string, runs: number, runOnce: () => SimulationResult): AggregatedResult {
  const baseSeed = hashSeed(seedLabel);
  const totalTrials: number[] = [];
  const keystrokes: number[] = [];
  const wallClockEstimate: number[] = [];

  for (let i = 0; i < runs; i++) {
    const result = withSeededRandom(baseSeed + i, runOnce);
    totalTrials.push(result.totalTrials);
    keystrokes.push(result.keystrokes);
    wallClockEstimate.push(result.wallClockEstimate);
  }

  return {
    totalTrials: meanSd(totalTrials),
    keystrokes: meanSd(keystrokes),
    wallClockEstimate: meanSd(wallClockEstimate),
  };
}

export function fmt(stats: RunStats, decimals = 1): string {
  return `${stats.mean.toFixed(decimals)} ± ${stats.sd.toFixed(decimals)}`;
}

// "Not distinguishable": the two means are close enough that either could
// plausibly be a resample of the other, given the noise already observed.
// Uses the larger of the two series' own SDs as the yardstick (the more
// conservative of the two, rather than picking one side arbitrarily) --
// diff <= max(sdA, sdB) means "within one SD" in either direction.
export function withinOneSd(a: RunStats, b: RunStats): boolean {
  const diff = Math.abs(a.mean - b.mean);
  return diff <= Math.max(a.sd, b.sd);
}
