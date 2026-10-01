# Recall Drill add-on: decisions

Phase 0 (2026-10-01). The design spec is the Claude-project doc
`recall-drill-anki-addon-handoff.md` and its index
`recall-drill-anki-addon-prompts-index.md`. This file records what is actually
true on Don's Anki, and the decisions taken (or pending) on top of the spec.

## Scope

**The add-on serves all of Don's decks, not just Med Term** (Don, 2026-10-01). That includes the cloze decks built by the `anki-cards` skill, which carry:
- `rd::drill::A` / `rd::drill::A1` / `rd::drill::B` tags;
- `Layer::N` ordering;
- long HTML Extra fields;
- red-flag repair cards.

Nothing may assume Med Term's shape (Basic and Reverse, short answers).

**Tag namespace (checked on 26.08.1):** the skill's `rd::drill::*` tags and the handoff tag `rd::drilled` share the `rd::` prefix.
- `tag:rd::drill` matches only the skill's tags (a tag and its children; no prefix match).
- `tag:rd::drill*` and `tag:rd::*` match **both**.
- Add-on searches must use exact tag names, never a wildcard over `rd::`.

## Versions

| What | Value |
|---|---|
| Anki | 26.08.1 (39e4b0b4), Qt 6.11.0, Chromium 140. Frozen Windows build in `%LOCALAPPDATA%\Programs\Anki` |
| Anki's bundled Python | 3.13.13 (MSC v.1944, 64-bit) |
| `min_point_version` | **260801**. Anki's `anki.utils.int_version()` is `YYMMPP`: 26.08.1 → 260801 |
| Dev venv Python | 3.13.5 (uv-managed CPython already on disk, `%APPDATA%\uv\python\cpython-3.13.5-windows-x86_64-none`) |
| Pinned `anki` / `aqt` | 26.8.1 / 26.8.1 from PyPI (same build as Don's install) |
| FSRS in the Med Term preset | on |

**The venv's patch version differs (3.13.5 vs 3.13.13), and that's safe.** Same minor version, so the same language, stdlib API and bytecode. The add-on ships source only, with no compiled extensions. ruff `target-version = "py313"` and pyright `pythonVersion = "3.13"` hold the code to 3.13. No 3.13 *patch* release adds language features.

**The spec's pre-check versus Don's version:** the pre-check ran on `anki` 26.9.3, which is *newer* than Don's 26.08.1. Every fact below was re-run on 26.08.1. The A/B optimizer numbers came out identical.

## Tooling

- **Type checker:** pyright 1.1.414.
  - `standard` everywhere.
  - `strict` on `recalldrill/__init__.py`, `recalldrill/engine/` and `recalldrill/anki_io/`.
  - `ui/` stays at standard because PyQt6's stubs leave signals partially `Unknown`, which strict rejects on every `qconnect`.
- **Lint:** ruff 0.16.10, rules `E F W I UP B`, line length 100.
- **Tests:** pytest 9.1.1 with `--import-mode=importlib`.
- **Commands** (from the repo root):
  ```
  anki-addon\.venv\Scripts\python -m pytest anki-addon/tests -q
  cd anki-addon && .venv\Scripts\ruff check . && .venv\Scripts\pyright
  anki-addon\.venv\Scripts\python anki-addon/tools/fsrs_handoff_experiment.py
  ```
- **Venv setup:**
  ```
  <python3.13> -m venv anki-addon\.venv
  anki-addon\.venv\Scripts\python -m pip install -r anki-addon\requirements-dev.txt
  ```
- **The web tooling ignores the venv without config changes.**
  - `tsc --listFilesOnly` lists 0 files under `anki-addon/`: TypeScript's default `**/*` skips dot-directories, so `.venv` (which holds aqt's web JS) is never scanned.
  - vitest still finds 30 files and 271 tests.
  - `tsconfig.json` and `vitest.config.ts` are untouched.
- **The root `__init__.py` is guarded with `if __package__:`.** Pytest imports `anki-addon/__init__.py` as a package node, and an unguarded relative import fails there. The menu code lives in `recalldrill/ui/about.py`.

## API facts

Executable: [`tests/anki_io/test_api_facts.py`](../tests/anki_io/test_api_facts.py), on a scratch collection with FSRS on.

**Rules the add-on follows** (Phase 0 corrections, adopted by Don 2026-10-01; details in the table):
1. Image Occlusion = `originalStockKind == StockNotetype.OriginalStockKind.ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION` (**6**). Never `StockNotetype.Kind.KIND_IMAGE_OCCLUSION` (5 = cloze's value).
2. Cloze = `model["type"] == 1` **and not** Image Occlusion.
3. `extract_cloze_for_typing(ordinal=…)` takes `card.ord + 1`.
4. `prop:d` searches use the 0–1 scale. `memory_state.difficulty` is 1–10.
5. `set_due_date` also unsuspends. (Moot for the handoff under decision B, but true of any other use.)
6. `deck:"X"` also matches the deck's cards that currently sit in a filtered deck (via `odid`).

**Where the spec was wrong or silent:**

| Fact | Spec said | Actually true on 26.08.1 |
|---|---|---|
| Image Occlusion detection | `model.get("originalStockKind") == StockNotetype.Kind.KIND_IMAGE_OCCLUSION` | **Wrong enum.** `originalStockKind` uses `StockNotetype.OriginalStockKind`: Cloze = **5**, IO = **6**. `Kind.KIND_IMAGE_OCCLUSION` is **5**, so the spec's check matches *every cloze note* and no IO note. Use `StockNotetype.OriginalStockKind.ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION`. |
| Cloze detection | `model["type"] == 1` | The stock **Image Occlusion notetype is also `type == 1`**. Cloze = `type == 1` **and not** IO (by `originalStockKind`). |
| `extract_cloze_for_typing(ordinal=n)` | — | `n` is the **cloze number** (1-based, `card.ord + 1`), not `card.ord`. Returns `"alpha, gamma"` for two c1 deletions, without hints. |
| `cloze_numbers_in_note` | — | Exists. Returns numbers **unordered** (`[2, 1]` seen). Callers must sort. |
| `prop:d` scale | 0–1 or 1–10? | Search uses **0–1** (`(D − 1) / 9`). `card.memory_state.difficulty` is **1–10**. |
| Rating enum vs revlog ease | Ease 1 = Again | Revlog `ease` is 1-based (1 Again … 4 Easy). `CardAnswer.Rating` (for `build_answer`) is **0-based** (`AGAIN = 0 … EASY = 3`). |
| `deck:"X"` and filtered decks | ? | **Yes.** A card moved into a filtered deck keeps its home deck in `odid`, and `deck:"X"` (and `deck:"X::Sub"`) still finds it. |
| `set_due_date` on a **suspended** new card | ? | **It unsuspends.** Result: `type 2, queue 2, ivl 0, due today+1`, `memory_state None`. One revlog row: `ease 0, ivl 0, lastIvl 0, factor 2500, time 0, type 4` (manual). `factor ≠ 0`, so rslib does **not** treat it as a reset. |
| Answer via scheduler | — | `build_answer` crashes unless `card.start_timer()` was called (it reads `time_taken()`). |
| Typing | — | `col.sched` is typed `V3Scheduler \| DummyScheduler`, `col.db` is `DBProxy \| None`. `aqt.mw` is typed `AnkiQt` (non-Optional) but is `None` outside Anki. `anki_io` code will need `isinstance`/`assert` narrowing. |
| Import order | — | `anki.cards` must not be imported before `anki.collection` (circular import). |
| Leech action default | — | `["lapse"]["leechAction"]` is `1` (tag only); `0` = suspend. New deck default new/day 20, rev/day 200. |
| `answer_av_tags()` on Basic | — | The front's `[sound:]` is **not** repeated in the answer's AV tags, even though the template includes `{{FrontSide}}`. |
| Undo merge | as spec | As spec. Label is `"Recall Drill handoff"`, one `col.undo()` restores tags, queue and due, and **removes the manual revlog rows**. The previous step (`"Suspend"`) is next on the stack. |
| `strip_html` | glues block words | As spec: `"a<br>b<div>c</div>"` → `"abc"`, `[sound:…]` survives. The add-on must turn block tags into spaces first. |

Everything else in §6 behaved as the spec says (state codes `-1`/`0`/`-3`, revlog columns and types, tags, unsuspend, reposition/bury, deck limits, rollover/today, AV tag types).

### Checked headless or by reading the installed `aqt` source

| Item | Result |
|---|---|
| `import aqt.gui_hooks` without a display | Works; it's also a test (`test_gui_hooks_exist`) |
| `deck_browser_will_show_options_menu` | Exists. `(menu: QMenu, deck_id: int) -> None` |
| `overview_will_render_bottom` | Exists. **Filter** `(link_handler: Callable[[str], bool], links: list[list[str]]) -> Callable[[str], bool]` |
| `profile_will_close` | Exists. `() -> None` |
| `webview_did_receive_js_message` | Exists. **Filter** `(handled: tuple[bool, Any], message: str, context: Any) -> tuple[bool, Any]` |
| `operation_did_execute` | Exists. `(changes: OpChanges, handler: object \| None) -> None` |
| `aqt.operations.CollectionOp` | Exists, with `.success()`, `.failure()`, `.with_backend_progress()`, `.run_in_background(initiator=None)`. Constructor: `CollectionOp(parent: QWidget, op: Callable[[Collection], ResultWithChanges])` |
| Tools-menu entry and About box | **Don's manual check** (below) |

## Handoff: A vs B

Run: `anki-addon\.venv\Scripts\python anki-addon/tools/fsrs_handoff_experiment.py` on 26.08.1, Python 3.13.5, FSRS on, default deck options (learning steps 1m 10m).

- **A**: suspended new cards → one undo step (tag `rd::drilled`, unsuspend, `set_due_date "1"`).
- **B**: suspended new cards → unsuspend, `reposition_new_cards` to position 0 (shifting the others), `bury_cards(manual=True)`.

| | A (set due date) | B (reposition + bury) |
|---|---|---|
| **Handoff day** | Review card: `type 2, queue 2, ivl 0, due today+1`. `memory_state None`. Writes one **manual** revlog row (ease 0, factor 2500). One undo step. | Still a **new** card: `type 0, queue -3 (manually buried), due 0` (front of the new queue). `memory_state None`. **No revlog.** Hidden from today's study. |
| **Next day** | Shows as a **review**, due. Doesn't count against new/day. | Comes back automatically at rollover (source and simulated test below) as the **first new card**. **Counts against the deck's new/day.** |
| **First real review (Good)** | Logged as **review** (`type 1`). Next interval **2 days**. FSRS memory state starts at the same S 2.306 / D 2.118 a new card gets for Good. **Skips Anki's learning steps.** | Logged as **learn** (`type 0`). Enters the 10m learning step, then graduates normally. FSRS memory state S 2.306 / D 2.118. **Uses Anki's learning steps.** |
| **FSRS optimizer** (40 cards per arm) | **0 items. Excluded from training for the card's whole life.** | **120 items** (3 per card) |

Control and diagnosis arms:
- **C** (set-due-date row, then first rating logged as *learning*): **80 items**.
- **D** (reviews only, no manual row, no learning row): **0 items**.

Matches the 26.9.3 pre-check exactly (A 0, B 120, C 80).

**Why A is excluded** (`rslib/src/scheduler/fsrs/params.rs`, tag 26.08.1, `reviews_for_fsrs`, line 473): *"when training, we ignore cards that don't have any learning steps"*. A card handed off with `set_due_date` never gets a `Learning` revlog row, because its first real rating is logged as a review. D isolates this: the manual row isn't the cause, the missing learning row is. The card's memory state is still computed for *scheduling* (the non-training path starts from the first user grade). Only optimizer training loses it.

**Manual bury comes back the next day: yes.**
- Source:
  - `rslib/src/scheduler/service/mod.rs:36`: `sched_timing_today()` calls `unbury_if_day_rolled_over()`.
  - `rslib/src/scheduler/bury_and_suspend.rs:32–50`: on a new day it restores every card matching `StateKind::Buried`, which is `queue in (-2, -3)` (`search/sqlwriter.rs:473`). The same file's `unbury()` test does this with a `CardQueue::UserBuried` card.
- Python's `col.sched.today` goes through `sched_timing_today`.
- Simulated with the same trick as that test (creation stamp moved back one day): `queue -3 → 0`. Covered by `test_manually_buried_card_returns_after_rollover` and the experiment's Part 2.
- Confirm in real time in Don's manual check, step 5.

**New-card limit under B:** handed-off cards take new/day slots in the Med Term preset, and they take them **first** (position 0). Med Term preset `new/day`: **_still pending Don_**. It was left blank in the decisions of 2026-10-01. The Anki connector has no deck-options read, and the real collection is not opened directly while Anki runs.

**Cost summary:**
- **A** keeps new/day free, and the handoff is one clean undo step. The cost: it **skips Anki's learning steps**, the first interval is ~2 days with no same-day re-check, and **every handed-off card is permanently invisible to the FSRS optimizer**. That grows with every deck drilled.
- **B** keeps every card in optimizer training and gives Anki's learning steps a same-day-plus-one check. The cost: each card **counts against new/day** on the day after, ahead of the deck's other new cards. The handoff is three ops (wrap them in one custom undo entry, as A does). The card's day-1 review is a learning step, not a spaced review.

**Decision (Don, 2026-10-01): B.** Unsuspend, reposition to the front of the new queue, bury (manual) until tomorrow. Reasons:
- A permanently excludes drilled cards from FSRS optimizer training (A = 0, B = 120, D = 0 above).
- B matches Don's medterm routine.

## Siblings at handoff

**Decision (Don, 2026-10-01): yes, hand off the siblings too.** When one card of a note is drilled (e.g. the Reverse card), the note's **undrilled, suspended, new** siblings are also unsuspended as plain new cards.
- Siblings are repositioned **right after the drilled cards**: drilled cards first, then siblings, then the deck's other new cards.
- Siblings are buried until tomorrow, like the drilled cards.
- This matches the medterm routine, which unsuspends both directions.
- Siblings that are not suspended, or not new, are left alone.

Notes for the phase that builds this (not decisions):
- Siblings also take new/day slots, so a handoff of *n* two-direction notes uses up to 2*n*.
- If the deck preset has "Bury new siblings" on, then on the next day Anki buries a sibling once its drilled card has been studied. The sibling then shows the day after. That's Anki's normal behavior, not a handoff bug.

## Disambiguation hints

**Decision (Don, 2026-10-01): yes.**
- **On by default** only for **non-cloze** note types (cloze = `type == 1` and not IO; see API facts), on decks with **strict punctuation** on.
- The auto-hint rules are a port of the medterm skill's rules. The Phase 2 prompt includes the reference code.
- Manual per-card hint overrides live in `user_files/hints.json` (local, does not sync).

## Mid-session edit

**Decision (Don, 2026-10-01): session-only.** The drill **never writes note fields itself**.
- An **"Edit in Anki"** button opens Anki's Browser on that card.
- When the Browser closes, the add-on reloads the card from the collection and applies the edit to the session.
- The web app's rule for an edit that changes the answer (restart the card, reset its telemetry) is the reference behavior for "applies the edit".

Implementation note (checked in the installed `aqt` 26.08.1 source):
- There is **no `browser_will_close` / `browser_did_close` hook**.
- `Browser.closeEvent` saves the note via `editor.call_after_note_saved`, then `_closeWindow` tears down.
- The Browser is a singleton (`aqt.dialogs.open("Browser", mw, …)`) and may already be open.
- Candidate signals for "closed / edited": the Browser window's Qt `destroyed`/`finished` signal, or `operation_did_execute` with `changes.note_text` for the card's note. To be settled in the phase that builds it.

## UI tech

Pending Phase 3b.

## Engine extensions beyond the TS engine

(none yet)

## Dev install (Windows)

Not run by Claude Code. Don runs it by hand:

```
cmd /c mklink /J "%APPDATA%\Anki2\addons21\recall_drill_dev" "C:\Users\donth\Documents\dev\Recall-drill\anki-addon"
```

- The junction name `recall_drill_dev` **must differ** from the manifest package `recall_drill`.
- **Never "Install from file" a `.ankiaddon` while the junction exists.** Anki empties the target folder on install, and through a junction that deletes the repo's files. Remove the junction first, with `rmdir "%APPDATA%\Anki2\addons21\recall_drill_dev"`. **Never** `del /s`, which follows the junction into the repo.
- Anki writes `meta.json` into the add-on folder (that is, into the repo through the junction). It's gitignored.

### Don's manual check (Phase 0)

1. Create the junction above and restart Anki.
2. Tools menu shows **Recall Drill (dev)**, and its About box shows `Recall Drill 0.0.0 (dev)` and the Anki version. Nothing else changed, and no error pop-up.
3. Tools → Add-ons lists it, and the Debug Console shows no traceback.
4. Answered 2026-10-01 (see the decisions above), except the Med Term preset new/day, which is still pending.
5. Optional, for the bury question: in a throwaway deck, bury a card by hand (Browse → Toggle Bury), and check the next day (after Anki's next-day rollover, Preferences → Review) that it's back.
