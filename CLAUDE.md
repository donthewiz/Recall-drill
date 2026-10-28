# Recall Drill repo: instructions for Claude Code

Loaded at the start of every session. Keep it under 200 lines. Folder rules live in
`anki-addon/CLAUDE.md`, `mathpath-addon/CLAUDE.md` and `triage-addon/CLAUDE.md` (they load when you work there).
Workflows such as writing build prompts or reviews live in skills, not here.

## What's here

| Folder | What | Truth |
|---|---|---|
| `anki-addon/` | **Recall Drill** Anki add-on (package `recall_drill`): typed-recall drill, then handoff to Anki | `anki-addon/docs/DECISIONS.md` |
| `mathpath-addon/` | **Math Path** Anki add-on (package `math_path`): solve fresh-number math problems from recipes | `mathpath-addon/docs/DECISIONS.md` |
| `triage-addon/` | **Card Triage** Anki add-on (package `card_triage`): set a stuck new/learning card aside during review, release them later. Standalone | `triage-addon/docs/DECISIONS.md` |
| `src/`, `test/` | Recall Drill web app (React 19, TS 7, Vite 8; low priority). `src/utils/` is the **TS engine** the add-on's Python engine is ported from | `docs/V2-HANDOFF.md` (history) |
| `docs/` | Older project docs (history, not instructions) | |

The DECISIONS.md files and the code win over any summary, prompt or older doc. Read the
DECISIONS headings your change touches before writing code; add a dated entry for every
decision you make there.

## Settled scope (don't change, don't propose changing)

- **Anki is the only scheduler.** No due dates, intervals or FSRS logic of our own.
- **Typed free recall only** in Recall Drill. No multiple choice.
- **Fewer trials is the top priority** of the drill engine.
- **Handoff B:** drilled new cards stay new, go to the front of the new queue, buried until
  tomorrow; siblings too; one undo step.
- Tag searches use exact tag names, never a wildcard over `rd::` (`tag:rd::*` also matches
  `rd::drilled`).
- Tests use scratch collections only, never a real Anki profile.

## Never

- Never push to `main` or open a PR into anything but `main`. Work on a branch.
- Never merge on your own. Merge only when Don asks in the conversation, and always with
  **Rebase and merge** (commits are matched by message, not hash).
- Never rewrite pushed history: no force-push, no amend or rebase of pushed commits.
- Never hand-edit `mathpath-addon/core/` (copied from the anki-math-cards plugin, hashes
  tested) or `anki-addon/tests/golden/` (generated). A hook blocks both.
- Never change engine behavior in one language only (see "Engine changes" below).
- Never add keys, tokens, device IDs, private file paths or personal details: the repo is
  public.
- Never call `QApplication.setStyleSheet`; style only the add-ons' own windows.
- Never change Anki deck options or notes that aren't the add-on's own.

## Engine changes (Recall Drill)

The Python engine (`anki-addon/recalldrill/engine/`) is a step-for-step port of the TS
engine (`src/utils/`). CI regenerates the goldens and fails on any difference. A behavior
change is **one commit with four parts**:

1. Change the TS engine and its vitest specs.
2. Regenerate the goldens: `npx tsx anki-addon/tools/export_golden.ts`.
3. Port the same change to the Python engine.
4. Both suites green, and `npm run simulate` before and after (put both in the report).

A behavior the add-on adds on top of the TS engine goes under "Engine extensions" in
`anki-addon/docs/DECISIONS.md` with its own tests, not into the goldens.

## Setup

Cloud sessions: the SessionStart hook (`.claude/hooks/session_setup.sh`) makes one Python
3.13 venv per add-on (three: Recall Drill, Math Path, Card Triage) in `~/venvs/` from its `requirements-dev.txt`, links it as
`<add-on>/.venv`, and runs `npm ci`. The two venvs must stay apart (Math Path's tests check
that no system SymPy is installed; Recall Drill's dev pins install it). If the hook reports
FAILED, read the log it names and fix the install before writing code.

## Checks: run only what your change touches, then the full gate once

While working, run the tests for the files you changed (a test file, a folder, `-k name`).
Before the final push, run the full gate for every part you touched:

| You changed | Full gate (from the repo root) | Time (Est., cloud) |
|---|---|---|
| `src/` or `test/` | `npm run lint && npm test && npm run build` | ~1 min |
| `anki-addon/` | `anki-addon/.venv/bin/ruff check anki-addon && anki-addon/.venv/bin/python -m pytest anki-addon/tests -q` | ~2 min |
| `mathpath-addon/` | `mathpath-addon/.venv/bin/ruff check mathpath-addon && mathpath-addon/.venv/bin/python -m pytest mathpath-addon/tests -q` | ~5 min |
| `triage-addon/` | `triage-addon/.venv/bin/ruff check triage-addon && triage-addon/.venv/bin/python -m pytest triage-addon/tests -q` | ~1 min |
| TS or Python engine | both of the first two rows, plus the golden regeneration and `git diff --exit-code anki-addon/tests/golden` | ~3 min |
| Typed modules | `cd <add-on> && .venv/bin/pyright` (Card Triage too: its pure modules and `anki_io/` are strict) | ~1 min |

A PreToolUse hook pipes pytest, vitest and `npm test` output through
`.claude/hooks/test_filter.py`: you see failures, errors and the pass/fail count line, not
the passing dots. Exit codes are kept. Put `RD_FULL_OUTPUT=1` in the command to see
everything. `ruff format --check` is not part of CI (19 files would change); don't
reformat files you aren't otherwise changing.

When you change code that can be run, built, or type-checked, run a real check that
exercises the change before reporting it done: the project's tests, type-checker, or build,
or the changed command itself. A syntax-only check, or a check command that failed to
start, does not count; if all that is missing is the project's declared dependencies,
install them with its own package manager and lockfile (e.g. npm install, pip install -r
requirements.txt), never via sudo or the system package manager, unless told not to. Only
if no real check can run here, say which one you did not run and why instead of reporting
the change as done.

Yes/no behavior (a button exists, a value is saved, a window opens) is checked by a test
(pytest, or Playwright for the web pages), not by a screenshot. Screenshots are only for
layout and look, small (about 800×600 or cropped), taken near the end, of the screens the
prompt lists.

## How to work

- Keep working until everything the user asked for is done, and only stop to ask when you
  can't go on without the user or before a risky step.
- When the work the user asked for is done and checked, stop and report. Don't add
  features, tests, files, docs or refactors that weren't asked for. If you think one would
  help, mention it at the end instead of doing it.
- **Decide vs stop.** A choice the prompt didn't settle: decide, record it (DECISIONS.md
  and the report's "Decided on my own"), keep going. Stop and ask only for things that are
  hard to undo, or that change what Don sees in Anki or how he studies, when the prompt
  doesn't already say what to do.
- Read what the prompt points to (functions, files, DECISIONS headings) before exploring
  further. Stay inside the prompt's scope and its out-of-scope list.

## Commits and pushing

- One commit per fix or feature, plus one commit for test-only changes. Engine changes are
  one commit (see above). Message: `type(scope): what changed` (e.g.
  `fix(mathpath): accept "x = …" answers`), body says why.
- **Push at every stop point and before any pause** (a long test run, a question, the end).
  A cloud VM that is reclaimed starts fresh, and unpushed work is lost.

## The report (end of every build)

Top part, for Don (short, plain language):

1. **What changed:** what Don will see or can now do, one line each.
2. **Decided on my own:** each choice the prompt didn't settle, with one-line reason.
3. **Your to-dos:** what Don must do (merge the PR, restart Anki, a manual look the tests
   can't cover). Nothing a test already checks.

Detail part, for the reviewer: the branch and commits; the commands you ran with their
pass/fail count lines (evidence, not claims); checks you could not run and why; known
gaps; anything that differs from the prompt.

## Compact instructions

When compacting, keep: the prompt's requirements and out-of-scope list, decisions taken,
files changed, the last check results, and what is still left to do.
