# Recall Drill for Anki

A desktop add-on that drills your Anki cards by **typed recall** before Anki schedules them. You pick cards from a deck (or a search), type each answer from memory until it sticks, and hand them to Anki for long-term review. It is the Anki-side port of the Recall Drill web app: the same engine, run on your collection's cards.

**The method, in five lines.**
1. Cards are drilled in batches (default 5). Short answers are typed from a first-letter cue, then blind, several times in a row.
2. Long answers are split into chunks. Each chunk is typed once, then the chunks are chained back together.
3. Misses are broken down to the span that failed, and that span is drilled.
4. Each batch ends with a cycle pass; the whole session ends with a Final check, one cue-free pass over every card.
5. Anki owns long-term memory: the drill has no scheduler of its own, and fewer trials is the priority.

## What's core, and what's optional

**Core** (always on):
- pick cards (by class, template, tag, or a search);
- drill them;
- **hand them off to Anki** (tags, unsuspend, queue position);
- **pace a deck to a target date.**

**Optional** (each can be switched off):

| Part | Turn it off |
|---|---|
| Tuning report (Tools → Recall Drill: tuning report) | Don't open it. It only reads. Nothing changes unless you press Apply on a suggestion and confirm. |
| Holdout (a control group that skips the drill) | **Holdout %** = 0 in the panel. **0 is the default.** |
| Difficulty adjustment (+1 / −1 rep from FSRS difficulty) | Untick **Adjust reps by difficulty** for the deck, or set `difficulty_adjust` to false in the add-on config for every deck. |
| Struggle tags `rd::hard`, `rd::final-miss` | Always written at handoff; they only add tags, and a tag search isn't needed to use them. `rd::long` is off by default (`tag_long`). |

## Install

**Needs Anki 26.08.1 or newer** (the package's `min_point_version` is 260801). Desktop only.

1. Tools → Add-ons → **Install from file…** → pick `recall_drill-<version>.ankiaddon`.
2. Restart Anki. Tools → **Recall Drill…**, the deck gear menu's **Recall Drill this deck**, and the **Recall Drill** button on the deck overview all open the setup panel.

Build the package yourself: `python anki-addon/build.py` (clean git tree required; runs the engine tests first). It writes `anki-addon/dist/recall_drill-<version>.ankiaddon`.

**Dev install (Windows).** Link the repo's `anki-addon` folder into Anki's add-ons folder:

```
cmd /c mklink /J "%APPDATA%\Anki2\addons21\recall_drill_dev" "C:\path\to\Recall-drill\anki-addon"
```

The link name `recall_drill_dev` must differ from the package name `recall_drill`.

> **Never "Install from file" while the junction exists.** Anki empties the target folder on install, and through a junction that deletes the repo's files. Remove the junction first with `rmdir "%APPDATA%\Anki2\addons21\recall_drill_dev"`, and never `del /s` (it follows the junction into the repo).

## Daily use

Open the setup panel on a deck. It reads the collection but writes nothing until you press **Start**, **Save settings** or **Hand off**.

**Cards.** Cards are sorted into classes, each with an eligible count: flagged, leech, **stable**, suspended new, suspended review, lapsed, learning, new, young (under 21 days), mature, plus filtered-deck and buried cards. Flagged, leech, suspended new, lapsed, new and young are on by default; **stable** (well-known cards: FSRS stability ≥ 30 days and difficulty ≤ 5, not a leech) is **off by default**, and the panel counts the ones it skips. The **template filter** picks which templates of a multi-template note type are drilled (their siblings still go to Anki with them). Other controls: Max cards (0 = all), an exact tag, order (priority first, or deck order). **Edit mapping…** sets, per note type and template, which field is the answer and which is the Extra.

**Settings for this deck** (saved per deck): batch size, blind typings, cycle order, strict punctuation, word-ending tolerance, hints. For a deck of short terminology answers the panel offers **Use terminology settings** in one click.
- **Hints** tell apart prompts that look the same but want different answers (the front reads "meaning (2 forms; hint)"). They are on by default only on standard (non-cloze) note types with strict punctuation. Flagged prompts are listed in the panel, and the hint is editable in place; clear it to remove it.
- **Adjust reps by difficulty** changes the drill for *reviewed* cards only: high FSRS difficulty (≥ 7) gets one more blind typing and chunks earlier; low (≤ 3) gets one fewer. **New cards have no FSRS data and are unchanged.**
- **Holdout %** (0–50, **default 0 = off**): that share of new cards skips the drill and goes to Anki as plain new cards (tagged `rd::holdout`), as a fair comparison for the drilled ones.

**Drill time** reads "Next N cards: …". It comes from **your own drill sessions**: until you have **3 timed sessions** it says "no estimate yet".

**Pacing to a target date** (deck scopes): tick **Pace to a target date**, pick the date and the drill weekdays. The panel shows today's N, drill and Anki minutes, and the peak day. **Use N as max cards** fills Max cards with today's N.

**Handed-off cards wait for Anki.** After a handoff, those cards (and their siblings and holdout cards) stay out of new sessions until Anki has recorded a rating for them, so a session before your Anki reviews doesn't drill yesterday's cards again. The panel shows "Handed off, waiting for Anki: K". A card that is suspended again isn't left out: undoing a handoff re-suspends its cards, so they are drillable again.

**Keys in the drill window.**

| Key | Does |
|---|---|
| **Enter** | submit your answer, continue, or start the next batch |
| **Esc** | reveal the target (counts as a reveal, not a miss) |
| **Ctrl+Enter** | count a wrong answer as correct |
| **Ctrl+E** | edit the card in Anki's Browser |
| **Ctrl+R** | replay the audio |

Edits happen in Anki's own editor: close the Browser (or press **Done editing**) and the card reloads in the session.

**Done → Hand off.** A finished session ends on the Done screen. **Hand off** shows what will happen, tomorrow's load, and any warning, then does it as **one undo step**. **Edit → Undo "Recall Drill handoff"** reverts it (the cards go back to suspended and untagged).

How the cards enter Anki depends on `handoff_mode`:
- **B (default):** the cards stay *new*, go to the front of the new queue, and are buried until tomorrow, so Anki's own learning steps run and the FSRS optimizer keeps them (120 optimizer items in the test, against 0 for A).
- **A:** the cards become review cards due tomorrow. No learning steps, and the FSRS optimizer **never trains on them**.

Cards that already have a schedule keep it either way.

## Tags

| Tag | Meaning |
|---|---|
| `rd::drilled` | The note was handed off by a finished session. |
| `rd::hard` | A card of the note had misses + reveals + Final-check misses of at least `hard_threshold` (3). Replaced at the next handoff: removed if the note no longer qualifies. |
| `rd::final-miss` | A card missed in the Final check. Replaced the same way. |
| `rd::holdout` | The note was a held-out control (only exists when Holdout % is on). |
| `rd::long` | The note's answer was drilled in chunks. **Off by default** (`tag_long`). |

Tools → **Recall Drill: my rd::hard cards** opens the panel on `tag:rd::hard`; **Recall Drill: filtered deck for rd::hard** opens Anki's own filtered-deck dialog with that search filled in. The `anki-cards` skill's `rd::drill::*` tags are a different family: always search an exact tag, never `tag:rd::*`.

## Time figures

Every minute figure comes from **your own data**, and says where:
- **Drill minutes:** measured active drill time per card from your recent sessions. Time between two actions in the drill window counts, but a gap over **120 s** counts as 120 s (`idle_cap_seconds`), so a break doesn't.
- **Anki minutes:** Anki's FSRS simulator (needs 50 learning and 50 review ratings of yours in the deck) or, failing that, your revlog answer times (30 days, 50 ratings).
- Otherwise it says **"no estimate yet"**. There is no cold-start guess and **no daily time budget**: minutes are information only.

## Data and sync

**In the collection** (syncs with Anki): the tags, and what the handoff changes (suspension, queue position, due dates and review log rows for A, burying, flag clearing). That is all that reaches your phone.

**In `user_files/profiles/<profile>/`** inside the add-on folder (local, **does not sync, not on your phone**):
- `sessions/`: in-progress sessions;
- `history/`: the append-only session, handoff and tuning logs (the tuning report reads them);
- `deck_settings.json`: each deck's drill settings;
- `hints.json`: manual hints;
- `mappings.json`: your answer and Extra field choices;
- `pacing.json`: target dates and drill weekdays;
- `holdout.json`: the holdout's random salt;
- `estimates.json`: an old estimate cache nothing reads any more.

Each Anki profile has its own folder, since card and deck ids only mean something in one collection. **Back this folder up with the add-on folder.** Anki keeps `user_files/` when the add-on is upgraded, but deleting the add-on deletes it. Tuning values you accept live in the add-on's config (Tools → Add-ons → Recall Drill → Config; Anki stores it in the add-on's `meta.json`), not in `user_files/`: copy that JSON too.

A file the add-on can't read is renamed `<name>.corrupt-<timestamp>` and the defaults are used.

## Tuning report

Tools → **Recall Drill: tuning report**. Its metric is the **next-day Again rate**: for each drilled card, whether the first rating Anki recorded after the handoff (on a later Anki day, within 2 days) was Again. Holdout and baseline cards get the same measure from their first rating to their next-day rating. Trials per card are always shown beside it, because fewer trials is still the priority. Groups under 30 cards show "n too small" and produce no suggestion. It can suggest a new chunk threshold or a number of blind typings; nothing changes without your confirmation.

The warning it shows, verbatim:

> Drilled and undrilled cards aren't randomly assigned. Only the holdout comparison is a fair test. The baseline below is cards you learned before using the add-on, most of which were drilled in the web app, so it's not an Anki-only baseline.

## Known limitations

- FSRS difficulty adjustment applies to **reviewed** cards only. New cards have no FSRS data.
- **Stock** Image Occlusion cards aren't drillable (they hold shapes, not text). The `Image Occlusion (anki-medical-cards)` lookalike cards are.
- A cloze note type with several cloze fields is drilled on the **first cloze field** only.
- Edits go through Anki's editor; the drill never writes note fields.
- The simulator's Anki-minutes figure needs 50 learning and 50 review ratings in the deck. It adds new cards **every day**, not only on drill days. Like Anki's own deck-options Simulator, it may save FSRS memory states for review cards that lack one (that is the one write a panel read can cause).
- **Undoing a handoff leaves its history line**, so the tuning report still counts that session.
- **Desktop only.** The web app (PWA) stays the phone tool.

## Overlaps with other tools (no action taken)

- The `medical-terminology-recall-drill` skill and the `anki-cards` skill's Recall Drill export aren't needed for this path: the add-on reads the cards from Anki directly.
- The `medterm-daily-drill` skill's daily unsuspend and pacing are **replaced for decks drilled here**: the handoff unsuspends and queues, and the Pacing section sets the daily count. The skill itself is unchanged.

## Docs

`docs/DECISIONS.md` (decisions and checked Anki facts), `config.md` (every config key), and the repo's `docs/SMOKE.md` ("Anki add-on" section) for the manual checks. To change the engine without breaking parity, see "Changing the engine now" in `DECISIONS.md`: change the TS engine, regenerate the goldens (`npx tsx anki-addon/tools/export_golden.ts`), port to `recalldrill/engine/`, and get both test suites green in one commit.
