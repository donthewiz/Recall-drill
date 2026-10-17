# Math Path

An Anki add-on for **learning to solve math problems**, for any math-type course (College Algebra, precalculus, statistics, chemistry calculations). Flashcards teach the words, rules and process; Math Path is where you practise the calculation, with fresh numbers every time, and Anki stays the only scheduler.

It is separate from **Recall Drill** (`../anki-addon/`) and works without it.

## What it does (v0.1)

1. **Recipes become Anki notes.** The *anki-math-cards* skill writes one JSON recipe per problem type (`docs/recipe-format.md`). **Tools → Math Path → Import recipes…** turns a folder of them into **suspended** notes in each section's deck.
2. **A learn session** takes up to 3 recipes from a section (**Learn** on the progress map's row, or **Learn next**) and runs each through **Study → Faded → Plan → Solo**, one problem per turn, interleaved so solos are spaced. At the end the recipes that reached Learned are **handed to Anki** (unsuspended, front of the new queue, buried until tomorrow).
3. **Reviews open Math Path.** When Anki's reviewer shows a Math Path card, the Math Path window opens with one fresh problem. When you finish it rates the card from how it went (Good / Hard / Again, Easy is yours to pick) and the reviewer moves on.
4. **The progress map** (Tools → Math Path → Progress…) has one row per section: Recall Drill cards drilled, and a chip per recipe with its stage.

You work problems on paper; the window checks what you type. Math goes in with a **click palette** (fraction, power, root, ±, brackets, ∪, …): no keyboard shortcut is ever needed for a symbol. Letters and digits come from the keyboard.

Not in v0.1: a drawn graph tool (a graph answer is a shape and two typed points), test mode, TI-84 checks, two methods side by side, find-the-mistake problems.

## Install for development

The add-on is loaded from this folder through a link, so edits show after restarting Anki.

**On the PC (Windows)**, in PowerShell:

```powershell
New-Item -ItemType Junction -Path "$env:APPDATA\Anki2\addons21\math_path_dev" -Target "C:\Users\donth\Documents\dev\Recall-drill\mathpath-addon"
```

**On the laptop (Zorin)**, the clone synced to `/home/don/dev/Recall-drill`:

```sh
ln -s /home/don/dev/Recall-drill/mathpath-addon ~/.local/share/Anki2/addons21/math_path
```

The folder name must differ from the manifest package `math_path` on Windows (`math_path_dev`). **Never install a `.ankiaddon` over a linked folder**: Anki empties the target folder first, and through a link that deletes the repo's files. Remove the link first (`rmdir` on Windows, `rm` on Linux; never `del /s`). Fully close and reopen Anki after `git pull`.

Checks: `cd mathpath-addon`, then (once) `uv venv --python 3.13 .venv && uv pip install --python .venv/bin/python -r requirements-dev.txt`, then `.venv/bin/python -m pytest tests -q`, `.venv/bin/ruff check .` and `.venv/bin/pyright`. The Qt and browser tests need `aqt` (installed with the dev requirements; on Linux `libegl1`) and Chromium (`playwright install chromium`); they skip themselves when those are missing. `python build.py` writes `dist/math_path-0.1.0.ankiaddon`.

## The note contract (for the skill, which can add recipe notes itself later)

A note is a **Math Path note** when its note type has **both a `RecipeId` and a `Recipe` field**, whatever the note type is called. (Recall Drill uses the same rule to leave these notes alone.) Math Path makes the note type **"Math Path recipe"** itself when it is missing:

| Field | Holds |
|---|---|
| `Title` | the recipe's `title` (HTML-escaped) |
| `Section` | `<section.number> <section.title>`, e.g. `3.2 Quadratic Equations, Functions, Zeros, and Models` |
| `RecipeId` | the recipe's `id`, e.g. `ca.quad.solve_factoring` |
| `Version` | the recipe's `version` (a whole number) |
| `Prompt` | one example problem as MathJax (`\( … \)`), made from seed 1000; for the browser and the card back |
| `Recipe` | the whole recipe JSON: compact, ASCII-only, then **HTML-escaped** (`& < >`). Read it back by removing any tags the editor added, unescaping, then `json.loads` |
| `Notes` | yours; never touched by an import |

One card template, **Problem**: the front shows the Title, the Section, "Solving in Math Path…" and a *Solve in Math Path* link (`pycmd('mathpath:open')`); the back adds the Prompt.

Tags on import: `mp::recipe`, `Recipe::<recipe id>`; a handoff adds `mp::learned`. **Never an `rd::` tag**: those are Recall Drill's. New notes are **suspended**, in the file-name order, in the **section deck**: the deck whose last path component starts with `<section.number> ` (for example `College Algebra::Ch 03 …::3.2 Quadratic Equations, …`). A recipe whose `RecipeId` already exists is updated (its fields only) when the file's `version` is higher, and left alone otherwise.

## Settings

`config.json` (Tools → Add-ons → Math Path → Config; every key is explained in `config.md`): `problems_per_session` (3), `auto_open_in_review` (true), `prereq_lock` (true).

## Where things are

- `math_path/` the package. The top-level modules and `views/` are Qt-free (strict pyright): the problem engine, the controllers, the HTML for each screen. `anki_io/` talks to the collection (never Qt). `ui/` has the windows.
- `core/` the plugin's checker, **copied unchanged** (hashes in `core/SOURCE.md`, checked by a test). `vendor/` SymPy and mpmath. `web/` the page, MathLive and its fonts.
- `docs/DECISIONS.md` every decision and API fact; `docs/recipe-format.md` the recipe format.
