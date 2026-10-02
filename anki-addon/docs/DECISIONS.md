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
  - `strict` on `recalldrill/__init__.py`, `recalldrill/engine/`, `recalldrill/anki_io/` and the pure modules `recalldrill/storage.py`, `prompts.py`, `deck_settings.py`, `sources.py`, `controller.py`, `sessions.py`, `history_store.py`, `addon_config.py`, `card_html.py`, `drill_view.py`, `launch.py`, and (Phase 5) `holdout.py`, `measure.py` and `tuning.py`.
  - `ui/` stays at standard because PyQt6's stubs leave signals partially `Unknown`, which strict rejects on every `qconnect`.
- **Lint:** ruff 0.16.10, rules `E F W I UP B`, line length 100.
- **Tests:** pytest 9.1.1 with `--import-mode=importlib`.
- **CI** (`.github/workflows/ci.yml`):
  - `addon-engine` runs the engine tests with no anki installed.
  - `addon-anki` (Phase 3a) runs `tests/anki_io`, `tests/controller` and `tests/storage` with `anki` and `pytest` only. Tests that import `aqt` skip there (`needs_aqt` in `tests/anki_io/anki_fixtures.py`) and run locally. Phase 5 added the measurement tests (`tests/tuning`, `tests/test_measure.py`, `tests/test_holdout.py`) to it.
  - `tests/ui` (Phase 3b) needs `aqt`, so it runs locally only: every `ui/` module imports, and the drill window runs on Qt's offscreen platform with a stand-in web view (QtWebEngine can't start offscreen: the process exits with 127).
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
| Rendered side text (Phase 2) | front = `card.render_output(reload=True).question_text` | Exists (`TemplateRenderOutput`). On a **rendered** side, `[sound:…]` and TTS are already swapped for **`[anki:play:q:N]`** (`[anki:play:a:N]` on the answer), and `{{type:F}}` renders as **`[[type:F]]`** (the reviewer replaces it with the input box). `grading_text` strips both, besides `[sound:]` and `[anki:tts]…[/anki:tts]` in raw fields. |
| Rendered cloze (Phase 2) | — | The active deletion is `<span class="cloze" data-cloze="…">[...]</span>` (or `[hint]`); the other numbers show as plain text. Nested deletions render the same way, and the `data-cloze` attribute (escaped HTML) disappears with the tag. |
| `extract_cloze_for_typing` wrapper | — | `col.extract_cloze_for_typing(text, n)` is the public wrapper (no `_backend`). Nested clozes are flattened: `{{c1::outer {{c2::inner}} text}}` → c1 `"outer inner text"`, c2 `"inner"`. |
| Searches the add-on builds (Phase 2) | — | `mid:<note type id> card:<template ord + 1>` finds one template's cards. `col.build_search_string(SearchNode(deck=…))` / `SearchNode(tag=…)` escape `_`, `*` and `"`, so deck names and tags are matched literally. |
| Flags, filtered new cards (Phase 2) | — | `card.user_flag()` is `flags & 7` (red = 1, `flag:1`). A new card moved into a filtered deck keeps its new-queue position in `odue`. |

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
| `aqt.operations.QueryOp` | Exists: `QueryOp(parent, op, success)`, `.with_progress()`, `.failure()`, `.run_in_background()`. The setup panel reads cards with it, off the main thread |
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

**New-card limit under B:** handed-off cards take new/day slots in the deck's preset, and they take them **first** (position 0).

**Decision (Don, 2026-10-01): resolved, no cap intended.** The Med Term preset's new/day is not meant to hold handed-off cards back. If it ever does, Don raises the preset's limit by hand.
- The add-on never changes deck options.
- No code change for this decision. The Phase 4 handoff forecast reads the real new/day value from deck options (`col.decks.config_dict_for_deck_id(did)["new"]["perDay"]`).
- When handed-off cards plus siblings would exceed that value, the forecast **warns** and never blocks the handoff.

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
- Siblings also take new/day slots, so a handoff of *n* two-direction notes uses up to 2*n*. The Phase 4 forecast counts them (see "New-card limit under B").
- If the deck preset has "Bury new siblings" on, then on the next day Anki buries a sibling once its drilled card has been studied. The sibling then shows the day after. That's Anki's normal behavior, not a handoff bug.

## Disambiguation hints

**Decision (Don, 2026-10-01): yes.**
- **On by default** only for **non-cloze** note types (cloze = `type == 1` and not IO; see API facts), on decks with **strict punctuation** on.
- The auto-hint rules are a port of the medterm skill's rules. The Phase 2 prompt includes the reference code.
- Manual per-card hint overrides live in `user_files/hints.json` (local, does not sync).

## Reading cards (Phase 2)

How the add-on turns Anki cards into drill items (`recalldrill/anki_io/`). Executable in `tests/anki_io/`.

**Text.** Every graded string goes through `grading_text` (`anki_io/text.py`): drop `[sound:]`, `[anki:tts]…[/anki:tts]`, `[anki:play:…]` and `[[type:…]]`; turn `<br>`, `<hr>` and block-element tags (opening and closing: `div`, `p`, `li`, `ul`/`ol`, table cells, headings, …) into spaces; `strip_html`; NBSP → space; collapse JS whitespace; trim. Inline tags (`<b>os</b>seous`) stay glued. Display keeps the HTML.

**Front.** Always Anki's render of the question, never a mapped field. So cloze `[...]`/`[hint]`, images and template text come out right.

**Kinds.** `image_occlusion` only by `originalStockKind` 6 (stock IO), then `cloze` (`type == 1`), else `standard`. The note type's **name plays no part**. Stock IO is ineligible. A single cloze note whose cloze field holds `image-occlusion:` is ineligible on its own (counted as image occlusion); the rest of its note type is drilled. Anything else goes through the mapping, and a card with no typeable text ends up as "empty answer".

**Changed before merge (Don, 2026-10-02): no name rule for Image Occlusion.** Phase 2 first also treated any note type whose name contains "Image Occlusion" (meant for the IO Enhanced add-on), or whose sampled cloze notes held `image-occlusion:`, as IO. On Don's collection:
- All 686 image-occlusion notes use the anki-cards lookalike "Image Occlusion (anki-medical-cards)"; there are 0 stock IO and 0 IO Enhanced notes.
- The lookalike is a **standard** note type: fields `Question, Answer, Extra, FullContext, Source, Notes`, one template "Reveal" (front `{{Question}}`, back `{{Answer}}<hr id=answer>` then Extra / FullContext / Source).
- Its `Answer` repeats the Question HTML (header, image, masks) and adds a typeable label.

So the name rule only blocked drillable cards. The type-wide sampled-marker rule is gone for the same reason: it could block a whole cloze type over a few IO notes, which the per-note check already catches.

**Default mapping** (per note type id and template ord; `notetypes.py`):
- Standard: `{{type:F}}` on the front wins. Otherwise the candidates are the fields the answer side shows after `<hr id=answer>` that the front doesn't, in template order, minus:
  - **reference fields**, never an answer: `Extra`, `Back Extra`, `Notes`, `Remarks`, `FullContext`, `Source`, `Sources`, `Comments`, `Header`, `Footer` (case, spaces and `_` ignored);
  - media-looking names (`Audio|Sound|Image|Picture|Photo|Mask`);
  - TTS-only references.

  **If nothing is left after the rule**, the fields *before* it that the front doesn't show. That's how the IO lookalike maps to `Answer`.

  The first candidate with a non-empty answer in ≥ 50% of up to 50 sampled notes (evenly spread over the note ids) is the answer. None qualifies: unmapped.
- **Answer delta, image cards only** (standard): when the answer field and the fields the front shows (in `qfmt`, minus `{{type:}}`/TTS references and the answer field itself) contain the **same `<img src>`**, and the answer field's grading text starts with the front fields' grading text (joined by a space), the answer is the rest, trimmed.
  - This is the IO lookalike pattern: its Answer is "header + image + label", so it grades as the label (`Nucleus`, `Goblet cells`, `Hyaline (articular) cartilage`).
  - Empty remainder: "empty answer". A match that ends mid-word doesn't count.
  - **Text-only cards are graded in full**, even when the answer starts with the prompt: front `Bone`, back `Bone marrow` grades `Bone marrow` (Don, 2026-10-02).
- Standard Extra: the first of `Extra`, `Back Extra`, `Notes`, `Remarks` that exists, isn't the answer, and has content (text or an image) in a sampled note.
- Cloze: the field of the first `{{cloze:F}}` (or `{{type:cloze:F}}`) on the front; answer = `extract_cloze_for_typing(field, card.ord + 1)`; Extra = `Extra` or `Back Extra`. Never `FullContext` or `Source`.
- Overrides in `mappings.json` win, and may name any field (a reference field too). `ineligible: true` excludes the template ("marked ineligible"). No override makes stock IO drillable: it holds shapes, not text. An override naming a missing field leaves the template unmapped, so the panel shows it.

**Classes** (`cards.py`, first match wins): `in_filtered_deck`, `buried`, `flagged` (red by default), `leech`, `stable` (Phase 6, see "Difficulty adjustment"), `suspended_new`, `suspended_review`, `lapsed`, `learning`, `new`, `young` (< 21 days), `mature`. Picked by default: flagged, leech, suspended_new, lapsed, new, young.

**Selection** (`select.py`):
- Ineligible, counted by reason, first match wins: image occlusion, marked ineligible, unmapped, empty answer, then (unless that class is switched on) filtered deck and buried. Content reasons come first because they don't go away by themselves.
- Deck order: new cards by new-queue position (`odue` while in a filtered deck), then all other cards by `(note id, ord)`. Priority first: class rank `flagged, leech, lapsed, suspended_new, new, young`, then the classes that are off by default, then deck order. New cards are never re-sorted by note id, so `Layer::1 → 4` positions survive.
- Template filter (`card_ords`, saved per deck) works on the template index, which is 0 for every card of a cloze note type.
- `apply_holdout` sets the holdout aside while walking the ordered list (Phase 5, see "Measurement and holdout"). Cards of notes tagged `rd::holdout` are left out first (`holdout_exclude`, counted).

**Hints** (`prompts.py`, standard note types only). A port of the medterm skill's rules, with three adaptations for whole decks instead of one day's list:
1. Conflicts are looked up in a **pool**: every content-eligible card (any state) of the same note type and template under the selection's top-level deck. Hints are only made for the session's cards.
2. Keys are cards (`"<note id>:<ord>"`, as in `hints.json`), not terms. **Two cards with the same answer never conflict:** typing that answer is right for both prompts. (The skill deduplicated within a day and never met this; across chapters, repeated word parts would otherwise all be flagged.)
3. No card is dropped (the skill skipped a repeated front/term pair).

The front reads `meaning (N forms; hint)`, the skill's order. Default: on when the deck's strict punctuation is on and more than half the selected cards are standard note types; a saved `hints` wins.

**Image fronts.** A card whose rendered front contains `<img>` gets no hint (auto or manual) and is kept out of the conflict pool. The cards of one figure share the same header text; the image is what tells them apart. `SourceRef.image_front` marks them so the later "that's another card's answer" catch skips them too.

**What a source carries for display** (`build.py`, `SourceRef`): `front_html` (rendered question), `answer_html` (rendered answer, `render_output().answer_text`), `css` (the note type's CSS from `render_output()`; some lookalike cards draw their masks with CSS classes only), `extra_html` (raw Extra field), plus ids, class, flags, `answer_hash`, `has_audio`, `image_front` and the `hint` suffix.

**Per-deck settings** (`deck_settings.py`, `deck_settings.json` by deck id): `strictPunctuation`, `stemTolerance`, `batchSize`, `hints`, `cycleOrder`, `card_ords`. With nothing saved, a deck where ≥ 80% of the selected answers have ≤ 3 words gets a **proposal** (`stemTolerance` off, `strictPunctuation` on, `hints` on). It is never saved by the add-on by itself: the setup panel offers it as one click, and saves the deck's settings only on Start or Save. Phase 3b added `encodeReps`; Phase 5 added `holdoutPct` (Holdout %, see "Measurement and holdout").

**Storage** (`storage.py`): `user_files/profiles/<profile>/…`, one folder per Anki profile (a name with unsafe characters gets a hash suffix). Files are `{"schemaVersion": 1, "data": …}`, written atomically; an unreadable file is renamed `*.corrupt-<timestamp>` and the default is used.

**Known limitations:**
- A note type with several cloze fields is drilled on the first `{{cloze:F}}` of its front template only.
- The template filter can't pick cloze numbers (c1 vs c2): a cloze note type has one template.
- The front's `front_html` still holds `[anki:play:q:N]` and `[[type:F]]`; the drill window handles them (see "UI tech").

## Drill controller and session storage (Phase 3a)

SessionView isn't a pure view, so its behavior is ported to a Qt-free `DrillController` (`recalldrill/controller.py`). Phase 3b's Qt window renders `view()` and runs the effects each action returns: `StartDwell(ms)`, `PlayAnswerAudio(cid)`, `Persisted` / `PersistFailed`, `SessionComplete`, `SessionStopped`, `CollisionNotice(other_answer)`, `ClearInput`.

**Ported one-to-one** (each beside a comment naming the TS handler):
- the pre-wrong snapshot that "Count as correct" re-applies;
- the reveal flag the next answer consumes;
- the dwell from `DWELL_MS[dwellKey]`;
- the Extra pause, which holds the advanced state until Continue;
- `applyNext` on Continue in the cycle and Final check only;
- editing with a wrong verdict showing, and `editRevealsOnClose`;
- the busy guard (B5);
- saving after every answer.

`tests/controller/test_parity.py` replays the Phase 1b scripted scenarios through the controller's actions and checks the engine state after every step against the goldens.

**Changes from SessionView:**
- After "Count as correct" auto-advances, SessionView leaves Continue up on the next trial (`handleOverride`'s dwell callback never resets `showNextBtn`), and pressing it in the cycle runs `applyNext`, skipping a card. The controller's dwell always ends with Continue down. The web app still has the bug.
- Every action, End session included, is ignored during a dwell (busy guard). SessionView's End session also works during a dwell.
- An Extra that is only an image counts as an Extra: it shows, and it holds the pause like a text Extra does. The web app's Extra is text only.

**Kept from SessionView, on purpose:** End session during the Extra pause saves the state still on screen, as App does, so that one answer is lost.

**Add-on only:**
- **The "other card's answer" catch** (config `collision_catch`, default on). `build` gives each `SourceRef` `colliding_answers`: the answers of cards whose fronts conflict under the hint rule (same pool as the hints, filled in even with hints off; image fronts have none). On a full / cycle / Final trial, typing one of them exactly (and not this card's answer) shows *"That's the answer to another card with this prompt. This one wants a different form."*, clears the input and changes nothing: no trial, no save. The engine never sees it. A controller-side `collisions` tally goes into the save and the history.
- **Answer audio** (config `play_audio_on_feedback`, default on): `PlayAnswerAudio` when feedback shows the full back and the card has answer audio.
- **0 items is refused.** The engine's empty-deck path never completes.

**Session saves** (`recalldrill/sessions.py`): `sessions/<key>.json`. Keys: `deck-<did>`, `search-<sha1(query)[:12]>`, `again-<parent key>`.
- The content is the web app's `SavedSessionState`, written as SessionView builds it, plus `addon`: `sources`, `scope`, `selectOptions`, `deckSettings`, `hints`, `sessionId` (uuid4 hex from Start), `startedAt`, `collisions`, `handoffPending`, `historyWritten`, `drillAgainOf`.
- Resume (`sessions.resume`) mirrors `App.handleResumeSession`.
- `anki_io.resume.check_resume(col, saved)` lists `missing` and `changed` cards (answer hash vs what `build` reads now) for "Start fresh" / "Resume with the saved text". Engine state is never patched.
- **On completion:** history is written once, then `handoffPending` is set and the save is kept. A pending save offers "Hand off finished session", never "Resume". It's deleted after the handoff (`sessions.complete_handoff`) or on "Don't hand off" (`sessions.decline_handoff`), each after its history line (see "Handoff (Phase 4)").
- Drill-again sessions write no history and no handoff, and their save is deleted on completion.

**History** (`recalldrill/history_store.py`): `history/<did or search key>.jsonl`, append-only, never rewritten, no 50-entry cap.
- One `type: "session"` line per completed session: `sessionId`, `buildHistoryEntry`, `anki` (per card `cid, nid, ord, did, card_class`; `did` since Phase 5; parallel to the entry's `cards`), `encode` (`encodeReps, chunkDifficulty, MIN_WORDS_TO_CHUNK, ladderMode, batchSize, strictPunctuation, stemTolerance, hints`; `MIN_WORDS_TO_CHUNK` is the session's own since Phase 5), `scope`, `collisions`, `holdout` (Phase 5: `cid, nid, ord, did, card_class` per held-out card; `[]` before).
- An append skips a `sessionId` that already has a session line. That covers a crash between the append and the save's `historyWritten`.
- Phase 4 added `type: "handoff"` lines (a handoff, or a declined one; see "Handoff (Phase 4)").
- Phase 5 added `history/tuning.jsonl`: one `type: "tuning"` line per applied suggestion (see "Measurement and holdout").
- **Cold-start estimates:** `estimates.json`, keyed like the saves. It ports `get/saveColdStartHistory` and is updated whenever a session ends (completed or stopped), as SessionView's `finishSession` does. Since Phase 6 nothing reads it (see "Pacing (Phase 6)").

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

**Settled in Phase 3b.**
- Ctrl+E / Edit in Anki: `controller.begin_edit()` (so a still-unanswered card counts as revealed when the edit keeps progress), then `aqt.dialogs.open("Browser", mw, card=…, search=("cid:<id>",))`. `card=` selects the row, so the editor shows the card in a new or a reused Browser.
- **When the Browser closes** (Qt's `destroyed`, which fires after `closeEvent` saved the note), or on **Done editing** in the drill window (after `editor.call_after_note_saved`), `build.rebuild_card` re-reads that one card the way `build` did (front render, answer, Extra, answer side, CSS; the session's hint and colliding answers are kept) and calls `apply_card_edit`. A card that is gone, or whose answer is now empty, cancels the edit.
- **`operation_did_execute` is not used for this.** The Browser's editor saves the note while you type (an `update_note` op with `note_text` per save), so applying on the first such op would end the edit after one keystroke. Done editing covers a Browser that was already open and that Don wants to keep open.
- The drill never writes fields: edits are Anki's own, formatting intact.

Controller side (Phase 3a): `begin_edit()` returns the card to open (or None when SessionView's Edit button would be disabled), and the Browser closing calls `apply_card_edit(front, back, extra, source)` with the card as `build` reads it now, or `cancel_edit()`. The engine's `edit_current_item` decides restart vs kept progress, as in the web app. The web app's write-back to a saved deck and its "Saved for this session only." notice don't apply.

## UI tech (Phase 3b)

**Decision: an `AnkiWebView` for the card area, native Qt for everything you type into or press.**
- **Web view** (`ui/drill_window.py`, HTML from `drill_view.py`): the stage pill and cue badge, Anki's rendered front (media, ▶ buttons, the hint), the cue or revealed target, the feedback with the colored word diff, an image card's answer side, the Extra. Also the batch interstitial and the Done screen. The page is loaded once with `stdHtml` (with `css/reviewer.css` and MathJax, as the reviewer); every render is one `rdRender(payload)` eval, so there's no reload and no focus theft.
- **Native**: the answer box is a `QLineEdit` (no JS focus or IME trouble, no `pycmd` per keystroke); the buttons, progress bars, stats line and status dots are Qt widgets.
- **`pycmd`** is used only for the ▶ buttons in the card HTML (`play:q:N` / `play:a:N` → `play_clicked_audio`), plus a key fallback (`rd:enter`, `rd:ctrl-enter`, `rd:edit`, `rd:replay`) for when a click leaves focus in the page. AnkiWebView's own Esc message (`close`) reveals.
- **No logic in Qt.** The window renders `DrillController.view()` and runs effects. Decisions the window needed were moved into the controller, with tests (`tests/controller/test_display.py`): `Flash(ok)` (SessionView's `triggerFlash`), `StopAudio` and `PlayQuestionAudio`, `ViewModel.answer_html`, `hint`, `card_ord` and `audio_side`. The HTML is built by pure `drill_view.py` / `card_html.py`, also tested.

**Rendering the card like the reviewer.**
- The body gets `theme_manager.body_classes_for_card_ord(ord)` (`card cardN` plus the night-mode classes), and the note type's CSS (`SourceRef.css`) goes into a `<style>` on every render. That is what makes the image-occlusion lookalike's CSS-only masks (`.ob`, `.ob.a`, `.occ-wrap`) visible. Night mode follows `theme_manager.night_mode` (body classes per render, and AnkiWebView's own `theme_did_change` handler).
- `[[type:F]]` is removed from the front (the drill's own input replaces Anki's type-in box). `[anki:play:…]` becomes ▶ via `mw.prepare_card_text_for_display`, which also escapes media file names. `[sound:]` in the raw Extra field is dropped (a field isn't rendered by the template pass).
- The hint (`SourceRef.hint`) is appended to the displayed front.
- Extra is shown from `extra_html` (formatting and images kept) whenever the view says Extra is visible.
- **Image cards fit the window** (fixed after Don's manual check, 2026-10-02). On a card whose front has an `<img>` (`ViewModel.image_front`, the card gets `rd-img-card`), images in the front and answer are capped at `max-height: 60vh` with `width: auto` and `max-width: 100%`, all `!important`: some notes put `max-height:none` inline on the `<img>`. The occlusion boxes stay aligned because every variant wraps the image in an inline-block, relatively positioned box (`.occ-wrap` in the note type CSS, or an inline style), which shrinks with the image. Checked in Chromium on three real Bones/Cell/Epidermis notes (`.occ-wrap` with `.ob` boxes, inline-style boxes `#e04b3c`/`#e8c440`, and the `<br><b>label</b>` variant): wrapper size = image size, boxes at their declared %. With a web area of 700 px or more, the header + figure + cue (trial) and the verdict + cue + figure + label (feedback) fit without scrolling; at 620 px the feedback label falls up to 19 px below the fold.
- **On full-answer feedback, an image card shows the answer side in place of the front** (`ViewModel.answer_html`, via `card_html.answer_side`): the verdict and diff, the cue line, the answer figure (same scaling), then Extra. Stacked below the front figure, the revealed label was off screen. The rendered answer is split at `<hr id=answer>`: when the part before it is the front again (`{{FrontSide}}`) or empty, the part after it is shown; otherwise the part before it is the answer (the IO lookalike's `{{Answer}}`: image with the region revealed, plus its label), and the Extra after the rule stays in its own section, so it isn't shown twice.
- The card area scrolls to the top on every render.
- Text-only cards render exactly as before (a test pins the HTML).
- Diff colors are the web app's tokens, light and night: matched words plain, missed words red, underlined, on a red tint; feedback text green / red / blue for success / danger / info. The card flashes green or red for 400 ms, as SessionView.
- Card templates' `<script>` tags don't run (the HTML is set with `innerHTML`). MathJax is typeset after each render.

**Media loading: no rewrite needed.** `stdHtml` puts `mw.baseHTML()` (`<base href="{mw.serverURL()}">`) in the head, and Anki's media server answers any path that isn't `_anki/…` or an add-on export from the collection's media folder. So a card's `<img src="x.png">` loads as in the reviewer, once `prepare_card_text_for_display` has escaped the file name. Checked in the installed source (`test_phase_3b_display_apis`); confirm by eye in the manual check.

**Timers and audio.**
- `StartDwell(ms)` starts a single-shot `QTimer` → `dwell_elapsed()`. The controller ignores every action during a dwell (busy guard), so nothing can cancel it from the keyboard; closing the window, End session and profile close **flush** it first (`dwell_elapsed()` now), so the answer's state is committed before saving.
- `PlayAnswerAudio(cid)` → `av_player.play_tags(card.answer_av_tags())`.
- **Stop audio when the next trial shows another card** (`StopAudio`), not between trials of the same card. Stopping on every trial would cut a term's answer audio after the 500 ms dwell, before it's heard.
- Config `autoplay_question_audio` (default off): `PlayQuestionAudio` when a card comes up (once per card, not per trial).
- Ctrl+R replays the question's audio, or the answer's once the feedback shows the full back (`ViewModel.audio_side`).

**The drill window.** A top-level, non-modal `QDialog` (no parent, so Anki stays usable and can be in front), placed over the main window and then restored from `saveGeom`/`restoreGeom` (`recalldrill_drill`). Esc reveals (`keyPressEvent` and `reject()` both). The window's X asks **Save / Discard / Cancel**: Save is Save and stop; Discard deletes the session's save. A drill-again window asks Discard / Cancel (it's session-only). A finished session closes without asking. Two windows never drive the same save: opening a deck whose session window is open brings that window to the front.

**Keys.** Enter: submit, continue, or Next batch on the interstitial. Ctrl+Enter: Count as correct (only when offered). Esc: reveal. Ctrl+E: Edit in Anki. Ctrl+R: replay audio (a bare R would type into the answer box).

## Entry points (Phase 3b, checked on 26.08.1)

| Entry | How | Status |
|---|---|---|
| Tools → **Recall Drill…** | `mw.form.menuTools` action, current deck | works |
| Deck gear → **Recall Drill this deck** | `deck_browser_will_show_options_menu(menu, deck_id)` | works |
| Overview → **Recall Drill** button | `overview_will_render_bottom(link_handler, links)`: the button is added to `links`, and the returned handler answers its `pycmd` | works. **`webview_did_receive_js_message` isn't needed**: the overview's bottom bar sends its messages to the handler this filter returns. |
| Profile close | `profile_will_close`: each open drill window flushes its dwell, saves and stops, and closes; setup panels close | works |
| Tools → **Recall Drill: my rd::hard cards** / **Recall Drill: filtered deck for rd::hard** | `mw.form.menuTools` actions (Phase 4) | works (headless test; Don's manual check) |
| Tools → **Recall Drill: tuning report** | `mw.form.menuTools` action (Phase 5) | works (headless test; Don's manual check) |

"Works" is from the installed source and headless tests; Don's manual check confirms it in Anki. The Phase 2 dev preview (`Recall Drill (dev): preview current deck`) is gone; its content is the setup panel's. The About box stays.

## Setup panel (Phase 3b)

`ui/setup_dialog.py`, reading through `anki_io/panel.py` with `QueryOp` (off the main thread, 300 ms after the last change).
- **Scope**: the deck (with subdecks), or a **Search…** over the whole collection. A search's settings belong to the deck holding most of what it finds (`deck_settings.settings_deck`, every template counted).
- **Saved session** for the scope's key: a pending handoff offers **Hand off finished session** / **Don't hand off** (Phase 4); a resumable save offers **Resume** / **Start fresh**; a save with missing or changed cards (`check_resume`) lists them and offers **Start fresh (recommended)** / **Resume with saved text**. Start with a save present asks before replacing it.
- **Cards**: class toggles with eligible counts (Phase 2 defaults), max cards (0 = all), an exact tag, order. **Templates**: one checkbox per template of each multi-template standard note type, saved as the deck's `card_ords`; the sibling count is shown. **Ineligible** reasons are summed, with **Edit mapping…** (`ui/mapping_dialog.py`: answer field, Extra field or ineligible per (note type, template), saved to `mappings.json`).
- **Settings for this deck**: batch size (0 = whole deck), blind typings (`encodeReps`, now a per-deck setting; the config's `encode_reps` is the default), cycle order, strict punctuation, word-ending tolerance (disabled while strict, as the app), hints. While nothing is saved for the deck, the terminology proposal is offered as **Use terminology settings** (one click; it changes the draft, it isn't saved). Settings are saved only by **Save** or **Start**.
- **Hints**: the flagged prompts, and prompts that already have a manual hint, with the hint editable in place (`hints.json`; an emptied cell removes the hint).
- **Estimate** (until Phase 6): `compute_cold_start_estimate` over the built items with the deck's `encodeReps` and the config's chunk difficulty and ladder; the multiplier is `estimates.json`'s for the scope's key when there is one, else the exposure picker (fresh / once / familiar). Shown as "about N–M min". **Replaced in Phase 6** by the measured drill time (see "Pacing (Phase 6)"); the exposure picker is gone.
- **Start** goes through `launch.start`: saves the deck's settings, then `sessions.start_session` (`build_items(…, shuffle_within_batch=False)`). Disabled with 0 drillable cards, saying why.

Global config gained `autoplay_question_audio` (default false); `addon_config.parse_config` gives every missing or mistyped key its default.

## Handoff (Phase 4)

`recalldrill/anki_io/handoff.py`, `recalldrill/ui/handoff_dialog.py`. Executable in `tests/anki_io/test_handoff.py` (scratch collection, FSRS on) and the new facts at the end of `tests/anki_io/test_api_facts.py`.

A **complete** session (every card `finalDone`) is handed to Anki in one confirmed, undoable step. From then on Anki owns the cards' scheduling, and the drill's struggles live on as note tags. A saved-and-stopped or abandoned session hands off nothing.

**Plan, then apply.** `plan_handoff(col, saved, settings)` reads a fresh `CardSnapshot` of every session card (and of every card of their notes), then `build_plan` (pure) decides. Cards that no longer exist are skipped and listed. `apply_handoff(col, plan)` is the add-on's **only collection write**. The UI runs it inside `CollectionOp`: one undo step, "Recall Drill handoff", and the main window refreshes.

| Group | Rule | Action |
|---|---|---|
| `drilled_new` | `type == 0` now (suspended or not) | **A**: unsuspend, `set_due_date("1")`. **B**: unsuspend, reposition to the front of the new queue in drill order, bury (manual) |
| `drilled_scheduled` | `type != 0` now (learning, review, relearning; suspended leeches, red-flagged repair cards, and a card studied on the phone since the drill) | unsuspend if suspended; the schedule is **never** changed; buried (manual) if due today or overdue, so its first Anki rating comes tomorrow |
| `siblings` | `handoff_siblings` on; the drilled notes' other cards that weren't in the session and are new **and** suspended | unsuspend, reposition right after the drilled cards (A: at the front), bury |
| `holdout` (Phase 5) | the session's held-out cards (`addon.holdout` in the save) that still exist, are still new, and share no note with a drilled card | unsuspend, reposition right after the drilled cards and their siblings, bury, tag `rd::holdout` (A and B alike: they always stay new) |
| `holdout_siblings` (Phase 5) | `handoff_siblings` on; the holdout notes' other cards that are new and suspended | as siblings: unsuspend, queued right after the holdout cards, bury |

"Due today or overdue": a review or day-learning card with `due <= today`, or an intraday learning card due before `col.sched.day_cutoff` (the home deck's due while in a filtered deck).

**Flags and tags.** The red flag is cleared on drilled cards that have it (`clear_flag_on_handoff`, default on; `set_user_flag_for_cards(0, …)`): the last step of the anki-cards repair routine. Tags are note-level, so a note qualifies if any of its drilled cards does: `rd::drilled` always; `rd::hard` when misses + reveals + Final-check misses ≥ `hard_threshold` (3); `rd::final-miss` when a Final-check miss happened; `rd::long` for a chunked answer (`tag_long`, default off). `rd::hard` and `rd::final-miss` are **replaced**: removed from this session's notes that no longer qualify. Other tags (`rd::drill::*`, `Part::*`, `Layer::*`, `leech`) are never touched.

**Every action is planned only where it changes something** (unsuspend only suspended cards, bury only unburied ones, reposition only when the cards aren't already at those positions, tags only where missing or present). So planning again right after a handoff plans nothing (tested for A and B).

**Settings** (`config.json`): `handoff_mode` ("B", from the decision above; "A" is implemented too, so changing it is a setting), `handoff_siblings` (true), `hard_threshold` (3), `clear_flag_on_handoff` (true), `tag_long` (false).

### Facts found in Phase 4 (checked on 26.08.1)

| Fact | Consequence |
|---|---|
| **Each backend call commits on its own.** `add_custom_undo_entry` is not a transaction, and `CollectionOp` adds none: a failure partway leaves the earlier calls applied, as separate undo steps ("Update Tag" on top). | **Decision (Don, 2026-10-02): roll back.** On any exception, `apply_handoff` merges what ran into the "Recall Drill handoff" entry, undoes it (only if that entry is on top) and raises `HandoffFailed(rolled_back=True)`. The session stays pending and the error says nothing changed. If the rollback fails too, the message points at Edit → Undo. Tested with a forced failure mid-handoff. |
| `unsuspend_cards` is `restore_buried_and_suspended_cards`: it **unburies** too. | Only suspended cards are passed to it, and it runs before the buries. |
| `reposition_new_cards` gives one position **per note**, in the order notes first appear in the list (the cards' current order doesn't matter); a note's cards share it. Other new cards shift by the number of cards passed. | Siblings in the same call would share their drilled card's position. They get a second call starting right after the drilled notes: drilled cards 0…n−1, siblings n…, then the deck's other new cards. Two drilled cards of one note share a position. |
| `reposition_new_cards` on a new card in a filtered deck sets its home position (`odue`); `bury_cards` works there too; `set_due_date` takes the card out of the filtered deck. | No special case for filtered decks. |
| `bury_cards(manual=True)` on review, learning and day-learning cards changes only `queue` (due, ivl, memory state untouched). | As the spec assumed. |
| `prop:due=1` matches review and day-learning cards due tomorrow, not suspended or buried ones. `is:learn prop:due<1` matches intraday learning cards due today. | The forecast's "reviews tomorrow" search. |
| Missing card or note ids are ignored by every call the handoff makes. | A card deleted between plan and apply can't fail the handoff. |
| Deck options' "This deck" limits are `newLimit` / `reviewLimit` on the deck (None unless set). | The forecast uses them over the preset's `perDay` when set. |
| `FilteredDeckConfigDialog(mw, search=…)` and its `reopen(…, search=…)`. | The rd::hard filtered-deck entry. |

### Tomorrow's load (the forecast)

`forecast(col, plan, top_deck_id)`, for the top-level deck of the deck holding most drilled cards:
- **Reviews tomorrow**: the cards of `deck:"<top>" (prop:due=1 OR (is:learn prop:due<1))`, plus the handed-off cards that will be reviews tomorrow and that search doesn't count yet (A's drilled new cards; scheduled cards buried today). Counted as a set of card ids, so nothing counts twice. Compared with the deck's review limit.
- **New cards tomorrow**: B's drilled new cards plus the siblings, the ones joining the front of the new queue. Compared with new/day; above it, `new − limit` spill to the following day.
- **Collection-wide** reviews tomorrow, the same way, as context.
- **Warnings** (amber, never blocking): new/day exceeded, review limit exceeded, or reviews tomorrow > 1.5 × the deck's average of `prop:due=1` … `prop:due=7`.
- **When**: `next_day_start(now, rollover)`: today at the rollover hour if that's still ahead (drilling at 1 AM with a 4 AM rollover: that same morning), else tomorrow's. Written "Sat Oct 3, 4:00 AM" (English names whatever the locale). Checked against `col.sched.day_cutoff`.

### The dialog

From the Done screen's **Hand off** or the setup panel's **Hand off finished session** (`offer_handoff`): plan and forecast with `QueryOp`, then the confirmation:
- the headline "Hand off N cards: tag, unsuspend, <B: stay new, front of the queue, available from …> / <A: become review cards due from … (no learning steps)>";
- already-scheduled cards that keep their schedule, and those buried until tomorrow; missing cards; siblings; tags +X / −Y with a per-tag breakdown; red flags cleared;
- the forecast block and its warnings.

Buttons: **Hand off**; **Not now** (the session stays pending); **Don't hand off** (the save goes, with a declined history line). On success: the `type: "handoff"` history line, then the save is deleted, then "Handed off. Edit → Undo "Recall Drill handoff" reverts it." On failure: the session stays pending and the error shows.

The setup panel's other ways out of a pending handoff also write the declined line: its **Don't hand off** button (was "Discard"), and **Start** over it (after the "replaces it" question).

**Undo doesn't bring the save back.** After Edit → Undo "Recall Drill handoff", the cards are back as they were, but the session's save is already deleted, so the panel has no banner. Edit → Redo re-applies the handoff.

**History lines** (`history/<key>.jsonl`): `{"type": "handoff", "sessionId", "mode", "timestamp", "groups": {drilled_new, drilled_scheduled, siblings, holdout, holdout_siblings, holdout_skipped, missing}, "actions": {unsuspended, setDue, repositioned: [{cids, start}], buried, flagsCleared}, "tags": {added, removed, byTag}, "hardThreshold", "cards": [{cid, nid, ord, struggle, finalMisses, chunked, hard}], "forecast": {…}}`, or `{"type": "handoff", "sessionId", "declined": true, "timestamp"}`.

### The rd::hard entries (Tools menu)

- **Recall Drill: my rd::hard cards** opens the setup panel with the search `tag:rd::hard` (an exact tag).
- **Recall Drill: filtered deck for rd::hard** opens Anki's own filtered-deck dialog with that search filled in. Don builds the deck there; the add-on creates nothing.

**Changed from the prompt: a per-card filter, not the template filter.** `rd::hard` is a note tag, so a hard card's siblings carry it too. The prompt asked to narrow with the template filter, but that works on the template index, which is 0 for every card of a cloze note type ("Reading cards", template filter), so it can't keep c1 and drop c2. And it's a saved deck setting, which Start would save for the deck. Instead, `SelectOptions.exclude_cids` leaves out the cards whose **latest handoff line** says `hard: false` (`history_store.hard_cards`, every history log, declined lines ignored). Cards never handed off (a note tagged by hand) stay in. The panel shows "Only the cards that were hard in their last handoff" (on), and how many were left out. The panel applies this to the `tag:rd::hard` search only. The filtered deck uses the plain tag.

## Engine extensions beyond the TS engine

**`SessionConfig["minWordsToChunk"]`** (Phase 5). Python-only. **Absent ⇒ identical** to the TS engine.
- What: the session's own `MIN_WORDS_TO_CHUNK` (answers with at most this many words are drilled whole). `edit_current_item` uses `config.get("minWordsToChunk", MIN_WORDS_TO_CHUNK)` for both its rechunk check and its restart rebuild; the module constant is unchanged.
- Who sets it: the add-on, from config `min_words_to_chunk` (default 8 = the constant), through `launch.session_config` → `sessions.new_session_state` (`build_items(…, min_words_to_chunk)`) → the engine config. The save stores it as top-level `minWordsToChunk` (dropped when absent, like every other `None`), resume and drill-again carry it, and the history line records it as `encode.MIN_WORDS_TO_CHUNK`.
- `compute_cold_start_estimate(…, min_words_to_chunk=MIN_WORDS_TO_CHUNK)`: an optional last argument, so the panel's estimate chunks as the session will. Left out: the TS call.
- Why: applying a `MIN_WORDS_TO_CHUNK` suggestion from the tuning report needs the engine to honor it mid-session, not just at build.
- Proof: the golden and simulate parity suites pass unchanged (they never set the key), the goldens regenerate with no diff, and `tests/engine/test_min_words_to_chunk_ext.py` checks the set case (edit-restart rechunks with the session's T, a case-only edit keeps progress under it) and that an absent key equals the constant.

**`DrillItem["encodeRepsOverride"]` and `DrillItem["minWordsToChunkOverride"]`** (Phase 6). Python-only, optional, per card. **Both absent ⇒ identical** to the TS engine.
- What: a card's own `encodeReps` and its own chunk threshold, in place of the session's.
- One helper, `items.reps_for(item, config)` = `item.get("encodeRepsOverride", config["encodeReps"])` (it also takes the number itself), is the only way the engine reads `encodeReps` for a card:
  - `session._grade_and_advance`: the full stage, the combine windows (`required_reps_for_window(…, reps_for(it, config))` in cumulative mode, `reps_for` on every window in exhaustive mode), and remediation; the "N of M streaks" feedback says the card's M;
  - `estimate.compute_minimum_trials` (so `compute_cumulative_cold_start_multiplier` and `compute_remaining_cold_start_range`, which call it, follow);
  - `progress.compute_item_progress` (so `compute_session_progress` follows).
  The session-level reads that are about the session, not a card, are unchanged: `history.build_history_entry`'s `config.encodeReps`, `history_store.encode_settings`, the controller's save (`encodeReps`), `sessions.resume`.
- `items.min_words_for(item, session_T)`: `build_item(…, overrides)` chunks with the card's threshold (the override wins over the session value from Phase 5); `edit_current_item` uses it for both its rechunk check and its restart rebuild.
- `build_items(…, overrides=[…])` and `build_item(…, overrides)` store the fields on the item. `normalize_item` threads both through (a resumed card keeps them). `edit_current_item`'s restart path keeps them (`items.item_overrides(old)`): a rebuilt card is the same Anki card.
- Who sets them: `difficulty.adjust_card` (see "Difficulty adjustment"), through `build.BuildResult.adjustments` (a side table parallel to `deck_items`) → `launch.start(…, overrides)` → `sessions.new_session_state` → `build_items`. A drill-again session copies the parent items' overrides (`DrillController.drill_again_overrides`).
- Proof: the golden and simulate parity suites pass unchanged (they never set the fields); `tests/engine/test_difficulty_overrides_ext.py` checks a full card needing its own reps, the final combine window (cumulative) and every window (exhaustive), remediation, an edit restart and an in-place edit keeping both fields, progress, and `compute_minimum_trials` with mixed overrides equal to a perfect `simulate()` run's `attempts` (the `coldStartEstimate.consistency.spec.ts` rule, 4 decks × reps 1/3/5 × both ladders); `tests/storage/test_sessions.py` and `tests/anki_io/test_difficulty_build.py` check save, resume and drill-again.
- `tools/simulate.py` is unchanged by default (byte-identical to `npm run simulate`). `--difficulty-overrides` adds a **Python-only** section: the scoreboard's decks and learners with cards 0–3 at +1 (one more rep, T − 2), 4–7 unchanged, 8–11 at −1.

## Difficulty adjustment (Phase 6)

Cards that already have review history have an FSRS difficulty. `recalldrill/difficulty.py` (pure) turns it into the engine's per-card overrides. **New cards, most of what gets drilled, have no FSRS data and are unchanged**: they keep the word-count and `chunkDifficulty` rules exactly. The `chunkDifficulty` model and remediation are untouched.

- **Input:** a `CardSnapshot` (`card_state.py`, pure; `anki_io/cards.py` re-exports it), whose `fsrs_d` (1–10) and `fsrs_s` (days) come from `card.memory_state` directly. The 0–1 `prop:d` search scale is never used.
- **Settings** (`config.json`; defaults): `difficulty_adjust` **true** (each deck's "Adjust reps by difficulty" toggle, `deck_settings` key `difficultyAdjust`, wins), `hard_d` **7**, `easy_d` **3**, `min_encode_reps` **2**, `hard_chunk_shift` **2**, `skip_min_stability` **30**, `skip_max_difficulty` **5**.
- **Rules** (first match wins; R = the deck's reps, T = the session's threshold):

| Card | Reps | Threshold |
|---|---|---|
| FSRS, `D ≥ hard_d` | R + 1 | `max(4, T − hard_chunk_shift)`, never above T |
| FSRS, `D ≤ easy_d` | `max(R − 1, min(min_encode_reps, R), 1)`: a deck at 1 stays at 1 | T |
| FSRS, otherwise | R | T |
| No FSRS, `reps > 0`, and `lapses ≥ 3` or `0 < factor < 2000` or tag `leech` | R + 1 | T |
| No FSRS, `reps > 0`, otherwise | R | T |
| New card (`reps == 0`, no FSRS) | R | T |

  Only values that differ from the session's become overrides. With FSRS present, only D counts (lapses and the leech tag don't add a rep).
- **The `stable` class** (`classify`, right after `leech`): FSRS present, `S ≥ skip_min_stability`, `D ≤ skip_max_difficulty`, not tagged `leech`. Off by default in selection (the §7.1 trial saver): the panel counts the stable cards it skips. Ranked after `young` when switched on.
- **Panel:** in the card section, "Difficulty-adjusted: X cards +1 rep, Y cards −1 rep, Z cards chunk earlier. New cards (N): no FSRS data, unchanged." and, when any are skipped, "Stable: K cards skipped (…). Tick “stable” to drill them." The toggle sits with the deck's settings.
- **History:** each card of the session line's `anki` block also records `d`, `s` (None without FSRS), `encodeReps` and `minWordsToChunk` (what the card was drilled with) and `adjust` (+1 / 0 / −1 against the session's `encodeReps`).
- **Tuning report** (`tuning.py`; the prompt said `measure.py`, but the breakdowns and suggestions live in `tuning.py`, and `measure.py` stays the metric alone): a card's `encodeReps` is its own (older lines: the session's), so the `encodeReps` breakdown and suggestion use the **effective** reps per card; a new breakdown "adjustment (+1 / 0 / −1)"; the CSV gains an `adjustment` column.

## Measurement and holdout (Phase 5)

**Decision (Don, 2026-10-02, revised before merge): holdout off by default, with a per-deck control.** `config.json` and the code both default `holdout_pct` to **0** (off). Each deck turns it on with **Holdout %** (0–50) in the setup panel's card section, saved with the deck's other settings (`deck_settings.json`, `holdoutPct`); the config value is only the default for decks without their own. (The first decision was "on at 15%" in `config.json`; replaced.)

The success metric for the add-on is the **next-day Again rate** on drilled cards. Cost (trials per card) is always shown next to it, because fewer trials is still the priority.

### One metric (`recalldrill/measure.py`, pure)

- **Anki day** of a time: the local date after subtracting the rollover hour (`col.get_preferences().scheduling.rollover`). One function, `anki_day`, for everything. Local means the machine's time zone, as Anki's.
- **Counted rating:** a revlog row with `ease ≥ 1` and `type` 0, 1 or 2. Filtered/cram (3), manual (4, e.g. `set_due_date`'s row) and rescheduled (5) rows don't count, nor do `ease 0` rows.
- **Drilled card:** `t0` = its handoff (`type: "handoff"` line's `timestamp`). Outcome: the first counted rating on an Anki day after `day(t0)`.
- **Holdout and baseline card:** `t0` = its first counted rating (its introduction). Outcome: the first counted rating on a later Anki day.
- **Again** = `ease == 1`; `elapsed = day(rating) − day(t0)`.
- **Primary analysis:** `elapsed ∈ {1, 2}`. Larger gaps are reported as excluded ("rated later than 2 days", e.g. new/day spill). **Pending** cards (no outcome yet) are counted and never treated as successes.

### The holdout

- **Settings:** per deck, `holdoutPct` (0–50, setup panel **Holdout %**), defaulting to config `holdout_pct` (0); `holdout_exclude` (true, global). The salt is a random hex (`secrets.token_hex(8)`) made the first time a selection runs with the holdout on, in `user_files/profiles/<profile>/holdout.json`.
- **Assignment:** `int(sha1(f"{salt}:{cid}").hexdigest()[:8], 16) % 100 < pct` (`holdout.is_holdout`), with the deck's %. Deterministic: a card's status only changes when the % does, and then only from that session on (raising the % keeps every card already in, adds more; lowering it releases some). Cards already handed off as holdout keep `rd::holdout` and stay out of future drills (`holdout_exclude`), whatever the % is now.
- **Who can be held out:** classes `new` and `suspended_new` only, **deck scopes only** (never a search such as `tag:rd::hard`; drill-again never selects).
- **Selection:** `apply_holdout` walks the ordered eligible list, putting holdout cards aside, until `max_cards` **drill** cards are picked.
- **Rules added on top of the prompt** (to keep the control clean):
  - a note already tagged `rd::drilled` or `rd::holdout` is never held out (its sibling was drilled, or it is a past control);
  - a held-out card whose note also has a picked drill card is dropped from the holdout (and not drilled): the assignment is per card, as the prompt specifies, so a two-direction note can split. It goes to Anki as that drilled card's sibling, and the next selection drills it (its note is then `rd::drilled`).
- **Panel:** in the card section, for deck scopes, "Holdout: K cards skip the drill and go to Anki as new cards (measurement control)." next to the **Holdout %** spin box; K is recounted (the panel's usual 300 ms refresh) as the % changes. At 0: "Holdout: off". Search scopes show neither (they never hold cards out). Cards tagged `rd::holdout` are left out and counted ("N cards tagged rd::holdout left out").
- **Save and history:** `addon.holdout` in the save and `holdout` in the session line (`cid, nid, ord, did, card_class`). At handoff, the `holdout` and `holdout_siblings` groups (see the handoff table): a holdout note enters Anki exactly like a drilled note except for the drill (unsuspended, queued after the drilled cards and their siblings, buried until tomorrow, siblings by the same rule), plus the note tag `rd::holdout` (no `rd::drilled`). A held-out card that is gone or no longer new at handoff is left alone (`holdout_skipped`).
- **Later selections** leave `rd::holdout` notes out while `holdout_exclude` is on. With it off they can be drilled, and they are never held out a second time.

### The tuning report

Tools → **Recall Drill: tuning report** (`ui/tuning_dialog.py`). `anki_io/revlog.py` reads: every history line, the drilled and holdout cards plus every card of their top-level decks (`deck:"<top>"`), their home decks, and their revlog (`select id, cid, ease, type, ivl, time from revlog where cid in (…) order by id`, ≤ 500 ids per query). `tuning.build_report(history_lines, revlog_rows, deck_filter, cards=…, rollover=…)` is pure; the dialog renders it.

- **Header:** scope, number of sessions and their date range, drilled cards with outcomes / excluded / pending (and the holdout's), and the confound warning, verbatim.
- **Comparison:** drilled vs holdout vs **baseline** = cards in the same top-level decks (of the drilled cards, after the filter), not drilled or held out by the add-on, whose introduction predates the first add-on session (`startedAt` of the earliest session line). Columns: n (primary outcomes), Again, Wilson 95% CI, trials/card and misses + reveals/card (drilled only, per handed-off card).
- **Breakdowns of drilled cards:** answer words (1, 2–3, 4–8, 9–15, 16+), chunks (none, 2, 3, 4+), `encodeReps`, card class, handoff mode, deck (home deck). Each: n, Again with CI, trials/card, pending.
- **`min_n`** (config, default 30): a group under it shows "n too small" in place of a rate, and no suggestion is made from it.
- **Deck filter:** one top-level deck, or all.
- **Copy as CSV:** the per-card outcome table (group, ids, deck, session, t0, status, rating time, elapsed, ease, again, words, chunks, encodeReps, class, mode, attempts, misses, reveals, final misses).

**Suggestions** (rule-based, at most one per parameter, always shown with the numbers that triggered them):
- `MIN_WORDS_TO_CHUNK` (T = config `min_words_to_chunk`): unchunked cards with `words ∈ [T−3, T]` vs chunked cards with `words ∈ [T+1, T+4]` (chunked = the session actually chunked them). Unchunked CI lower bound above the chunked CI upper bound → **T − 2** (at least 1). CIs overlap and chunked cards cost ≥ 25% more trials per word (total attempts / total words per group) → **T + 2**. Otherwise no change. Either group under `min_n`: no suggestion. Always with: *"These groups differ in answer length, not just chunking; treat this as a hint, not proof."*
- `encodeReps` (current = config `encode_reps`): only when ≥ 2 values each reach `min_n`. The suggestion is the **lowest** such value that is not significantly worse (its CI lower bound above the upper bound) than any higher one: a lower value whose CI overlaps a higher one's wins (fewer trials); a significantly worse lower value loses to the higher one. Otherwise "insufficient variation". Since Phase 6 the values are per card (the difficulty adjustment's effective reps), which is what creates the variation.

**Apply** (per actionable suggestion): a confirmation shows old → new, the verdict, the evidence and the caveat; for `encodeReps` it also lists the decks whose saved "Blind typings required" differs (a deck's saved value wins over the default). Yes writes the add-on's global default through `addonManager.writeConfig` (`min_words_to_chunk` or `encode_reps`) and appends `{"type": "tuning", "timestamp", "parameter", "configKey", "old", "new", "verdict", "evidence", "deckFilter"}` to `history/tuning.jsonl`. Nothing changes without that click and confirmation. New values apply to sessions started afterwards.

**Known limitations:**
- The baseline is not an Anki-only baseline (the confound warning says so), and drilled cards aren't randomly chosen: only drilled vs holdout is a fair test.
- Drilled and holdout outcomes are not the same event: a drilled card's outcome is its first Anki rating after the drill (B: its first learning step the next day); a holdout card's is its first rating on the day after its introduction. That is the definition chosen in the prompt.
- Cards deleted since show as "(deleted card)" (their revlog stays), so a deck filter drops them.
- The Wilson CIs treat cards as independent; repeated drills of one card count once per handoff.

## Pacing (Phase 6)

Pace a deck to a target date (a chapter exam), as the medterm routine does: drill on the chosen weekdays, finish at least a day early. `recalldrill/pacing.py` (pure) does the arithmetic; `recalldrill/anki_io/workload.py` reads the collection; the setup panel's **Pacing** section (deck scopes only) shows it.

**Overlap with `medterm-daily-drill`:** this replaces the skill's pace calculation for anything drilled in the add-on. The skill itself is unchanged.

- **Settings** (`pacing.json`, by deck id, saved as soon as they change): `target_date`, `drill_weekdays` (default Mon–Fri), `finish_days_before` (default 1).
- **Remaining** (`Selection.pace_remaining`, counted whatever the class switches and Max cards say): the scope's eligible `new` + `suspended_new` cards that pass the template filter, excluding notes tagged `rd::drilled` or `rd::holdout`. `pace_suspended` is the suspended part; `pace_siblings` the suspended new cards the template filter left out whose note has a remaining card (they go to Anki with it).
- **Drill days left:** the drill weekdays from today through `target_date − finish_days_before`. Today counts unless a session in this scope **completed** today (a `type: "session"` line whose `finishedAt` is on today's Anki day).
- **Today's N** = `ceil(remaining / days_left)`. Edge cases, each a test: no target; **target passed** ("pick a new date"); **today not a drill day**, or **already done** (today's N is 0; the next drill day and its N are shown); **zero remaining**; **`days_left == 0` with cards left** ("Behind: N cards, no drill days left").
- **"Use N as max cards"** fills Max cards with N.

**Time figures: only measured data, each labelled with its source.** The web app's cold-start estimate (fixed multipliers, the exposure picker) isn't based on Don's data, so the add-on no longer shows it: the setup panel's "about N–M min" and exposure picker are gone (`tests/test_layering.py` checks that nothing shown imports `engine/estimate.py`, which stays for the parity tests), and the batch interstitial's remaining time is now this session's own active time per card × the cards left.

- **Active drill time** (`controller.py`): the time between consecutive actions (submit, reveal, continue, override, next batch), each gap capped at config `idle_cap_seconds` (120). The clock starts when the window starts the session and stops at Save and stop, so a gap across a saved or closed session never counts. Each gap also goes to the answered card (next batch: the session only). Saved as `addon.activeMs` / `addon.activeMsByItem`; the session line gets `activeMs` and per card `anki[i].activeMs`. Older lines have none and are ignored for timing.
- **Drill minutes:** the median active seconds per drilled card over the last 10 timed sessions **in this top-level deck** (a line's deck: where most of its cards live), by answer shape (chunked vs whole; a shape with no timed card takes the overall median). Needs ≥ 3 timed sessions in the deck; else the timed sessions of all decks (labelled "all decks"); else "no estimate yet (needs 3 timed sessions)". The next N cards' shapes come from the panel's build (overrides included).
- **Anki minutes** (tomorrow, and the peak day with its date):
  1. **FSRS simulator** (`col._backend.simulate_fsrs_review`, the deck options' Simulator). Request: the preset's FSRS params (`fsrsParams6`, else `fsrsParams5`) and desired retention, `search` = the deck, `new_limit` = the planned new cards per day (N + siblings at the scope's ratio, + the holdout share under B), `deck_size` = the remaining suspended cards + their siblings, the deck's review limit, `days_to_simulate` = drill days left + 14, the preset's learning and relearning step counts, max interval, review order, easy days, historical retention, leech suspension.
  2. **Revlog fallback:** the median `time` of Don's review (types 1, 2) and learning (type 0) ratings over the last 30 days in the top-level deck; per day, the reviews due (`prop:due=N`; tomorrow also counts learning cards due by then) × the review median, plus the cards handed off the day before × learning ratings per new card (measured) × the learning median.
  3. Fewer than 50 ratings: "no estimate yet".
- **Facts checked on 26.08.1** (`tests/anki_io/test_workload.py`):
  - `daily_time_cost` is **seconds** per day; every list has `days_to_simulate` entries; **index 0 is today** (the panel shows index 1 as tomorrow).
  - **Suspended new cards are not simulated**; `deck_size` adds new cards on top of the search's unsuspended ones.
  - The total cost grows with `new_limit`.
  - **The time cost is from the revlog, blended with built-in defaults** (fsrs-rs 6.6.1 `extract_simulator_config`, read in its source): each (state, rating) cost is `w · mean(Don's times) + (1 − w) · default` with `w = n / (50 + n)`; no revlog: the defaults. The test shows the same deck costing more with 60 s ratings than with 2 s ones, and 3 slow ratings barely moving it. So the simulator figure is shown only with **≥ 50 learning and ≥ 50 review ratings** in the deck; otherwise the panel says it would fall back on Anki's default times and goes to (2).
  - Anki's simulator computes and **stores** a memory state for a searched review card that lacks one (e.g. handed off under A with `set_due_date`), exactly as the deck options' Simulator does. That's the only write a panel read can cause.
  - The simulator introduces new cards **every day**, not on drill weekdays only, so its new-card days run a little ahead of a Mon–Fri plan.
- **Ceiling check** (warn with the number held back, never block), on the top-level deck as in the Phase 4 forecast: under **B**, tomorrow's new cards (N + siblings + holdout share) against its new/day; under **A**, N against the room left in its review limit after tomorrow's due reviews (the forecast's `prop:due=1 OR (is:learn prop:due<1)` count).
- **No daily time budget or minute threshold:** the minutes are information only.

## Changing the engine now

Since Phase 1b the Python engine (`recalldrill/engine/`) is a step-for-step port of the TS engine (`src/utils/`), and CI holds the two together. The `addon-engine` job regenerates `tests/golden/` from the TS engine and fails if anything changed (`git diff --exit-code`). So a change to engine behavior is one commit with four parts:

1. Change the TS engine (and its vitest specs).
2. Regenerate the goldens from the repo root: `npx tsx anki-addon/tools/export_golden.ts`.
3. Port the same change to the Python engine.
4. Both suites green: `npm run lint && npm test` and `pytest anki-addon/tests`.

A TS change alone fails the drift guard. Regenerated goldens without the Python change fail the parity tests. To chase a mismatch in a seeded `simulate()` run, `npx tsx anki-addon/tools/export_golden.ts --full <deck>:<learner>[:<run>]` and `python anki-addon/tools/simulate.py --full <same>` write that run's full state after every step to the gitignored `tests/golden/_debug/`, one line per step; diff the two files. A behavior the add-on adds on top of the TS engine goes under "Engine extensions" above, with its own tests, not into the goldens.

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
4. Answered 2026-10-01 (see the decisions above).
5. Optional, for the bury question: in a throwaway deck, bury a card by hand (Browse → Toggle Bury), and check the next day (after Anki's next-day rollover, Preferences → Review) that it's back.
