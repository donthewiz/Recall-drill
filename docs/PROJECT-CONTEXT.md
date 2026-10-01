# Recall Drill: project context (as of 2026-10-01)

Upload this to the Claude project as current context. It replaces older summaries. `docs/V2-HANDOFF.md` is the design history: why things are the way they are.

- Repo: https://github.com/donthewiz/Recall-drill
- Branch: `main` only. Local `v2` and `ai-studio-sandbox` (also on origin) have nothing that isn't already on `main`.
- Owner: Don

---

## 1. What the app is

Recall Drill is a **session-only typed-recall drill** for prose and terminology flashcards. It gets a deck to "encoded well enough to hand to Anki" in one sitting. **Anki owns long-term retention.** Don's main use is medical terminology: HR105 chapter decks, built by the `medterm-daily-drill` and `medical-terminology-recall-drill` skills, then reviewed in Anki.

### Settled scope (don't relitigate)

- **No scheduler.** No due dates, intervals, FSRS or cross-session decay.
- **Fewer trials is the top priority.** Every trial past the encoding bar gets paid for again in Anki.
- **Typed free recall stays the only response mode.** No multiple choice. The dropped C7 rung was the one exception ever considered.
- **Dropped, not deferred:** C6 (Anki TSV export) and C7 (multiple-choice rung).
- **Leave alone:**
  - The remediation design (recursive halving down to the failing span)
  - The `chunkDifficulty` percentage model
  - Deck and folder management
  - Clearing the saved session on completion

## 2. Stack and commands

- React 19, TypeScript 7, Vite 8, Tailwind 4, lucide-react, vite-plugin-pwa (works fully offline).
- 100% client-side: all data lives in `localStorage`. No server and no API keys.
- Vitest 5.

| Command | What it does |
|---|---|
| `npm run dev` | Dev server on port 3000 (`.claude/launch.json` has "Recall-drill dev") |
| `npm run lint` | `tsc --noEmit` |
| `npm test` | 271 tests, about 3–4s. Default env is node; specs touching localStorage start with `// @vitest-environment jsdom` |
| `npm run build` | Production build |
| `npm run simulate` | Trial-count scoreboard (`test/simulate*.ts`): 50 seeded runs × 3 decks × 3 learner models, mean ± SD. Deterministic. **Any engine change must report this before and after.** `docs/BASELINE.md` keeps the history. |

- **CI:** `.github/workflows/ci.yml` runs lint, test and build on pushes to `main` and on PRs. First run passed on 2026-09-30.
- The `gh` CLI is **not installed** on Don's machine. Open PRs via the GitHub web page.

## 3. Code map

`src/utils/drillEngine.ts` is a **barrel**: it re-exports the modules below. Import from it or from a module directly.

| File | Role |
|---|---|
| `utils/grading.ts` | `norm`, `exactMatch`, LCS `computeWordDiff`, `grade()` (exact / near / wrong) |
| `utils/items.ts` | `parseDeck`, `chunkText` (`MIN_WORDS_TO_CHUNK = 8`), `renderFirstLetterCue`, `buildCombineSequence`, `findAllCulpritChunks`, `buildItems`/`buildItem`, `normalizeItem` (migrates old saves) |
| `utils/session.ts` | The pure state machine: `initSession`, `selectTrial`, `applyAnswer`, `applyNext`, `editCurrentItem`, batch/cycle/final transitions, `emptyStats`, `computeAccuracyPercent`, `computeBatchSummary`, `DWELL_MS` |
| `utils/storage.ts` | localStorage helpers (`lsGet`/`lsSet`/`lsDelete`), deck index, folders, saved sessions, `writeBackCardEdit` |
| `utils/history.ts` | Per-deck session history and `rankHardestCards` |
| `utils/estimate.ts` | Cold-start time estimate and its recalibration |
| `utils/progress.ts` | Progress-bar math (C4) |
| `utils/settings.ts` | Typed `readSetting`/`writeSetting` for the global setup defaults |
| `utils/backup.ts` | JSON export/import (merge or replace), persistent-storage request |
| `App.tsx` | View routing and session lifecycle (start, resume, finish, drill-again, restart) |
| `components/SessionView.tsx` | Renders `selectTrial`, calls `applyAnswer`, handles feedback/dwell, override snapshot (`preWrongStateRef`), mid-session card edit |
| `components/SetupView.tsx` + `setup/` | Deck editor and resume prompt; `SessionSettings`, `ColdStartEstimatePanel` |
| `components/DecksView.tsx` + `decks/` | Library, folders, drag and drop, backup. Dialogs live on a shared `ModalShell` |
| `components/DoneView.tsx` | End screen: stats, "Where you struggled", Final-check misses, "Drill these cards again" |
| `components/HelpModal.tsx` | User-facing method explanation (4 sections) |

## 4. How a session works (shipped behavior)

**Phases.** Cards are split into **batches in deck order** (default 5; 3–10, or 0 = whole deck). Each batch runs:

1. **encode**
2. **cycle**
3. a **batch-done** summary screen ("Next batch" / "Save and stop")

After the last batch comes a **Final check**: one shuffled, cue-free pass over every card in the session.

**Encode ladder, per card:**
- **Short answers (≤ 8 words, or difficulty 100%)** use the `full` stage:
  - attempt 0 shows a first-letter cue (`T__ h____ …`)
  - then it needs `encodeReps` (default 3) consecutive blind correct answers
- **Longer answers are chunked:**
  - Each chunk is shown once (an ungraded presentation), then needs one blind correct answer.
  - Then forward chaining: windows 1–2, 1–3, …, 1–n.
  - Intermediate windows need 1 correct answer; the whole-answer window needs `encodeReps`.
  - A chunked card stays on screen until its whole answer is assembled. Rotation to other cards resumes after the final window.
- **Remediation:**
  - A combine miss triggers it: immediately for windows of 2 or fewer chunks, otherwise on the 2nd miss.
  - LCS alignment finds the culprit chunks, which are drilled.
  - After 2 further misses, the culprit is halved recursively.

**Cycle:**
- A card is mastered at 2 correct in a row.
- Shuffled mode: the first correct answer sends the card to the end of the pass; a miss or reveal brings it back 2–3 cards later.
- An "in order" mode also exists.

**Final check:**
- Each card needs one correct answer.
- A miss or reveal sends it to the end of the pass and counts toward `finalMisses`.
- The session is complete, and its save cleared, only when every card is `finalDone`.

**Grading:**
- **`exact`:** matches after normalization (case and meaningless punctuation forgiven).
- **`near`:** the only differences are stopwords, or similarity ≥ 0.9 with light-stem differences. Stem tolerance is a setting; turn it **off** for terminology decks.
- **Strict punctuation** is a per-deck setting and disables `near`.
- **Wrong answers** wait for Enter/Continue. "Count as correct" (Ctrl+Enter) re-applies the trial to the state from before the wrong answer.

**Reveal ("Show target" / Esc):**
- Resets that part's streak.
- Counts as an attempt but never as a miss.
- Since 2026-09-30, it's tracked in `stats.reveals` and **subtracted from accuracy**.

**Accuracy** = (attempts − misses − reveals) / attempts.

## 5. Data (localStorage keys)

| Key | Contents |
|---|---|
| `deck-index` | `SavedDeckEntry[]` (includes per-deck `strictPunctuation`) |
| `deck-folders` | Folder tree |
| `deck:<slug>` | Cards: `{front, back, extra?}` |
| `session:<slug>` | `SavedSessionState` (in-progress session, written every trial) |
| `session-history:<slug>` | `SessionHistoryEntry[]` (new, capped at 50) |
| `cold-start-history:<slug>` | Estimate multiplier from the last session |
| `recall_drill_*` | Global defaults: `encode_reps` 3, `chunk_difficulty` 35, `batch_size` 5, `stem_tolerance` true, `ladder_mode` cumulative, `cycle_order` shuffled, `theme`; plus `last_export`, `premade` |

Backups (`schemaVersion` 1) contain folders plus each deck's items, saved session and `history`.

## 6. What changed on 2026-09-30 (4 commits on `main`, CI green)

1. **Cleanup** (`3eb8d7c`):
   - Removed AI Studio leftovers: Gemini/express/dotenv deps, `.env.example`, `DISABLE_HMR`, the `@` alias.
   - Removed unused packages (motion, testing-library and others).
   - Renamed the package to `recall-drill`.
2. **Tests and CI** (`1fe9f53`): node test environment by default (~29s → ~3s); GitHub Actions workflow.
3. **Refactor** (`f2790bf`, no behavior change; simulate output identical):
   - Split the engine into the modules above.
   - Added `settings.ts`.
   - Moved DecksView's dialogs and SetupView's settings/estimate panels into subcomponents.
4. **Features** (`3170e8e`):
   - **Per-card telemetry** on `DrillItem`: `attempts`, `misses`, `reveals`, `nearMisses`, `hardSpans`. One wrapper (`recordTrialTelemetry`) inside `applyAnswer` records them. `hardSpans` keeps the narrowest remediated spans.
   - **Session history**, written in `App.handleFinishSession` on completion for saved decks only. Each card records `words`, `chunks`, attempts, misses, reveals, `finalMisses` and `hardSpans`.
   - **Done screen:** honest accuracy line, "Where you struggled" (top 5 by misses + reveals + finalMisses), and "Drill these cards again" for the Final-check misses.
   - **Fix:** "Practice again" no longer drops the Extra field.

## 7. Decisions worth knowing

- A "Count as correct" override counts as an attempt on the **card** (so the card's state matches a typed correct answer) but **not** in session `stats.attempts`. That matches the original C2 spec.
- **History is written only for completed sessions on saved decks.**
  - Folder practice and drill-again sessions aren't logged: they have no deck-index entry.
  - A session started from the editor without "Save deck" still logs under its slug.
- **Drill-again** runs like folder practice: session-only, named "<deck> (missed cards)", and mid-session edits don't save back to the deck.
- **Mid-session edits:** an edit that changes the answer restarts the card and resets its telemetry.
- `MIN_WORDS_TO_CHUNK = 8` was tuned on a synthetic fixture. The plan is to retune it from real `session-history` data.

## 8. Open items and next steps

- **Retune `MIN_WORDS_TO_CHUNK`** once a few real decks have history. Group cards by `words` and `chunks` and compare misses and attempts. Get the data with "Export all decks" (the JSON includes history).
- **Measure the spacing work in Anki:** compare the next-day Again rate for drilled cards against undrilled ones. The Anki MCP connector is available. This was the stated success metric for the 2026-09-24 spacing changes.
- `HelpModal` doesn't mention the reveal/accuracy change or the done-screen review features.
- An abandoned drill-again or folder session leaves a `session:<name>` key behind (pre-existing pattern).
- `docs/SMOKE.md` §10 (new features) hasn't been run by hand on a real deck yet.

## 9. Conventions

- **Commits:**
  - Conventional style (`feat(engine):`, `fix(session):`, `refactor:`, `chore:`, `test:`, `docs:`), one logical change per commit.
  - Each commit must typecheck and pass tests on its own.
  - Engine changes quote the simulate delta.
- **Work order:**
  - Characterize, then change.
  - The engine stays pure (no React, no timers, no mutation); `SessionView` is a thin shell.
  - New saved-state fields are optional and migrated in `normalizeItem` or on resume.
- **Docs:** `V2-HANDOFF.md` records "as shipped" notes wherever behavior differs from the spec. `BASELINE.md` is the scoreboard. `SMOKE.md` is the manual release checklist.
- Don works on Windows. The repo uses LF (`.gitattributes`).
