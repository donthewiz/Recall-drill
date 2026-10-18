# mathpath-addon/: Math Path add-on

Loads when you work in this folder. The full record is `docs/DECISIONS.md`; the recipe
format is `docs/recipe-format.md` (a copy of the anki-math-cards plugin's reference).

## What it is

A separate add-on (package `math_path`) that teaches problem types from the
anki-math-cards skill's JSON **recipes**: a learn session (Study → Faded → Plan → Solo),
then Anki reviews, where each review opens one fresh problem and rates the card by how it
went (no help = Good, hint only = Hard, a wrong try or a shown step = Again). It imports nothing from
Recall Drill. Anki is the only scheduler: Math Path never sets a due date or interval, and
hands off with handoff B.

## Layout and layers (`tests/test_layering.py`)

| Part | Rules |
|---|---|
| `math_path/*.py`, `math_path/views/` (top level) | Qt-free **and** Anki-free. Strict pyright |
| `math_path/anki_io/` | May import `anki` and `aqt.operations`, never Qt |
| `math_path/ui/` | Qt. Standard pyright. Style only Math Path's own windows |
| `core/` | Copied unchanged from the anki-math-cards plugin (`core/SOURCE.md`, hashes tested). **Never edit** (hook-blocked); fix bugs in the plugin, work around them in Math Path's own code. To update: copy the new plugin files in with a shell command, then update the hash table in `core/SOURCE.md` |
| `vendor/` | SymPy and mpmath that ship with the add-on. They are **not** installed in the venv on purpose (a test checks no system SymPy is on the path), so a part the trimmed vendor lacks fails a test, not Don's Anki |
| `web/` | The page (MathLive palette, KaTeX fonts) served through `setWebExports` (`pages.web_pattern()`) |

`core/`, `vendor/` are outside ruff, pyright and coverage.

## Things that bite

- **The palette adapter:** the click palette gives MathLive LaTeX; Recall Drill's reader
  turns it into a keyboard form that `core/`'s checker doesn't read. `math_path/palette.py`
  bridges the two. Any change to answer parsing must pass the palette path test
  (`tests/engine/test_palette_path.py`) on every Chapter 3 recipe, not only typed text.
- **Anki keeps only 30 undo steps.** Writes are bulk (`col.add_notes`, `update_notes`, one
  `suspend_cards`, one `bury_cards`) inside one custom undo entry (`anki_io/undo.py`).
- **The reviewer hook** (`reviewer_did_show_question`) also fires for the next card after
  an answer; a stale window is closed there. Rating goes through `_showAnswer()` then
  `_answerCard(ease)`, only when `mw.reviewer.card.id` is the card (`ui/review_bridge.py`).
- **The `webview_did_receive_js_message` filter** sees every web view's messages: pass on
  anything that isn't Math Path's own, unchanged.
- **Speed:** `math_path/fastgen.py` pre-filters numbers before any SymPy call;
  `tests/engine/test_speed.py` guards it. Keep problem generation well under a second.

## Tests

- From the repo root: `mathpath-addon/.venv/bin/python -m pytest mathpath-addon/tests/<path> -q`.
  The whole suite takes about 5 minutes in the cloud; run the related folder while working
  and the whole suite once before the final push.
- Recipe fixtures: `tests/fixtures/recipes/ch03/` (30 College Algebra Chapter 3 recipes) and
  `v2_examples/`. Every change to grading or generation should pass all of them.
- The web pages are tested in real Chromium by Playwright (`tests/ui/page_harness.py`, from
  `file://` URLs); the Qt windows with a stand-in web view. Those tests skip themselves when
  `aqt` or a browser is missing; say so in the report if they skipped.
