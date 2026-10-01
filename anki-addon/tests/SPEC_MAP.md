# Vitest spec → Python test map

Every vitest spec file (30 files, 271 tests) and where its behavior is checked in the add-on. Phase 1a started this map; Phase 1b finished it.

**Statuses:**
- **ported**: a pytest twin per TS `it`, with the TS test name in the docstring.
- **golden**: replayed against recorded TS outputs in `tests/golden/` (written by `tools/export_golden.ts`). A scenario name refers to a scripted session in `session_scenarios.json`, replayed step by step by `tests/engine/test_session_golden.py`: after every action the result, the **full state**, `selectTrial` and the progress/estimate metrics must equal the TS values, and no engine call may change its input.
- **N/A**: web-app UI or `localStorage` behavior the add-on doesn't have, with a reason.

A scenario drives the same deck, config and answers as the `it`, and the golden checks the full state the `it` makes assertions about, so it pins everything the `it` asserts (and more). The scenarios' `covers` lists quote the `it` titles; `tools/export_golden.ts` holds the scripts.

**Golden files:**

| File | Phase | Holds |
|---|---|---|
| `prng.json` | 1a | `hashSeed`, `mulberry32` |
| `jscompat.json` | 1a, 1b | JS built-ins the engine relies on; 1b added `toFixed`, `toISOString`, `.length`, `reduce` sums |
| `grading.json` | 1a | `norm`, `exactMatch`, `computeWordDiff`, `grade` |
| `items.json` | 1a | everything in `items.ts` |
| `session_scenarios.json` | 1b | 100 scripted sessions (1,662 steps, full state after each); pure cases for `history.ts`, `progress.ts`, `estimate.ts`, `orderCycleQueue`, `computeAccuracyPercent`; hand-built edge states |
| `session_sim.json` | 1b | the scoreboard's 450 seeded `simulate()` runs (numbers + trace hash), its decks and config, the `npm run simulate` "Current engine" text, and 37 seeded twins of the spec files' own `simulate()` calls |
| `session_seed0.json` | 1b | seed 0 of each scoreboard config: trial, answer, result and state hash at every step |

## Summary

| # | Spec file | TS tests | Status | Python |
|---|---|---|---|---|
| 1 | `src/test/backup.spec.ts` | 5 | N/A | Web app's JSON backup of its `localStorage` library. The add-on keeps cards in Anki. |
| 2 | `src/test/c1.spec.ts` | 6 | ported (4) + golden (2) | `test_c1_spec.py`; scenarios |
| 3 | `src/test/c2.spec.ts` | 6 | golden | scenarios |
| 4 | `src/test/c3.spec.ts` | 7 | ported (3) + golden (4) | `test_c3_spec.py`; scenarios |
| 5 | `src/test/c4.spec.ts` | 8 | ported (8) + golden | `test_c4_spec.py`; `pure.itemProgress`/`sessionProgress`; progress after every scenario step |
| 6 | `src/test/c5.spec.ts` | 13 | ported (7) + golden (6) | `test_c5_spec.py`; scenarios |
| 7 | `src/test/c8a.spec.ts` | 8 | ported (2) + golden (6) | `test_c8a_spec.py`; scenarios |
| 8 | `src/test/c8b.spec.ts` | 5 | golden (3) + ported (2) | scenarios; `test_simulate_parity.py` |
| 9 | `src/test/chainContiguity.spec.ts` | 4 | golden | scenarios |
| 10 | `src/test/characterization.engine.spec.ts` | 10 | golden | scenarios (the shared suite's 3 walks plus the engine-only 7) |
| 11 | `src/test/characterization.legacy.spec.ts` | 5 | N/A | Tests the frozen `LegacyEngine` reference snapshot (`src/test/reference/`), which the add-on doesn't port. |
| 12 | `src/test/chunkText.spec.ts` | 3 | ported | `test_chunk_text_spec.py`; `items.json` |
| 13 | `src/test/cycleGap.spec.ts` | 1 | golden | scenario |
| 14 | `src/test/cycleOrder.spec.ts` | 10 | ported (3) + golden (7) | `test_cycle_order_spec.py`; scenarios |
| 15 | `src/test/editCurrentItem.spec.ts` | 16 | ported (1) + golden (15) | `test_edit_current_item_spec.py`; scenarios |
| 16 | `src/test/extraField.spec.ts` | 14 | ported (10) + golden (3) + N/A (1) | `test_extra_field_spec.py`; scenarios |
| 17 | `src/test/finalCheck.spec.ts` | 7 | golden | scenarios |
| 18 | `src/test/grade.spec.ts` | 30 | ported | `test_grade_spec.py`; `grading.json` |
| 19 | `src/test/history.spec.ts` | 7 | ported (3) + N/A (4) | `test_history_spec.py`; `pure.historyEntries`/`rankHardestCards` |
| 20 | `src/test/overrideCredit.spec.ts` | 6 | golden | scenario `override-at-every-stage` |
| 21 | `src/test/phantomFolderEntry.spec.ts` | 6 | N/A | Web app's deck index and folders in `localStorage`. |
| 22 | `src/test/preSessionEditPersistence.spec.ts` | 2 | N/A | Web app's deck editor persistence in `localStorage`. |
| 23 | `src/test/repRotation.spec.ts` | 3 | golden | scenarios |
| 24 | `src/test/resumePosition.spec.ts` | 5 | golden | scenarios |
| 25 | `src/test/sessionSource.spec.ts` | 4 | N/A | Writing a mid-session edit back to a saved deck. The add-on never writes note fields (DECISIONS.md, mid-session edit). `resolveSourceDeckEditable` itself is golden (`items.json`). |
| 26 | `src/test/settings.spec.ts` | 3 | N/A | Web app settings in `localStorage`. The add-on uses `config.json`. |
| 27 | `src/test/strictPunctuation.spec.ts` | 34 | ported (28) + golden (3) + N/A (3) | `test_strict_punctuation_spec.py`; scenarios |
| 28 | `src/test/telemetry.spec.ts` | 11 | ported (4) + golden (7) | `test_telemetry_spec.py`; scenarios |
| 29 | `test/coldStartEstimate.consistency.spec.ts` | 28 | ported | `test_simulate_parity.py` (seeded golden runs + the spec's assertion) |
| 30 | `test/simulate.spec.ts` | 4 | ported | `test_simulate_parity.py` (seeded golden runs + the spec's assertions) |

**Totals:** 271 TS tests. 238 are covered (ported, golden, or both) and 33 are N/A. Nothing that exercises engine behavior is left uncovered.

## Not covered, and why

All 33 are web-app storage or UI, which the add-on doesn't have or builds differently:

- `backup.spec.ts` (5), the backup case in `extraField.spec.ts` (1), and the two backup cases in `history.spec.ts`: the web app's JSON export/import of its `localStorage` library. The add-on's cards live in Anki.
- `characterization.legacy.spec.ts` (5): tests the frozen pre-Phase-1 `LegacyEngine` snapshot, which is a TS-side reference only.
- `phantomFolderEntry.spec.ts` (6), `preSessionEditPersistence.spec.ts` (2), `settings.spec.ts` (3), and the 3 deck-index cases in `strictPunctuation.spec.ts`: the deck index, folders, deck editor and settings in `localStorage`.
- The two other `history.spec.ts` storage cases (append/trim, delete with deck): `localStorage` history. The add-on's history storage is Phase 3a; `buildHistoryEntry` and `rankHardestCards`, which build what it stores, are ported and golden.
- `sessionSource.spec.ts` (4): writing a mid-session edit back to the saved deck. The add-on never writes note fields.

Partly covered: `resumePosition.spec.ts` "currentId survives the storage round-trip" is checked through the add-on's save shape (every `save-resume` step records the saved JSON, `currentId` included); the `localStorage` call it makes is N/A.

## Beyond the specs

The golden data also checks behavior no vitest `it` pins, all listed in the scenarios' `covers`:
- A reveal at every stage (chunk presentation and blind attempt, combine, remediate at depth 1 and 2, full, cycle, final) and an override after a wrong answer at every stage, including remediation retries and splits.
- Deep remediation: a ≤ 2-chunk window remediating on the first miss, a > 2-chunk window on the second, two culprit spots, recursive halving to depth 3, and one-word pieces that never split.
- Save and resume mid-encode, mid-remediation, mid-cycle, at batch-done and mid-final, plus old save shapes (no `currentId`, telemetry, `finalDone`/`finalMisses`, `stats.reveals`, `finalCheckStartAttempts`, settings fields, or `batchIndex`/`batchSize`/`batchStartStats`; a pre-C8a `chunkStreak`; a remediate card with an empty stack).
- Config variety: `batchSize` 0/3/5, `cycleOrder` both ways, `ladderMode` exhaustive, `encodeReps` 1/2/3/5/8, `chunkDifficulty` 15/20/35/50/100, `minWordsToChunk` 3, `buildItems` with and without the within-batch shuffle, an empty deck.
- Edits: restart with an Extra note, an edit with a pending "Count as correct" (SessionView applies the edit to the pre-answer state), and edits in cycle and final.
- `computeBatchSummary`, `computeAccuracyPercent`, `computeSessionProgress`, `computeCumulativeColdStartMultiplier` and `computeRemainingColdStartRange` at recorded steps; `computeColdStartEstimate` for every scenario deck at every exposure level; `buildHistoryEntry` and `rankHardestCards` at session ends.

## Per-test detail (Phase 1b files)

Files that were already fully ported in Phase 1a (`chunkText`, `grade`) and the N/A files are in the summary only.

### `src/test/c1.spec.ts`

| `it(...)` | Covered by |
|---|---|
| cumulative (forward chaining): n-1 growing-prefix windows | ported: `test_c1_spec.py` (Phase 1a) |
| exhaustive: n(n-1)/2 windows, unchanged from the original ladder | ported: `test_c1_spec.py` (Phase 1a) |
| defaults to cumulative when no mode is given | ported: `test_c1_spec.py` (Phase 1a) |
| requires just 1 rep for every window except the final (whole-answer) one | ported: `test_c1_spec.py` (Phase 1a) |
| 4-chunk answer, encodeReps=3: 8 chunk trials (4 presented + 4 blind, C8a/C8b) + (1+1+3) combine + 2 cycle = 15 trials, 11 counted attempts, 0 misses | golden `c1-e2e-four-chunk-reps-3` |
| a genuinely wrong combine answer on the final window still enters remediate and B1 attributes correctly | golden `remediation-exhaustive-b1`, `c1-remediation-cumulative` |

### `src/test/c2.spec.ts`

| `it(...)` | Covered by |
|---|---|
| dropping a stopword from an otherwise-exact long answer counts as near and advances the streak | golden `c2-near-stopword-full` |
| a plural-only difference on a long answer counts as near when stemTolerance is on | golden `c2-near-stem-on` |
| the same plural difference counts as wrong when stemTolerance is off | golden `c2-near-stem-off` |
| a near-miss in the cycle phase advances cycleStreak and does not increment misses | golden `c2-near-cycle` |
| override does not double-count the attempt, decrements nothing (miss was never committed), and increments overrides | golden `c2-override-direct` |
| override on the final rep of a stage-unit advances the item exactly like a genuine correct answer | golden `c2-override-final-rep` |

### `src/test/c3.spec.ts`

| `it(...)` | Covered by |
|---|---|
| a 13-card deck at batchSize 5 produces batches of 5/5/3 | ported: `test_c3_spec.py` (Phase 1a) |
| batchSize 0 (or omitted) is a single whole-deck batch | ported: `test_c3_spec.py` (Phase 1a); golden `config-batch-0` |
| round-robins over not-yet-ready items, skipping ready ones | ported: `test_c3_spec.py` (Phase 1a) |
| visits more than one distinct item before the first item reaches ready | golden `c3-interleave-five-chunked` |
| is fully massed (one item at a time) when there is only a single item -- batching never changes single-item behavior | golden `c3-single-item-massed` |
| round-tripping through a SavedSessionState-shaped save reproduces the interstitial exactly | golden `resume-batch-done` |
| migrates a pre-C3 save (no batchIndex/batchSize) to batchIndex 0, batchSize items.length | golden `resume-batch-done` |

### `src/test/c4.spec.ts`

| `it(...)` | Covered by |
|---|---|
| new is 0, ready is 0.7, mastered is 1.0 | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| encoding: chunk progress falls strictly between 0 and 0.7 and grows with chunkIndex/chunkStreak | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| encoding: chunk progress is independent of encodeReps (C8a fixed the chunk criterion at 1 cued + 1 blind) | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| encoding: combine-stage progress picks up where the chunks left off (all chunks pre-credited) | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| encoding: remediate holds progress flat at the combine window it interrupted (doesn't dip) | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| deckFraction averages every item; batchFraction averages only the given subset | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| defaults batch to the full item list when omitted (matches the doc's 2-arg signature) | ported: `test_c4_spec.py`; golden `pure.itemProgress` / `pure.sessionProgress` |
| never decreases, starts > 0 after the first correct chunk, and reaches exactly 1.0 only once every item is mastered | ported: `test_c4_spec.py`; golden `c4-progress-perfect-session` |

### `src/test/c5.spec.ts`

| `it(...)` | Covered by |
|---|---|
| keeps the first character of each word and underscores the rest, preserving word count | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| leaves punctuation visible in place, only underscoring letters/digits | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| leaves a one-character word as-is | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| preserves the first character's original case | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| reveals the first alphanumeric character of each run, even mid-word after punctuation | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| reveals the first alphanumeric of each run for medical word parts led/trailed by punctuation | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| degenerate case: a single alphanumeric character after punctuation is left fully revealed | ported: `test_c5_spec.py`; golden `items.json` `targets` (Phase 1a) |
| full stage: firstLetter cue on the first attempt, none once a streak starts | golden `c5-full-stage-cue` |
| chunks stage: each chunk starts with a presentation, not firstLetter (C8b) | golden `c5-chunks-presentation-cue` |
| cycle stage: always fully blind, same as before C5 (no copy-typing attempt existed there) | golden `c5-cycle-blind` |
| chunks/combine/full misses return advance: manual instead of auto-retrying on a timer | golden `c5-full-stage-cue` |
| an exact answer still auto-advances (only wrong verdicts became manual) | golden `c5-full-stage-cue` |
| walking a full session (chunks -> combine -> cycle) never yields a graded cue that reveals the full text pre-attempt | golden `c5-no-graded-full-cue` |

### `src/test/c8a.spec.ts`

| `it(...)` | Covered by |
|---|---|
| a chunk needs exactly 1 cued + 1 blind at encodeReps=1 > does not advance on the cued attempt alone, and does not need more than one blind success | golden `c8a-chunk-cued-plus-blind-reps-1`, `c8a-chunk-cued-plus-blind-reps-2`, `c8a-chunk-cued-plus-blind-reps-3`, `c8a-chunk-cued-plus-blind-reps-5` |
| a chunk needs exactly 1 cued + 1 blind at encodeReps=2 > does not advance on the cued attempt alone, and does not need more than one blind success | golden `c8a-chunk-cued-plus-blind-reps-1`, `c8a-chunk-cued-plus-blind-reps-2`, `c8a-chunk-cued-plus-blind-reps-3`, `c8a-chunk-cued-plus-blind-reps-5` |
| a chunk needs exactly 1 cued + 1 blind at encodeReps=3 > does not advance on the cued attempt alone, and does not need more than one blind success | golden `c8a-chunk-cued-plus-blind-reps-1`, `c8a-chunk-cued-plus-blind-reps-2`, `c8a-chunk-cued-plus-blind-reps-3`, `c8a-chunk-cued-plus-blind-reps-5` |
| a chunk needs exactly 1 cued + 1 blind at encodeReps=5 > does not advance on the cued attempt alone, and does not need more than one blind success | golden `c8a-chunk-cued-plus-blind-reps-1`, `c8a-chunk-cued-plus-blind-reps-2`, `c8a-chunk-cued-plus-blind-reps-3`, `c8a-chunk-cued-plus-blind-reps-5` |
| the full stage still needs encodeReps consecutive blind successes | golden `c8a-full-stage-reps-3` |
| the final combine window still needs encodeReps consecutive blind successes | golden `c1-e2e-four-chunk-reps-3` |
| clamps a legacy mid-chunk chunkStreak (accumulated under the old encodeReps-per-chunk rule) down to 1 | ported: `test_c8a_spec.py` (Phase 1a); also through a resume in `resume-pre-c8a-and-empty-remediation` |
| leaves a valid {0, 1} chunkStreak untouched | ported: `test_c8a_spec.py` (Phase 1a) |

### `src/test/c8b.spec.ts`

| `it(...)` | Covered by |
|---|---|
| cue is { kind: "present" } with no payload -- the text to show is Trial.target | golden `c8b-presentation-0`, `c8b-presentation-1`, `c8b-presentation-2` |
| advances chunkStreak from 0 to 1 regardless of what is "typed", never counts as an attempt or a miss | golden `c8b-presentation-0`, `c8b-presentation-1`, `c8b-presentation-2` |
| the subsequent blind attempt (chunkStreak 1) is the first one that can actually be wrong | golden `c8b-presentation-0` |
| trialsByStage.chunks counts both the presentation and the blind attempt for each chunk | ported: `test_simulate_parity.py::test_presentations_count_as_trials_but_not_keystrokes` (golden run `c8b:twoChunk`) |
| simulate()'s total keystrokes exactly match a hand-walked session that skips presentation trials | ported: `test_simulate_parity.py::test_presentations_count_as_trials_but_not_keystrokes` (against the `c5-no-graded-full-cue` walk) |

### `src/test/chainContiguity.spec.ts`

| `it(...)` | Covered by |
|---|---|
| cumulative ladder: chunks and intermediate windows run back to back, then the final window rotates | golden `chain-contiguity-cumulative` |
| exhaustive ladder: short-of-criterion reps on intermediate windows stay on the card too | golden `config-exhaustive-reps-2`, `chain-contiguity-exhaustive` |
| remediation stays on the card and contiguity holds up to the final window | golden `chain-contiguity-remediation` |
| full-stage only: consecutive graded trials alternate cards while more than one is encoding (Phase 2 unchanged) | golden `chain-contiguity-full-stage-only` |

### `src/test/characterization.engine.spec.ts`

| `it(...)` | Covered by |
|---|---|
| walks the exact (stage,target,streak,status) sequence | golden `characterization-full-stage-walk` |
| walks the exact (stage,target,streak,status) sequence, correctly attributing the miss to only the culprit chunk (post-B1-fix) | golden `characterization-two-chunk-walk` |
| walks miss -> correct -> correct -> mastered | golden `characterization-cycle-walk` |
| one shuffled Final-check trial over the single item, then the session finishes | golden `characterization-full-stage-walk` |
| flags only the chunks that actually mismatch, not the whole window (B1 fixed) | golden `remediation-exhaustive-b1` |
| a remediate-stage answer leaves the original state.items entry untouched | golden `characterization-purity-remediate` |
| encode phase: reveal then type the now-visible answer correctly -- streak resets, no miss counted | golden `characterization-b2-encode` |
| encode phase: reveal then type something wrong -- still resets to 0, still no miss counted | golden `characterization-b2-encode` |
| combine stage: reveal resets combineStreak, not combineMissCount | golden `characterization-b2-combine` |
| cycle phase: reveal resets cycleStreak, reinserts into queue, no miss counted, still manual advance | golden `characterization-b2-cycle` |

### `src/test/cycleGap.spec.ts`

| `it(...)` | Covered by |
|---|---|
| every first-correct card is not served again until every other queued card has been served (perfect learner) | golden `cycle-gap-shuffled` |

### `src/test/cycleOrder.spec.ts`

| `it(...)` | Covered by |
|---|---|
| inOrder sorts ids ascending without mutating the input | ported: `test_cycle_order_spec.py`; golden `pure.orderCycleQueue` |
| shuffled (and default) returns a permutation of the same ids | ported: `test_cycle_order_spec.py`; golden `pure.orderCycleQueue` |
| a perfect run is two full passes in deck order | golden `cycle-order-inorder-perfect` |
| a miss does not break order: the card returns on the next pass | golden `cycle-order-inorder-miss` |
| a revealed answer also waits for the next pass | golden `reveal-inorder-cycle-and-final`, `cycle-order-inorder-reveal` |
| is scoped to the current batch | golden `config-batch-3-inorder`, `cycle-order-inorder-batch-scope` |
| cycleOrder=shuffled: a first correct is reinserted into the current pass | golden `cycle-order-shuffled-first-correct` |
| cycleOrder=undefined: a first correct is reinserted into the current pass | golden `cycle-order-undefined-first-correct` |
| keeps deck order and the first encode trial is the first card | golden `cycle-order-encode-deck-order` |
| default (no flag) still shuffles within batches, for the harness | ported: `test_cycle_order_spec.py` (Phase 1a) |

### `src/test/editCurrentItem.spec.ts`

| `it(...)` | Covered by |
|---|---|
| a prompt-only edit keeps every progress field | golden `edit-prompt-only` |
| an equivalent answer edit on a normal deck keeps progress (Menieres -> Ménière's) | golden `edit-equivalent-answer` |
| an equivalent edit with the same chunk count swaps in the new chunk text | golden `edit-same-chunk-count` |
| a prompt-only edit keeps stored chunks even when chunkText would now produce different ones | golden `edit-legacy-chunks-prompt-only` |
| trims both fields | golden `edit-trims-and-noop-empty` |
| 'pre op' -> 'pre-op' keeps progress on a normal deck | golden `edit-pre-op-normal` |
| 'pre op' -> 'pre-op' restarts on a strict deck | golden `edit-pre-op-strict` |
| a real answer change mid-combine fully resets the item and nothing else | golden `edit-restart-mid-combine` |
| an equivalent edit that changes the chunk count restarts | golden `edit-chunk-count-change` |
| an equivalent edit during 'remediate' restarts | golden `edit-during-remediate` |
| a real answer change in cycle (inOrder) goes back to encode and never re-serves mastered cards | golden `edit-restart-from-cycle-inOrder` |
| a real answer change in cycle (shuffled) goes back to encode and never re-serves mastered cards | golden `edit-restart-from-cycle-shuffled` |
| does not mutate a deep-frozen input, on either path, in either phase | golden `edit-cycle-prompt-only-and-final-noop` |
| is a no-op on 'batch-done' | golden `edit-noop-batch-done` |
| is a no-op on an empty front or back | golden `edit-trims-and-noop-empty` |
| never picks a mastered item, from the front or mid-rotation | ported: `test_edit_current_item_spec.py` (Phase 1a) |

### `src/test/extraField.spec.ts`

| `it(...)` | Covered by |
|---|---|
| a three-field tab line produces front/back/extra | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| a two-field tab line produces no extra key at all | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| a three-field :: line produces front/back/extra | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| a two-field :: line produces no extra key | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| a fourth tab segment folds into extra, not dropped | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| an all-whitespace third segment is trimmed away to no extra | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| comment and blank lines are still skipped, extra or not | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| a card with extra carries it onto the built DrillItem | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| a no-extra card is byte-identical to before extra existed | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| normalizeItem reads extra from a saved item, undefined-safe | ported: `test_extra_field_spec.py`; golden `items.json` (Phase 1a) |
| keeps every progress field and the chunk array (strictPunctuation=false) | golden `edit-extra-only-strict-false` |
| keeps every progress field and the chunk array (strictPunctuation=true) | golden `edit-extra-only-strict-true` |
| extra never influences whether the answer counted as changed | golden `edit-extra-never-changes-answer` |
| round-trips extra through export -> wipe -> import | N/A: the web app's backup |

### `src/test/finalCheck.spec.ts`

| `it(...)` | Covered by |
|---|---|
| a shuffled, cue-free pass serves each item exactly once, then the session completes | golden `final-check-perfect-six` |
| the "k of N" counter reads N of N right after the last card's correct answer, before Continue is clicked | golden `final-check-counter` |
| a wrong answer comes back only after every other pending card, and the session waits for it | golden `final-check-miss-requeue` |
| increments finalMisses, leaves stats.misses alone, and requeues to the end | golden `final-check-reveal` |
| a mid-Final-check resume preserves finalDone and still tests the card that was in flight at save time | golden `resume-mid-final` |
| an old save with no finalDone/finalMisses on any item resumes fine | golden `resume-old-save-shapes` |
| reads exactly 1 for a perfect learner throughout -- at the start of the Final check, partway through it, and once it completes | golden `final-check-multiplier` |

### `src/test/history.spec.ts`

| `it(...)` | Covered by |
|---|---|
| records each card with its length, chunking, and cost | ported: `test_history_spec.py`; golden `pure.historyEntries` |
| orders by misses + reveals + final-check misses, then attempts, then deck order | ported: `test_history_spec.py`; golden `pure.rankHardestCards` |
| leaves out cards with no trouble, and respects the limit | ported: `test_history_spec.py`; golden `pure.rankHardestCards` |
| appends per deck and keeps only the newest entries | N/A: `localStorage` history (add-on storage is Phase 3a) |
| is deleted with its deck | N/A: `localStorage` history |
| round-trips through a backup export and replace-import | N/A: the web app's backup |
| imports a backup made before history existed | N/A: the web app's backup |

### `src/test/overrideCredit.spec.ts`

| `it(...)` | Covered by |
|---|---|
| full-stage card, 2nd rep | golden `override-at-every-stage` |
| chunk, blind attempt | golden `override-at-every-stage` |
| first 2-part combination (a miss would isolate) | golden `override-at-every-stage` |
| whole-answer window, 2nd rep | golden `override-at-every-stage` |
| review, the answer that would master | golden `override-at-every-stage` |
| final check | golden `override-at-every-stage` |

### `src/test/repRotation.spec.ts`

| `it(...)` | Covered by |
|---|---|
| no two consecutive graded encode trials are on the same card while more than one card is still encoding | golden `rep-rotation-full-stage` |
| a wrong answer serves the same card next | golden `rep-rotation-full-stage` |
| a presentation trial and its blind attempt stay adjacent, and final-window reps rotate while another card is still encoding | golden `rep-rotation-presentation-adjacent` |

### `src/test/resumePosition.spec.ts`

| `it(...)` | Covered by |
|---|---|
| resumes a mid-remediation card on the same card and piece | golden `resume-mid-remediation` |
| resumes a mid-chunks card on the same chunk | golden `resume-mid-chunks` |
| falls back to rotation when the saved card is no longer unfinished | golden `resume-fallback-rotation` |
| a fresh start is unchanged: first card in deck order | golden `resume-fallback-rotation` |
| currentId survives the storage round-trip | golden `resume-mid-chunks` |

### `src/test/strictPunctuation.spec.ts`

| `it(...)` | Covered by |
|---|---|
| strict: "tachycardia fast heart rate" vs "tachycardia (fast heart rate)" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "the fight or flight response" vs "the "fight or flight" response" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "normal range 7.35-7.45" vs "normal range: 7.35-7.45" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "heart lungs kidneys" vs "heart, lungs, kidneys" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "the end" vs "The end." -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "dont" vs "don’t" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "pre-op" vs "pre—op" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "Menieres disease" vs "Ménière’s disease" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "Menière" vs "Menière" -> exact | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "tachycardia" vs "tachycardia (fast heart rate)" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "inflammation of stomach" vs "inflammation of the stomach" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "inflammation of the joint" vs "inflammation of the joints" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "pre op" vs "pre-op" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "and or" vs "and/or" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "74" vs "7.4" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "Na" vs "Na+" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict: "5" vs "-5" -> wrong | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "pre op" vs "pre-op" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "and or" vs "and/or" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "10 mg" vs "10mg" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "Na +" vs "Na+" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "5 %" vs "5%" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "itis" vs "-itis" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "dont" vs "don't" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "tachycardia fast heart rate" vs "tachycardia (fast heart rate)" -> exact (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "74" vs "7.4" -> wrong (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "Na" vs "Na+" -> wrong (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strict off: "5" vs "-5" -> wrong (unchanged from Phase 1) | ported: `test_strict_punctuation_spec.py`; golden `grading.json` (Phase 1a) |
| strictPunctuation: true grades a dropped-stopword difference wrong (near-miss tier disabled) | golden `strict-stopword-wrong` |
| strictPunctuation: false grades the same difference near (stopword forgiveness applies) | golden `strict-off-near` |
| an old config with strictPunctuation undefined (pre-Phase-2 session) behaves like false | golden `strict-undefined-near` |
| a deck saved with strictPunctuation: true round-trips through the deck index | N/A: deck index in `localStorage` |
| a deck saved without the strictPunctuation arg defaults to false | N/A: deck index in `localStorage` |
| an old deck-index entry saved before this field existed loads as strict = false | N/A: deck index in `localStorage` |

### `src/test/telemetry.spec.ts`

| `it(...)` | Covered by |
|---|---|
| counts a correct answer as an attempt on that card only | golden `telemetry-answers` |
| records a wrong answer as a miss on the card | golden `telemetry-answers` |
| records a reveal on the card and in stats.reveals, never as a miss | golden `telemetry-answers` |
| records a near-miss | golden `telemetry-answers` |
| does not count a chunk presentation | golden `telemetry-presentation-and-hard-span` |
| records the chunk that broke while combining as a hard span | golden `telemetry-presentation-and-hard-span` |
| survives normalizeItem (a save/resume round trip) | golden `resume-old-save-shapes` |
| excludes reveals from the correct count | ported: `test_telemetry_spec.py`; golden `pure.accuracy` |
| treats a missing reveals field (an old save) as 0 | ported: `test_telemetry_spec.py`; golden `pure.accuracy` |
| reads 100 with no attempts and never goes negative | ported: `test_telemetry_spec.py`; golden `pure.accuracy` |
| is what the batch summary reports | ported: `test_telemetry_spec.py`; golden `telemetry-answers` |

### `test/coldStartEstimate.consistency.spec.ts`

| `it(...)` | Covered by |
|---|---|
| shortDeck, encodeReps=1, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| shortDeck, encodeReps=1, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| shortDeck, encodeReps=3, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| shortDeck, encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| shortDeck, encodeReps=5, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| shortDeck, encodeReps=5, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mediumDeck, encodeReps=1, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mediumDeck, encodeReps=1, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mediumDeck, encodeReps=3, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mediumDeck, encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mediumDeck, encodeReps=5, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mediumDeck, encodeReps=5, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| proseDeck, encodeReps=1, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| proseDeck, encodeReps=1, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| proseDeck, encodeReps=3, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| proseDeck, encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| proseDeck, encodeReps=5, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| proseDeck, encodeReps=5, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=1, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=1, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=3, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=5, minWordsToChunk=3 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=5, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency:...`) |
| shortDeck, encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency-inOrder:...`) |
| mediumDeck, encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency-inOrder:...`) |
| proseDeck, encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency-inOrder:...`) |
| mixedDeck (chunked + full-stage cards), encodeReps=3, minWordsToChunk=8 | ported: `test_simulate_parity.py::test_minimum_trials_matches_a_perfect_session` (golden run `consistency-inOrder:...`) |

### `test/simulate.spec.ts`

| `it(...)` | Covered by |
|---|---|
| runs a nonzero number of trials for every learner/deck combination | ported: `test_simulate_parity.py::test_extra_run_matches_ts_exactly` (golden runs `simulate:*`) |
| reports trialsByStage keys that are valid stage names | ported: `test_simulate_parity.py::test_extra_run_matches_ts_exactly` |
| a struggling learner never needs fewer trials than a perfect one on the same deck | ported: `test_simulate_parity.py::test_struggling_never_needs_fewer_trials_than_perfect` |
| cumulative ladder gives >=40% trial-count reduction vs exhaustive once cards average >=4 chunks (perfect learner) | ported: `test_simulate_parity.py::test_cumulative_ladder_cuts_trials_by_40_percent` |

