# Recall Drill v2 — Implementation Handoff

**For:** Sonnet 5, coding agent, working in `donthewiz/Recall-drill` (main)
**From:** design session, 2026-09-19
**Read this whole document before writing any code.** The sequencing in Part 3 is not optional — several changes are load-bearing for the ones after them, and doing them out of order will produce a tangle.

---

## Part 0 — Scope decision (settled, do not relitigate)

Recall Drill is a **session-only drill tool**. It gets material to criterion in one sitting. Anki owns long-term retention.

Consequences that bind every decision below:

- **Do not build a scheduler.** No due dates, no intervals, no FSRS, no cross-session decay. `handleFinishSession` clearing saved state on full mastery is correct behavior, not a bug.
- **The criterion bar is "encoded well enough to hand to Anki," not "retained."** Anki re-tests tomorrow. Every trial spent past the encoding bar is paid twice. Trial-count reduction is therefore the top priority, not a nice-to-have.
- **Do not add multiple choice as the primary scaffold.** Decks hold prose answers; distractors drawn from other cards' backs are trivially discriminable for sentences. An optional MC rung for short backs is Phase 7 and is off by default.

---

## Part 1 — Current architecture (verified, so you don't have to re-derive it)

### Files

| Path | Role |
|---|---|
| `src/types.ts` | `DrillItem`, `SavedSessionState`, `EncodeStage`, etc. |
| `src/utils/drillEngine.ts` | Pure-ish helpers: `norm`, `computeWordDiff`, `chunkText`, `buildCombineSequence`, `findAllCulpritChunks`, `splitInHalf`, `culpritHalf`, `buildItems`, `normalizeItem`, localStorage helpers |
| `src/components/SessionView.tsx` | **All** session state machine logic, inline in `handleCheck` + `advanceEncode` + `advanceCycle` |
| `src/components/SetupView.tsx` | Deck editor, reps slider, chunk-difficulty slider, resume prompt |
| `src/components/DoneView.tsx` | End-of-session stats |
| `src/App.tsx` | View routing, session lifecycle, localStorage prefs |
| `src/components/HelpModal.tsx` | User-facing explanation of the method |

### The state machine as it stands

**Encode phase**, per item, strictly serial (`advanceEncode` takes `remaining[0]` — deck order, fully massed, no interleaving whatsoever):

1. `stage: 'chunks'` — each chunk needs `encodeReps` *consecutive* correct. `isBlind = chunkStreak >= 1`, so attempt 1 is copy-typing with the answer visible in both `subText` and `placeholder`.
2. `stage: 'combine'` — walks `combineSeq`, each window needs `encodeReps` consecutive correct.
3. `stage: 'remediate'` — on combine miss, `findAllCulpritChunks` identifies bad chunks, pushes onto `remediateStack`, drills each to `encodeReps`, recursively halving via `splitInHalf`/`culpritHalf` after 2 further misses. Returns to `combineSeqIdx = remediateReturnSeqIdx`.
4. `stage: 'full'` — for answers ≤3 words or `chunkDifficulty >= 100`; needs `encodeReps` consecutive.

Item hits `status: 'ready'` when the ladder completes.

**Cycle phase**: all `ready` items shuffled into a queue. `cycleStreak >= 2` → `mastered`. Miss → reinsert at `2 + rand(0..1)`. Correct-but-unmastered → reinsert at position `min(3, len)`.

### Measured cost of the current design

`buildCombineSequence(n)` emits `{start: e-s+1, end: e}` for `e = 2..n`, `s = 2..e` — that is **n(n−1)/2 windows**, each needing `encodeReps` consecutive correct.

For a 4-chunk answer at the default `encodeReps = 3`:

- chunks: 4 × 3 = **12 trials**
- combine: 6 windows × 3 = **18 trials**
- cycle: **2 trials**
- **≥ 32 correct typings for one card**, before any miss or remediation.

At 6 chunks it is 18 + 45 + 2 = **65**. A 30-card chapter deck is four to five figures of keystrokes. This is the single biggest problem in the app and it is self-inflicted, not a missing feature.

### Bugs found during review (fix these; they are not optional polish)

**B1 — `findAllCulpritChunks` aligns positionally and will misfire catastrophically.**
It slices `typedWords` by cumulative chunk word-counts. If the user omits *one* word early in the window, every subsequent slice is shifted and every remaining chunk is flagged as a culprit. A single dropped article therefore queues the entire window for remediation. This is a major contributor to the trial explosion above. **Fix: reuse the LCS alignment already computed in `computeWordDiff` to attribute mismatches to chunks, rather than positional slicing.**

**B2 — Revealing the answer does not affect grading.**
`handleCheck` never reads `userRevealedAnswer`. Press Esc, read the answer, type it, and it counts as a full blind success and advances the streak. Criterion is therefore not what the UI claims. **Fix: a revealed trial must not advance the streak. It should reset it to 0 and not count as a miss.**

**B3 — `NodeJS.Timeout`** is used as a type in browser code. Use `ReturnType<typeof setTimeout>`.

**B4 — `useTransition` is imported in `SessionView.tsx` and never used.** Remove.

**B5 — `handleKeyDown` Enter → `handleNext()` is not guarded by `isProcessing`.** A fast double-Enter during the feedback window can skip a trial. Guard it.

---

## Part 2 — The seven changes

Each change lists intent, exact mechanics, and its acceptance test. Do not improvise alternatives; if a spec here looks wrong once you're in the code, stop and say so rather than substituting your own design.

---

### C1 — Replace the exhaustive combine ladder with forward chaining

**Why:** the current sequence re-verifies sub-spans that the learner has already produced correctly inside a longer span. The remediation system is what catches genuine weak spots, and it targets better than an exhaustive ladder does.

**Mechanics:**

```ts
// drillEngine.ts
export type LadderMode = 'cumulative' | 'exhaustive';

export function buildCombineSequence(
  n: number,
  mode: LadderMode = 'cumulative'
): CombineSequenceItem[] {
  if (mode === 'exhaustive') { /* keep existing body verbatim */ }
  // cumulative / forward chaining: 1–2, 1–3, ..., 1–n  → n-1 windows
  const seq: CombineSequenceItem[] = [];
  for (let e = 2; e <= n; e++) seq.push({ start: 1, end: e });
  return seq;
}
```

- `{start, end}` shape is unchanged, so `findAllCulpritChunks`, `remediateReturnSeqIdx` and the combine branch of `handleCheck` need no structural change.
- **Per-window rep requirement:** intermediate windows (`end < n`) require **1** blind success. Only the final window (`end === n`) requires `encodeReps`. Add `requiredRepsForWindow(seqItem, n, encodeReps)` to `drillEngine.ts`.
- Expose `ladderMode` as a setting in `SetupView` (default `'cumulative'`), persisted to `localStorage` under `recall_drill_ladder_mode`. Keeping `'exhaustive'` available is deliberate: it lets the trial-count claim be measured rather than trusted.

**New cost for a 4-chunk answer, `encodeReps = 3`:** 12 chunk + (1 + 1 + 3) combine + 2 cycle = **19**, down from 32. At 6 chunks: 18 + (1×4 + 3) + 2 = **27**, down from 65.

**Acceptance:** `buildCombineSequence(6, 'cumulative').length === 5`; `buildCombineSequence(6, 'exhaustive').length === 15`. Trial-count simulation (Part 4) shows ≥40% reduction on the fixture deck for a perfect learner.

---

### C2 — Lenient grading with near-miss tier and manual override

**Why:** grading is `norm(typed) === norm(target)`. A dropped "the" scores identically to not knowing the answer. This inflates repetition load without adding learning, and it is the most frustrating interaction in the app.

Note `norm()` already strips punctuation and lowercases, so this is purely about word-level differences.

**Mechanics:**

```ts
// drillEngine.ts
export type Verdict = 'exact' | 'near' | 'wrong';

export interface GradeResult {
  verdict: Verdict;
  diff: WordDiffResult[];
  missingWords: string[];
  extraWords: string[];
  similarity: number; // 0..1
}

export function grade(typed: string, target: string, opts?: {
  lenient?: boolean;        // default true
  stemTolerance?: boolean;  // default true
}): GradeResult;
```

Rules, in order:

1. `norm(typed) === norm(target)` → `exact`.
2. Otherwise compute the LCS alignment (extract the DP from `computeWordDiff` into a shared `alignWords()` — do not duplicate it). `similarity = 2 * lcsLength / (typedLen + targetLen)`.
3. `near` if **either**:
   - every missing and extra word is in a `STOPWORDS` set (`a an the of to in on for and or is are was were that this it its as at by with from`), **or**
   - `similarity >= 0.9` **and** every missing word is a stopword or differs from a typed word only by a light stem (strip trailing `s`, `es`, `ed`, `ing`).
4. Otherwise `wrong`.

Behavior:

- `near` **advances the streak** exactly like `exact`. It does **not** increment `stats.misses`. It increments a new `stats.nearMisses`, shows the diff with a neutral-toned note ("close — target wording: …") for ~1200ms, then advances.
- `stemTolerance` must be a user setting (`recall_drill_stem_tolerance`, default on) with a visible caption warning that it should be turned **off** for terminology decks where inflection matters. Don's HR105 medical terminology deck is exactly that case.
- **Manual override:** during the feedback window after a `wrong` verdict, show a button "Count as correct" bound to `Ctrl+Enter`. It converts the trial to `exact` retroactively: advance the streak, decrement `stats.misses`, increment `stats.overrides`. Must be reachable before auto-advance fires — extend the feedback dwell for `wrong` verdicts to 2200ms, or better, require an explicit Enter/Next on `wrong` (see C5).

**Acceptance:** unit tests over a table of (typed, target, expected verdict) covering: exact, stopword-only omission, stopword-only insertion, plural difference, one content word wrong (must be `wrong`), transposed clause, empty input (must be `wrong`).

---

### C3 — Batch the encode phase (set-level chunking)

**Why:** encoding is currently fully massed — card 1 is drilled to completion before card 2 is touched. There is no interleaving anywhere in the encode phase, and the single cycle queue over an entire deck produces a session with no stopping points.

**Mechanics:**

- Add to `SavedSessionState`: `batchSize: number` (default 5, user-settable 3–10, plus "whole deck"), `batchIndex: number`.
- Partition items into batches **in deck order** — chapter decks are topically ordered and batch composition should respect that. Shuffle only the *trial order within* a batch.
- **Rotation granularity matters.** Do not interleave at the individual-trial level: the chunk→combine chain depends on contiguity, and shredding it defeats the chaining design. Rotate to the next unfinished item in the batch **after each completed stage-unit** — one chunk learned, one combine window learned, one remediation span cleared. Implement as `selectNextEncodeItem(batch, lastItemId)` in `drillEngine.ts`, round-robin over batch members whose status is not `ready`.
- When every item in a batch is `ready`, run the cycle phase **scoped to that batch** until all are `mastered`, then advance `batchIndex`.
- Add a **batch interstitial** screen between batches: batch number, items mastered, trials spent, accuracy, and two buttons — "Next batch" and "Save and stop". "Save and stop" must persist cleanly and resume at the batch boundary.
- Migration in `normalizeItem` / session load: a saved state with no `batchIndex` is treated as `batchIndex: 0, batchSize: items.length`.

**Acceptance:** a 13-card deck at `batchSize: 5` produces batches of 5/5/3; encode trial order within a batch shows at least one item switch before any item reaches `ready`; resume after "Save and stop" restores the same batch and the same per-item stage state.

---

### C4 — Honest progress display

**Why:** the bar is `mastered / items.length`. It reads 0% through the entire encode phase of a long deck, which is the largest phase. That is a retention problem for the app, independent of memory science.

**Mechanics:**

```ts
// drillEngine.ts — pure, unit-tested
export function computeItemProgress(item: DrillItem, encodeReps: number): number; // 0..1
export function computeSessionProgress(items: DrillItem[], encodeReps: number): {
  deckFraction: number;
  batchFraction: number;
  masteredCount: number;
  readyCount: number;
};
```

Weighting: `new` = 0; `encoding` = fraction of the item's own ladder completed (chunks done / total chunks, then combine windows done / total windows, scaled into the 0–0.7 band); `ready` = 0.7; `mastered` = 1.0.

UI: two bars in `SessionView` — **batch** (primary, prominent) and **deck** (secondary, thin) — plus the existing `mastered/total` counter as a label. Do not remove the counter; add to it.

**Acceptance:** progress is strictly monotonic across a simulated session (never decreases), starts > 0 after the first correct chunk, and reaches exactly 1.0 only when all items are `mastered`.

---

### C5 — Cue fading replaces copy-typing

**Why:** attempt 1 of every stage-unit currently shows the full target in both `subText` and `placeholder`. That is transcription, not retrieval, and generates near-zero learning. It is roughly a third of all trials in the encode phase.

**Mechanics:**

Stop deriving cue level from streak counters (`isBlind = streak >= 1`, repeated in four places). Introduce an explicit cue model:

```ts
// types.ts
export type Cue =
  | { kind: 'none' }
  | { kind: 'firstLetter'; pattern: string }
  | { kind: 'full'; text: string }          // reveal only, never on attempt 0
  | { kind: 'choice'; options: string[] };  // Phase 7, off by default
```

Ladder per stage-unit:

- **attempt 0:** `firstLetter`. Render each target word as its first character followed by underscores matching the remaining length, preserving word count and separators: `"The heart pumps blood"` → `"T__ h____ p____ b____"`. Put the pattern in `subText`; set `placeholder` to the pattern too.
- **attempt 1 and later:** `{ kind: 'none' }`.
- **Esc / "Show answer":** reveals `{ kind: 'full' }`. Per **B2**, a trial completed after a reveal resets the streak to 0 and does **not** count as a miss. Surface this in the UI copy so it isn't a surprise ("revealing resets the streak for this part").

Add `renderFirstLetterCue(target: string): string` to `drillEngine.ts`.

On a `wrong` verdict, replace the timed auto-advance with an **explicit** advance (Enter or the Next button), so the correction is actually read and the override in C2 is reachable. Keep auto-advance for `exact`. Use the short dwell for `near`.

**Acceptance:** `renderFirstLetterCue` preserves word count and punctuation position; a full-session simulation contains zero trials where the complete target text is visible before the first attempt; a revealed-then-correct trial leaves the streak at 0.

---

### ~~C6 — Anki handoff export~~ (DROPPED)

**DROPPED 2026-09-20 — not deferred, cut from v2 scope.** Kept below,
struck, so the original reasoning stays on record; do not build this
against this doc.

**Why:** this is the only feature on the list that Anki can't do for itself. Recall Drill knows which items cost the most trials and *where inside the answer* the failures clustered — `combineMissCount` and `remediateStack` already carry that. Exporting it makes the two tools complementary rather than sequential.

**Mechanics:**

- Add per-item telemetry to `DrillItem`: `trialCount`, `missCount`, `nearMissCount`, `revealCount`, `hardSpans: string[]` (push `rTop.text` each time a span enters `remediateStack`, deduped).
- Difficulty tier from `missCount + revealCount`: 0 → `easy`, 1–2 → `med`, ≥3 → `hard`.
- In `DoneView`, add **"Export for Anki"** producing tab-separated rows with a header comment, and a "Copy to clipboard" button plus a `.tsv` download:

  ```
  #separator:tab
  #html:false
  #tags column:3
  <front>\t<back>\t rd::<tier> rd::deck::<slug>
  ```

- Include an optional fourth column with the hard spans joined by ` | `, gated behind a checkbox ("include trouble-spot notes"), since it only helps if the target note type has a spare field.
- **Optional stretch, clearly marked as such:** direct push via AnkiConnect at `http://localhost:8765` using the `addNotes` action. This only works if the app's origin is in AnkiConnect's `webCorsOriginList`; implement with a connection test and a clear failure message that falls back to the TSV path. Do not make this the default.

**Acceptance:** exported TSV round-trips through Anki's import with tags landing in the tag field; tier assignment matches the telemetry on a simulated session.

---

### ~~C7 (optional, build last, default OFF) — Multiple-choice rung for short backs~~ (DROPPED)

**DROPPED 2026-09-20 — not deferred, cut from v2 scope.** Kept below,
struck, so the original reasoning stays on record; do not build this
against this doc.

Only eligible when `norm(back).split(' ').length <= 4` **and** the deck has ≥4 items whose backs are distinct and within ±2 words of the target's length. Generate 3 distractors from those backs. Insert as attempt 0, pushing `firstLetter` to attempt 1 and blind to attempt 2.

If the eligibility test fails for an item, that item silently uses the C5 ladder. Setting: `recall_drill_mc_rung`, default `false`.

Do not spend time here until C1–C6 are merged and verified.

---

### C8 — chunk-stage criterion

**Why:** the chunks stage was never touched by C1–C5 and is now the largest
single cost in a prose deck's trial count (~60% of `proseDeck`'s trials,
per `docs/BASELINE.md`). Each chunk needs `encodeReps` consecutive correct
answers, and then every chunk is re-tested again inside every combine
window that includes it, and *again* in the cycle phase once the item is
ready — the same word sequence drilled to the same criterion three separate
times. Where a chunk is a genuine weak spot, the combine stage already
catches it (a combine miss triggers remediation, which drills exactly the
culprit chunk) — that's error-driven allocation, which is what the
remediation system is for. Paying the full `encodeReps` cost *again* at the
chunk level, before combine or cycle ever get a chance to test it, is
redundant repetition, not learning.

Split into two independently measurable parts so the Part 4 harness can
show each one's effect before the next lands.

---

### C8a — chunks stage advances on one blind success

**Mechanics:**

- The chunks stage's advance criterion changes from "`chunkStreak` reaches
  `encodeReps`" to "one correct answer at cue level `'none'`" (fully
  blind). A correct answer at cue level `'firstLetter'` (attempt 0) still
  happens and still moves the chunk from cued to blind, but it does **not**
  advance `chunkIndex` by itself.
- `encodeReps` no longer paces the chunks stage at all — including at
  `encodeReps: 1`, where a chunk previously advanced on the very first
  (cued) correct answer. After C8a every chunk needs its cued attempt
  *and* one blind success, regardless of the `encodeReps` setting.
- `encodeReps` continues to govern exactly what it governed before this
  change for every other stage: the **final** combine window (intermediate
  windows already only need 1 rep under the cumulative ladder, per C1) and
  the `full` stage (short, unchunked answers). Remediation's own
  `encodeReps` threshold is untouched — it isn't part of the chunks-stage
  triple-count this change targets.
- A miss on the blind attempt resets `chunkStreak` to 0 (back to the cued
  attempt), unchanged from today.
- Update `SetupView`'s reps-slider caption: it currently reads "Blind
  typings required to encode each chunk/card" and describes e.g. "3
  consecutive blind completions" — that's no longer true of chunks, only of
  the final combination and short (`full`-stage) cards.
- **Migration:** `chunkStreak`'s valid range for stage `'chunks'` shrinks
  to `{0, 1}` (a blind success always advances and resets it immediately
  now, so it never legitimately grows past 1). A save from before C8a can
  have a `chunkStreak` up to `encodeReps - 1` for an item mid-chunks-stage;
  `normalizeItem` should clamp any such value down to 1 on load
  (interpreted as "already past the cued attempt, one blind success away").

**Acceptance:** for any `encodeReps` value, a chunk needs exactly one
correct cued (`'firstLetter'`) answer followed by exactly one correct blind
(`'none'`) answer to advance — never fewer, never more, and never
`encodeReps`-many. Combine's final window and the `full` stage are
unaffected. Re-run the Part 4 harness and report the table before moving to
C8b — if chunk trials don't drop, stop and report rather than proceeding.

---

### C8b — presentation trial replaces the cued chunk attempt

**Mechanics:**

- Add `{ kind: 'present' }` to the `Cue` union (`types.ts`). It carries no
  payload — the text to show is `Trial.target`, same as every other cue.
- The chunks stage's attempt 0 (`chunkStreak === 0`) becomes a
  presentation, not a graded typing attempt: `selectTrial` returns
  `cue: { kind: 'present' }` instead of `firstLetter`. The chunk's full
  text is shown, no input is accepted, and the learner presses Enter (or a
  "Continue" button) to move on — there is nothing to grade.
- `applyAnswer` handles a presentation trial as a distinct path, short of
  the normal grade-and-branch chunks logic: it advances `chunkStreak` from
  0 to 1 unconditionally, does **not** call `grade()`, and does **not**
  increment `stats.attempts` (nothing was attempted) or `stats.misses`
  (nothing can be wrong). It returns a new `'presented'` verdict so the
  shell can render it distinctly from a graded `'exact'`.
- Attempt 1 (`chunkStreak === 1`, cue `'none'`) is unchanged from C8a: the
  first — and only — typed, graded, blind attempt.
- In `test/simulate.ts`'s harness, a presentation trial still counts as one
  trial (`totalTrials`, `trialsByStage`) so it's represented in the
  wall-clock estimate (reading time isn't free), but contributes 0 to
  `keystrokes` (nothing is typed).

**Acceptance:** the chunks stage never shows a graded typing attempt with
the full answer already visible (the old `firstLetter` cue is gone from
chunks entirely) — attempt 0 is a pure read, attempt 1 is the first real
retrieval attempt. A presentation trial never appears in `stats.attempts`,
`stats.misses`, or a diff. Re-run the Part 4 harness and report the table
again.

---

## Part 3 — Method: how to execute this

**This sequencing is the most important instruction in the document.**

`handleCheck` is currently a ~300-line branching function that mutates a cloned item, calls four different `setState`s, and chains the next trial through `setTimeout`. Every change in Part 2 touches it. If you bolt seven features onto that structure you will produce something untestable and Don will get regressions he can't localize.

### Phase 0 — Characterize, then extract (no behavior changes)

1. Add Vitest if absent (`vitest`, `@testing-library/react`, `jsdom`). Wire `npm test`.
2. Write **characterization tests** that lock in current behavior: a scripted sequence of answers against a fixture deck, asserting the exact sequence of `(stage, target, streak, status)` transitions. These tests are the safety net. Write them against the code as it is, before changing anything.
3. **Extract the state machine out of React into pure functions in `drillEngine.ts`:**

   ```ts
   export interface SessionState {
     items: DrillItem[];
     phase: 'encode' | 'cycle';
     queue: number[];
     stats: SessionStats;
     currentId: number;
     batchIndex: number;
     config: SessionConfig; // encodeReps, chunkDifficulty, batchSize, ladderMode, lenient, stemTolerance
   }

   export interface Trial {
     itemId: number;
     stage: EncodeStage | 'cycle';
     prompt: string;   // front
     target: string;   // what must be typed
     cue: Cue;
     label: string;        // stage pill
     detail: string;       // phase detail line
   }

   export function selectTrial(state: SessionState): Trial | null;
   export function applyAnswer(
     state: SessionState,
     typed: string,
     opts: { revealed: boolean; override?: boolean }
   ): { state: SessionState; verdict: Verdict; feedback: Feedback; advance: 'auto' | 'manual' };
   ```

   No React, no `setTimeout`, no mutation of inputs — return new state. `SessionView` becomes: render `selectTrial(state)`, call `applyAnswer` on submit, render feedback, schedule or await advance.

4. Run the characterization tests against the extracted reducer. **They must pass unchanged.** Do not proceed until they do.

### Phase 1 — Bug fixes

B1 (LCS-based culprit attribution), B2 (reveal affects grading), B3–B5. Update characterization tests where B1/B2 intentionally change behavior, and note in the commit which assertions moved and why.

### Phase 2 — C2 (grading) → Phase 3 — C1 (ladder) → Phase 4 — C5 (cue fading)

These three are the trial-count reductions and they compound. Do them in this order: grading first, because the trial-count simulation in Part 4 is only meaningful once near-misses stop being scored as failures.

### Phase 5 — C3 (batching) → Phase 6 — C4 (progress)

Batching changes the shape of `SessionState`; progress display depends on it.

### ~~Phase 7 — C6 (export), then C7 (MC) if time allows.~~ (DROPPED 2026-09-20 — see C6/C7 in Part 2)

### Phase 8 — C8a (chunk-stage criterion, part 1) → Phase 9 — C8b (presentation trial, part 2)

Two independently measurable parts, per C8's own acceptance criteria — stop
and re-run the Part 4 harness after C8a before starting C8b, not just at
the end of both.

**Commit per phase.** Each commit: passing tests, a one-line trial-count delta from the Part 4 harness in the message.

---

## Part 4 — Verification: make the cost measurable

Don't take the trial-count claims in this document on faith. Build the harness in Phase 0 and use it as the scoreboard.

```ts
// test/simulate.ts
type LearnerModel = {
  // probability of a correct answer given attempt index and cue level
  pCorrect(attemptIdx: number, cue: Cue, priorExposures: number): number;
};

export function simulate(deck: DeckItem[], config: SessionConfig, learner: LearnerModel): {
  totalTrials: number;
  trialsByStage: Record<string, number>;
  keystrokes: number;   // sum of target lengths actually typed
  wallClockEstimate: number; // keystrokes / 4.5 cps + per-trial overhead
};
```

Three learner models: **perfect** (always correct), **realistic** (0.55 on first blind attempt, rising ~0.12 per prior exposure, capped 0.95), **struggling** (0.3 base, +0.08). Two fixture decks: 12 short term↔definition cards, and 12 prose cards averaging 18 words.

Report a table before/after each phase. The design targets:

| Metric (realistic learner, prose deck) | Baseline | Target |
|---|---|---|
| Total trials | measure first | ≤ 45% of baseline |
| Keystrokes | measure first | ≤ 50% of baseline |
| Trials where full target was visible pre-attempt | ~33% | 0% |
| Est. wall clock | measure first | ≤ 50% of baseline |

If a phase doesn't move its metric in the expected direction, **stop and report** rather than proceeding. A change that doesn't reduce cost isn't worth the regression risk.

Also add, at the end: a **manual smoke checklist** in `docs/SMOKE.md` — start a fresh session, mid-session refresh and resume, batch interstitial save-and-stop, override on a wrong answer, reveal-then-type, export TSV, and a 100-card deck for a performance sanity check (`persistState` serializes the whole item array on every trial; check it doesn't stutter, and if it does, debounce it).

---

## Part 5 — Things to leave alone

- The remediation design (recursive halving to the culprit span). It's the strongest idea in the app. Fix its input (B1); don't redesign it.
- Typed free recall as the universal response mode. Don't soften it into recognition.
- Deck/folder management, the card editor, theming, premade decks. Out of scope.
- The `chunkDifficulty` percentage model. It works; it just feeds too large a ladder, which C1 fixes.
- `handleFinishSession` clearing state on full mastery. Correct under session-only scope.

---

## Part 6 — Update the user-facing explanation

`HelpModal.tsx` currently describes the old method ("broken into small 4-word chunks", "2 correct recall trials"). Rewrite it to match the shipped behavior: batches, the cue ladder, forward chaining, lenient grading with override, and the Anki handoff. Keep it to the same four-section format. Do this in the final phase, from the code as merged — not from this document.

---

## Part 7 — Results

The full measurement trail (every phase's before/after table, the harness
rework to seeded N=50 runs, and the corrections to two earlier overclaims)
lives in [`docs/BASELINE.md`](./BASELINE.md). These are the three numbers
worth remembering from it, stated at the same honesty level as that file:

1. **`proseDeck` (chunked, multi-word answers) is robustly, distinguishably
   cheaper than Phase 0, for every learner.** Perfect: 240.0 ± 0.0 → 144.0 ±
   0.0 trials (17472 → 9764 keystrokes). Realistic: 454.4 ± 33.6 → 257.9 ±
   31.0. Struggling: 945.5 ± 66.5 → 762.7 ± 80.7. This is the real,
   load-bearing effect of C1 (forward-chaining ladder), C2 (lenient
   grading), C5 (cue fading), and C8a/C8b (chunk-stage criterion,
   presentation trial) combined — measured on a deck with enough chunked,
   multi-word surface area for those mechanisms to matter.
2. **`shortDeck` (1-2 word answers, never chunks) is not statistically
   distinguishable from Phase 0 at N=50, for any learner.** C1 and C8a/C8b
   structurally cannot touch a deck with zero chunked cards. C2 and C5 *can*
   run on the `full` stage, but their effect on answers this short is too
   small to clear the sampling noise floor. An earlier draft of this
   document's baseline overstated this as "nothing from C1–C8 touches that
   code path," which conflated "too small to measure" with "structurally
   inapplicable" — corrected in `docs/BASELINE.md`.
3. **`MIN_WORDS_TO_CHUNK` (raised from 3 to 8) is a real, current-vs-current
   win on `mediumDeck` (backs 4-8 words) — realistic learner 259.9 ± 28.7 →
   92.0 ± 6.2 trials — but that win belongs entirely to the threshold
   constant, not to C1-C8.** It's a fixture-shape effect: a back either
   clears the word-count bar and skips the ladder, or it doesn't, with no
   dependency on any of the ladder/grading/chunk-stage work. An earlier
   draft reported this as a Phase-0-vs-final comparison (231 → 141 → 60),
   which was invalid — `LegacyEngine` shares `chunkText` live with the
   current engine, so the "Phase 0" side moves under the same threshold
   change instead of staying fixed. The valid comparison is current-engine-
   against-itself, before and after the constant changed.

**Scope cuts.** C6 (Anki handoff export) and C7 (multiple-choice rung) were
dropped from v2's scope on 2026-09-20 — not deferred — see the struck
sections in Part 2.

**One knob worth revisiting from real usage, not simulation.**
`MIN_WORDS_TO_CHUNK = 8` was tuned against a synthetic 12-card fixture
(`mediumDeck`) built specifically to have backs in the 4-8 word range no
other fixture covered. It's a plain constant in `drillEngine.ts`, not a
structural decision — if real decks show people struggling with 6-8 word
answers presented whole, or sailing through 9-10 word answers that still
get chunked, move it.

---

## Known limitations

- **Exact match is spacing-insensitive; `alignWords` is not.** `grade()`'s
  exact check (via `exactMatch`) strips all spaces after normalizing, so a
  pure spacing/punctuation variant like `"pre op"` vs `"pre-op"` matches
  outright. But if that same attempt also has an unrelated word-level
  difference (so the exact check misses and grading falls through to
  `alignWords`'s per-word comparison), the spacing variant is now just two
  different tokens to the aligner — it can misattribute which word is at
  fault, or tip a near-miss into `wrong`, or (inside remediation)
  misattribute the culprit chunk. "Count as correct" (Ctrl+Enter) is the
  escape hatch for this case.
- **`npm run simulate` does not exercise punctuation variants.** Its
  synthetic decks (`shortDeck`/`mediumDeck`/`proseDeck`) and learner models
  never type punctuation, so it can't measure the punctuation-normalization
  change in `norm()`/`grade()` one way or the other — it's only useful here
  as a check that the change didn't regress trial/keystroke counts on
  ordinary text (it doesn't). `src/test/grade.spec.ts`'s punctuation table
  is the actual evidence for this change's grading behavior.

---

## Per-deck strict punctuation mode

A deck's "Punctuation must match" setting (`strictPunctuation` on its
`SavedDeckEntry`/`SessionConfig`) swaps `grade()`'s comparator from `norm()`
to `normStrict()` and disables the near-miss tier entirely: every word is
required (no stopword or stem forgiveness, regardless of the deck's own
stem-tolerance setting, which the UI disables while strict is on) and every
non-exact answer grades `wrong`. Within that stricter word-for-word
requirement, hyphens, slashes, `+ % < > =`, and a digit-internal decimal
point (`7.35`) still count and must match literally — a strict deck won't
silently accept `74` for `7.4` or `and or` for `and/or`. Brackets, quotes,
apostrophes, commas, colons, semicolons, accents, and a sentence-ending
`. ! ?` are still ignored, same spirit as lenient mode, just without the
word-level leniency layered on top.
