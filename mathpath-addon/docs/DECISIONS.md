# Math Path: decisions and facts

Everything here is a decision (by Don, 2026-10-16/17, or made while building and flagged **built**) or a fact checked against the installed `aqt`/`anki` 26.8.1 source. The recipe format is `docs/recipe-format.md`; the copied checker is described in `core/SOURCE.md`.

## Why

Don's College Algebra tests (Bittinger, *College Algebra: Graphs and Models*, 7e; MyMathLab) are solved by calculation, so flashcards alone aren't enough. The **anki-math-cards** skill writes, per textbook section, Anki cards (drilled in Recall Drill) and **problem recipes**: one JSON file per problem type that generates fresh-number problems with checked steps, hints, named mistakes and the answer's required form. Math Path is where those problem types are learned and practised. It is a **separate add-on** (`mathpath-addon/`, package `math_path`, name "Math Path"), for any math-type course, and works without Recall Drill (nothing is imported from it; what was useful was copied). **Anki stays the only scheduler.**

How it works (Don's decisions):

1. **Learn session first, then Anki.** A section's recipes wait as **suspended** notes. A learn session takes each through Study → Faded → Plan → Solo, then hands it to Anki. After that, every time Anki shows the card, Math Path gives **one fresh problem** and rates the card from how it went.
2. **A Math Path window**, like Recall Drill's drill window: it opens by itself when a Math Path card comes up in the reviews; when finished it rates the card and goes back to the reviewer.
3. **v0.1 is the solving loop and the progress map.** Not in v0.1: a drawn graph tool (a graph answer is typed: a shape and two points), test mode, TI-84 checks, two methods side by side, find-the-mistake problems.
4. **Typing is how Don memorizes.** Math is entered with a **click palette**; no symbol ever needs a keyboard shortcut. Letters and digits come from the keyboard.
5. Don works problems **on paper**. The window checks what is typed; it doesn't ask for every line, except in the stages built for that (Faded, Plan).

Settled and never changed here: Recall Drill changes only in commit 1 (v0.6.1); Anki is the only scheduler (Math Path never sets a due date or interval; it rates through the reviewer and hands off with **handoff B**); deck options are never changed; notes that aren't Math Path notes are never touched (Recall Drill tags are only *read* for the progress map); only Math Path's own windows are styled, never `QApplication.setStyleSheet` (a test checks it).

## Versions and tooling

- Anki 26.08.1; the add-on targets its bundled Python 3.13.13 (`manifest.json` `min_point_version` 260801).
- Dev: `anki==26.8.1`, `aqt==26.8.1` (type-checking `ui/`, Qt tests), `pytest==9.1.1`, `ruff==0.16.10`, `pyright==1.1.414`, `playwright==1.56.0` (`requirements-dev.txt`). **SymPy and mpmath are not installed in the dev venv or in CI on purpose**: the tests run on the copies in `vendor/` (the ones that ship), so a SymPy part the trimmed vendor lacks fails a test, not Don's Anki. A test checks that no system SymPy is on the path.
- Layering (`tests/test_layering.py`): the top-level modules of `math_path/` and `views/` are Qt-free **and Anki-free** (strict pyright); `anki_io/` may import `anki` and `aqt.operations`, never Qt; `ui/` may import anything and is at standard pyright (PyQt6's stubs leave signals partly Unknown). `core/`, `vendor/` are outside ruff, pyright and coverage.

## API facts (checked in the installed 26.8.1 source, or on a scratch collection)

| Item | Fact | Consequence |
|---|---|---|
| Reviewer hook | `gui_hooks.reviewer_did_show_question(card)` runs at the end of `Reviewer._showQuestion`, after `state = "question"` and the web `eval` | The window opens from it. It also fires for the next card after an answer, so a stale window (another card) is closed there |
| Answering | `Reviewer._answerCard(ease)` returns unless `mw.state == "review"` and `reviewer.state == "answer"`; `_showAnswer()` sets `state = "answer"`; the answer ends in `_after_answering` → `reviewer_did_answer_card` → `nextCard()` | Rating = `_showAnswer()` if the reviewer is still on the question, then `_answerCard(ease)`. Same timer, revlog row (type and ease) and undo as pressing the button; the reviewer moves on by itself. Only when `mw.reviewer.card.id` is the card (`ui/review_bridge.py`) |
| Card-face link | The card's own `pycmd` reaches `webview_did_receive_js_message` (a filter `(handled, message, context) -> (handled, result)`); for the reviewer's web view `context` is the `Reviewer` | `pycmd('mathpath:open')` is handled there. The same filter sees **every** web view's commands, including Math Path's own `mp:` ones, so it must pass anything it doesn't own through unchanged |
| Web exports | `mw.addonManager.setWebExports(module, pattern)` keeps **one** regex per add-on, matched with `re.fullmatch` against the path after `/_addons/<folder>/` (so `web/mp_page\.js`); the folder is the add-on's folder name (`math_path` or the dev junction) | `pages.web_pattern()` lists the page's files and MathLive with its `KaTeX_*.woff2` fonts; nothing else is served. MathLive finds its fonts from the script's own URL |
| `AnkiWebView.stdHtml` | `css`/`js` entries starting with `/` become `http://127.0.0.1:<port><path>`; others `/_anki/<path>`. `eval` is queued until the page has loaded | MathJax is Anki's own (`js/mathjax.js`, `js/vendor/mathjax/tex-chtml-full.js`); the page's scripts are `/_addons/<folder>/web/...`. `mp.render` can be called right after `stdHtml` |
| QtWebEngine offscreen | `QtWebEngine` can't start on Qt's offscreen platform (the process exits) | The window tests use a stand-in web view that records `stdHtml` and `eval`; the page itself is drawn in real Chromium by Playwright (`tests/ui/page_harness.py`) from `file://` URLs, with Anki's MathJax from the installed `_aqt` package |
| `QDialog.closeEvent` | calls `reject()` (which is also Esc) | `PageWindow.closeEvent` accepts the event itself, and `reject()` is "Esc": it closes a dialog, and only closes the help text in the learn and review windows |
| Undo | `col.add_custom_undo_entry(label)` … `col.merge_undo_entries(pos)` makes several writes one step; **Anki keeps only 30 undo steps**: a step made of more than 30 separate ops loses its start and `merge_undo_entries` fails with "target undo op not found" (seen with 30 `add_note` + `suspend` calls) | Writes are bulk: `col.add_notes([AddNoteRequest…])`, `col.update_notes`, one `suspend_cards`, one `bury_cards`. Each backend call commits on its own, so a failure merges what ran into the step and undoes it (`anki_io/undo.py`) |
| Handoff calls | as Recall Drill's DECISIONS: `unsuspend_cards` unburies too (pass only suspended cards, before burying); `reposition_new_cards` gives one position per note; `bury_cards(manual=True)` changes only `queue`; a manually buried card returns at the next rollover (a test moves `col.crt` back a day, as rslib's own test does) | Handoff B in `anki_io/handoff.py` |
| `CollectionOp(parent, op)` | `op` must return something with `.changes` (an `OpChanges`) | The import and the handoff return a small result object carrying it |
| Queue | `get_queued_cards` serves the *current deck's* new cards | Tests select the course's deck before answering through the backend |
| Tags | `tag:rd::drill` matches `rd::drill` and its children (`rd::drill::A1`), not `rd::drilled`; `tag:rd::*` would match every `rd::` tag | The Recall cell counts `rd::drill`, `rd::drilled`, `rd::undrilled`, with exact-tag searches |

## The adapter (why `palette.py` exists)

The click palette gives MathLive's LaTeX. Recall Drill's reader (`latex_to_keyboard`, copied in `core/drill_check/math_parse.py`) turns that into **Recall Drill's own keyboard form**, which is not the form `verify_math` (the checker) reads: it wraps every group in the private-use characters U+E200 / U+E201 and writes a union as the symbol "∪". Fed straight to the checker, every fraction is graded wrong, and a plain `sqrt((8))` slips past the "simplified" form check. `math_path/palette.py` is a pure adapter on the Math Path side (`core/` is never edited):

- groups come back as ordinary parentheses, and a lone atom `(x)` / `(3)` loses its parentheses; double parentheses collapse;
- "∪" becomes " U ", which the checker reads as a union;
- `\lor` / `\vee` (what MathLive makes of the letters "or" typed in a field) becomes " or ";
- identifiers glued to a function call (`isqrt(448)`, the imaginary unit then a root) are written out as a product (`i*sqrt(448)`); real function names are left alone;
- `\frac{6}{8}` stays "(6/8)", as before, so that a form check can see it is unreduced.

`tests/engine/test_palette_path.py` runs the whole **palette path** (LaTeX to adapter to checker) on every Chapter 3 recipe and the v2 examples, not only the typed-text path.

## Decisions the brief did not settle (built, flagged)

**Importing and notes**
- Section decks: when several decks match a section number, only those with the recipe's course in their path are kept; none or still several means the import dialog asks (default: skip).
- Writes are bulk (`add_notes`, `update_notes`, one suspend, one bury) because of Anki's 30-step undo list (see above). A failure merges what ran into one undo step and undoes it.
- The `Recipe` field is compact ASCII JSON, HTML-escaped, so no editor round trip changes it.

**The learn session**
- Study moves on by itself: there is no result screen after Study.
- Faded: steps that can't be blanked are shown worked before the first blank and name-only after it. A wrong step counts as a wrong answer for passing the level.
- Plan: Enter moves to the next box and checks on the last; there is no cap on tries.
- **Spacing, one recipe left:** two unaided solos on one recipe must have another problem between them. With a single recipe left in the session (or a gap that spans sessions, where the time since is certain) the second solo may follow directly: the rule is waived rather than leaving the session stuck.
- "Gave up" means Show answer. The checker's `fill` turns "oo" into "inf" in typed text (a quirk, kept).
- The handoff question has a third option, **Not now**. Recipes learned but not handed over (window closed, handoff failed) are carried into the next session through `pending` and offered again.
- Natural sort for section order (`3.10` after `3.9`).
- `answer_solves` is read as equality with the wrong equation's solutions. A `form_violation` mistake is also shown on "right value, wrong form".
- A graph answer is typed: shape plus two points.

**Reviews**
- One history line per finished problem, written at Next or when the window closes.
- If the reviewer has moved on while the window was open, nothing is rated and the window says so.
- Rating suggestion: Again if the answer or a step was shown or there was any wrong try (even if then fixed), Hard after a hint/why only, Good otherwise. **Easy is never automatic.** *Don, 2026-10-17: a wrong try that is then fixed is Again; this supersedes the first version, where a wrong try was Hard.*

**The progress map**
- Recall counts include `rd::drill::*` children. The amber line before Learn is a question (Learn anyway / Cancel), never a lock.
- The window re-reads everything on every Anki operation and on Refresh (the learn window has its own store).
- Learn next also exists in the menu.

**Display**
- Inner-scroll layout (header, scrolling body, palette, footer) instead of sticky bars.
- Only Math Path's windows are styled, by the page's own CSS.

## Found in review (2026-10-17)

- **A list answer written with the variable is right:** `x = -5/2, x = -9` reads as `-5/2, -9` (`grading.drop_var_labels`), for answer kinds `list` and `expr` and for "solutions" steps. Only when every piece is `<var> = <value>` with no other relation; `y = …`, a half-labelled list or `x < 3` are left as typed. The equation kind (an axis, `x = 3`) is never touched. Before this, the labelled form counted as a wrong try (Hard in a review, back to Faded in a session).
- **Commas between equations in an "each" step:** `2x+5=0, x+9=0` reads as `2x+5=0; x+9=0` (`grading.commas_between_equations`), because the palette has a comma button and no semicolon. Only when every comma-separated piece is one equation.
- Tests: `tests/engine/test_labels_and_commas.py` (every list recipe, 5 instances, keyboard and palette path; every "each" step); 20 of its 23 tests fail without the change.
- **Math fields can be typed in (bug #11, first check in Anki):** `PageWindow._on_bridge` redrew after every page message, and `mp.render` replaced `root.innerHTML`, so each `<math-field>` was rebuilt from Python's copy of its value (a keystroke behind); `focusId` then refocused the new field, its `focusin` sent `mp:focus` again, and the loop dropped keys, palette presses and Enter. The offscreen tests never had real focus events or a round trip.
  - **The keep rule:** `pages.KEEP_KINDS = ("focus", "field", "text")`. After one of these, the window calls `redraw(keep=True)`; `pages.redraw_call(view, keep, last)` (one pure function, used by the window and the browser test) sends nothing when the shown `(html, readonly, night)` is unchanged and otherwise sends `mp.render` with `"keep": true`. Every redraw that is sent updates the remembered value. Any other command, a timer, a theme change or the handoff is a full redraw, exactly as before (a new problem starts with empty fields). `select` stays full: it changes the screen.
  - **Page side:** in a keep render, live fields and text boxes are moved into the new HTML as the same elements and Python's values are not written into them. The focused one is never taken out of the page (`morphAround` swaps the new siblings around it level by level; if the new screen has no twin at the same depth it falls back to a rebuild): detaching and reattaching a focused MathLive field keeps its value but drops keys typed in the next ~60 ms. Focus returns synchronously. A keep render with `keep` false does what it did before.
  - Visible effects of focus/field/text (the step row's ` now` class, a step's "Not right yet." note cleared by `set_field`, the verdict cleared) still show, because the changed HTML is sent as a keep redraw.
  - Tests: `tests/ui/test_typing.py` (real Chromium, real focus, an async `pycmd` round trip into `LearnSession.command`, including a whole Faded problem from `ca.cx.express_i`) and two in `tests/ui/test_ui_smoke.py`.

## Fix bundle v0.1.1 (Don's first real Anki check, 2026-10-17; built 2026-10-18)

- **Rating (Don, 2026-10-17, supersedes "wrong try = Hard"):** a wrong try that is then fixed is **Again**. `review.suggested_rating`: shown step, shown answer or any wrong try is Again; hint/why only is Hard; clean is Good. The done screen's wording ("Right after a wrong try.") still fits.
- **Partial-answer feedback (#3), Claude's wording:** for a `list` answer with two or more values, a wrong answer with at least one right value says `Not right yet: you have 1 of 2 solutions; there is another.` (everything typed is right, something is missing; `there are N more` for more than one) or `Not right yet: 1 of your 2 values is right.` (something typed is wrong; `are` for more than one). It never says which piece. A wholly wrong answer is still `Not right yet.`; a right value in the wrong form and a named mistake are as before. Only `AnswerVerdict.partial` (words) is new: `ok`, `value_ok` and `counts_as_try` come from the checker unchanged. Answers with a rounding rule (`places`) and one-value lists get no counting.
- **Map order (#5):** one function, `session.learn_order`, orders notes for the learn session (`pick_for_session` filters, then calls it) and for the map (`build_map` calls it for all of a section's notes, learned or not, a broken one as the first free slot by note order). NEXT is unchanged.
- **"each" step (#8):** `grading.check_step_keyboard` now also needs as many `;`/`,`-separated equations as the step's expected result (so `(x+2)(x+3)=0` for "set each factor equal to 0" fails; `x+2=0, x+3=0` passes in either order). The core's `each` check accepts anything with the same solutions and stays as is (**the plugin should check the equation count itself**).
- **No leading 1 (#12), Claude's call:** the recipe template `{s} sqrt(-1) sqrt({n})` fills `{s}` with 1, which is the plugin's recipe, so `display._tidy` fixes what is shown: a regex drops a `1` that is a multiplier only (preceded by the start, a space or an operator, not by a digit, `.`, `^`, `/`, `-`, `)`; followed by a letter or bracket, never `1/2`, `1.5`, `10`, `1^2`, `(1+x)` or `-1`). It runs for every step, answer, hint and message (all of them go through `kb_html` / `kb_math_html`). Two radicals side by side get a dot (`√−1·√108`). Prompts are not touched.
- **Imaginary notation (#13), Claude's call, Don to confirm with Bittinger's Video Notebook:** `6i√3`, not `6√3i` (`display.i_before_radical`, one small function: drop its call in `_tidy` to undo). Display only: `7√10i`, `7i√10` stay right; `i√490` is still the right value in an unsimplified radical form, as before.
- **Palette keys (#15):** `[ ( ) ]`. The old order `[ ) ( ]` came from Recall Drill v0.6; nothing in the code gives a reason for it (the tooltips say "closed end" / "open end" only). Tests look keys up by name. Recall Drill is unchanged.
- **Answer box under the palette (#14):** could not be reproduced in Chromium: the palette and button bar are flex siblings below `.mp-main`, which already ends above them (`tests/ui/test_layout.py` checks the geometry scrolled to the end, Faded and Solo, light and dark, 800x600 and 1000x700, and it also passes without the CSS change). Made it sturdier anyway: `#mp-root` is `position: fixed; inset: 0` instead of `height: 100vh` (so a wrong `vh` in the web view can't push the bars), `.mp-main` has 28 px bottom padding and a `scroll-padding-bottom`. Don: if the box is still hidden in Anki, the screenshot of where it sits will tell more.
- **√ then digits (#9):** a real-Chromium test (click the key, type `108` at once, 0 and 30 ms, Faded and Solo, field focused or not) passes without any JS change: the digits land inside the root. The recording's "digits right of an empty box" was not reproduced, so `mp_page.js` is unchanged. The key goes to the field that last had the focus, or to the page's first field when none has.
- **Tests of #11 (Finding 1):** `test_a_correction_after_a_wrong_step_check_keeps_every_key` now selects the typed text and types the correction over it at once (no Backspace, no wait). At 30 ms it fails with the page's JS from before the #11 fix and with the keep branch of `render` disabled; at 0 ms the keys outrun the round trip and it passes even then. It passes with `main`'s JS, which already is the fix.
- **Flaky test (`test_a_redraw_keeps_what_was_typed_and_the_focus`):** a field's value changes before its `input` event reaches `pycmd`, so waiting for `mp.fieldValue('s1') === 'ab'` could pass while the last `mp:field:s1:ab` message was not yet recorded; the test then fed Python `a` and the redraw correctly showed `a`. The test now waits for that message, then for the redrawn field to exist, then for it to hold `ab` (reproduced under CPU load: about 1 failure in 50).

## Core bugs and workarounds

No edit to `core/` was needed. Worked around in the wrapper:

- a step's typed text is passed to the checker through the environment (`mp_typed`) so a `{` in it is never treated as a template;
- `ValueError` from a malformed interval in `check_answer` is caught and read as a wrong answer;
- `isqrt(` and `or` typed in a field are handled in the adapter (above);
- the `_same` comparator is special-cased for graph and extreme answers.

## Speed

`math_path/fastgen.py` pre-filters candidate numbers with exact `Fraction` arithmetic before any SymPy call. The slowest recipe was `ca.rateq.solve_quadratic` at 5.2 s to generate a problem; with the pre-filter every Chapter 3 recipe generates in well under a second (worst seen 140 ms, `ca.quad.solve_formula` 121 ms in another run). `tests/engine/test_speed.py` guards it. The problem bank prepares the next problem on a worker thread.

## Sizes

| Part | Size |
|---|---|
| `vendor/` (SymPy, mpmath, licences; trimmed copy from Recall Drill) | 17.3 MB tracked (838 files) |
| `web/` (page, MathLive, KaTeX fonts) | 1.1 MB |
| `math_path-0.1.1.ankiaddon` | 4.86 MB (4,864,378 bytes, 920 files; measured for 0.1.0, the code change since is small) |

SymPy and mpmath are vendored, not installed: Anki's Python has neither.
