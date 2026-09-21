// Deterministic PRNG utilities for the Part 4 simulation harness. Lets
// npm run simulate report reproducible mean/SD statistics across N runs per
// (deck, learner) config instead of a single unseeded sample -- see
// simulate.stats.ts and simulate.report.ts. Not used by simulate.ts itself
// or by any shipped app code; harness-only.

// Small string -> 32-bit int hash (djb2-ish), used to turn a
// "deckName:learnerName" label into a stable base seed so re-running the
// harness reproduces the exact same N seeds every time.
export function hashSeed(label: string): number {
  let h = 0;
  for (let i = 0; i < label.length; i++) {
    h = (Math.imul(31, h) + label.charCodeAt(i)) | 0;
  }
  return h >>> 0;
}

// mulberry32: small, fast, good-enough-for-simulation seeded PRNG. Returns
// a zero-argument function matching Math.random()'s contract (a float in
// [0, 1)), so it can be swapped in for Math.random() wholesale.
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return function (): number {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Runs `fn` with the global Math.random temporarily replaced by a seeded
// generator, then restores it -- even if `fn` throws. simulate() (and
// drillEngine.ts's shuffle(), which it calls indirectly) both read
// Math.random() directly rather than accepting an injectable RNG, and this
// harness is explicitly not supposed to make app-code changes, so
// monkey-patching for the duration of one synchronous call is the
// lowest-footprint way to make a run reproducible.
export function withSeededRandom<T>(seed: number, fn: () => T): T {
  const original = Math.random;
  Math.random = mulberry32(seed);
  try {
    return fn();
  } finally {
    Math.random = original;
  }
}
