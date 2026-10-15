# Recall Drill for Anki

A desktop add-on that drills your Anki cards by **typed recall** before Anki schedules them. You pick cards from a deck (or a search), type each answer from memory until it sticks, and hand them to Anki for long-term review. It is the Anki-side port of the Recall Drill web app: the same engine, run on your collection's cards.

**The method, in five lines.**
1. Cards are drilled in batches (default 5). Short answers are typed from a first-letter cue, then blind, several times in a row.
2. Long answers are split into chunks. Each chunk is typed once, then the chunks are chained back together. A list answer is split a few items at a time, never mid-item, and (unless the card says the order matters) its items can be typed in any order.
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

## What's new in 0.3.2 + exam tracker test (unreleased)

- **Exam tracker hover test (off by default, fake numbers).** Tools → **Recall Drill: exam tracker test** turns on a preview of the exam tracker that is coming in 0.4. On Anki's main deck screen, three decks (Human Anatomy & Physiology 1 → Lab → Lab 2, → Lecture → Lecture 3 → Muscle Tissue Chapter 10, and Medical Terminology) get a status tag ("Behind", "Slightly behind", "On pace"), a thin progress bar, "N days left" and a line like "61 a day needed · 18 done today". Hover a row for a small card with the numbers; click the status tag to keep the card open (click again to close; Esc closes too). A collapsed parent deck shows its worst child's status. **All numbers are made up and say TEST. Nothing is read from or written to your collection**, and nothing about how a card is drilled changed. Switch it off the same way; nothing needs a restart. Real numbers come in the next step.
- **Exam tracker test polish.** The hover card now opens beside the deck list (below or above the row when there's no room), is smaller (280 px), waits half a second and fades in, and the row's numbers line up with the deck name; the fake rows follow the renamed decks (Human Anatomy & Physiology 1 → Lab → Lab 2, and so on).

## What's new in 0.3.2

- **Drill next now drills only the next layer.** In a deck with layers, **Drill next** opens the setup panel in Deck order with **Only with tag** already set to `Layer::N` for the layer marked Next, so the panel counts just that layer's cards instead of the whole deck. It also ticks only the **new** and **suspended new** card types, so the session is the cards the table counts as "to go" and no reviews (young, lapsed, flagged); tick them in the panel to add them. A deck without layers still opens the next subdeck.

## What's new in 0.3.1

- **Drill a deck by layer.** If your notes carry the anki-cards skill's `Layer::1` … `Layer::4` tags, **Deck order** now goes Layer 1 of every chapter first, then Layer 2, and so on, even for cards the skill added days later. A deck without those tags is ordered as before.
- **Progress by layer, with a "Next" marker.** Tools → **Recall Drill: sections** is now titled **Recall Drill: progress**. When your cards have layers, each row is a layer, with a done/total column for every chapter. The first layer that isn't finished is marked **Next**, and **Drill next** opens the setup panel on the deck in Deck order. Without layers you still get one row per subdeck, now in the order the cards were made instead of alphabetical.
- **Cards the drill can't take no longer get stuck.** Hold back leaves out Image Occlusion and other cards the drill can't use, and releases the ones already held, in one undo step. They are counted as "can't drill" and never keep a layer from being done.
- **Held cards don't go "stale" just for being held.** A held-back deck's cards count as stale only after its exam date has passed (or its pacing target says so), so the daily notice stops nagging the day you hold a deck back.
- Nothing about how a card is drilled changed.

## What's new in 0.3.0

- **Drill a whole section, then hand it to Anki.** Each deck has a switch, **Keep new cards out of Anki until drilled** (the setup panel, for the deck and its subdecks). Turn it on and the add-on asks, then suspends the deck's new cards that Anki would otherwise show you undrilled (tagging their notes `rd::held`), so a section is drilled whole and in order, tagged and untagged cards together. The handoff brings the drilled ones into Anki; **Send to Anki undrilled** (Tools → Recall Drill: waiting cards) releases the rest. A deck that holds cards back drills in **Deck order** by default. It is one undo step, and nothing is suspended without your click.
- **See which sections are done.** Tools → **Recall Drill: sections** (or **Sections…** in the setup panel) lists a deck's subdecks in order: cards, drilled, sent undrilled, held, not yet in Anki, % drilled, and "done". Click a row to open that subdeck.
- **Exam dates.** Each deck can have an **Exam date** next to the pacing target. A deck without one uses its parent's. The panel shows "Exam: Fri Oct 23 (10 days)".
- **A warning before the rating window closes.** If drilled cards have been handed off but Anki hasn't had its first rating from you yet, the panel says how many, and the day (and hour) by which to rate them to keep them in the comparison.
- **A small export for Claude.** `exports/outcomes.csv` in your profile folder is rewritten after every handoff and once when the profile opens (Tools → **Recall Drill: export outcomes now** does it on demand and shows the folder). Per drilled or holdout card: the next-day result, what the card cost you in Anki over its first 14 days, and, when the deck has an exam date and the card has a memory state, the predicted recall on exam day.
- Nothing about how a card is drilled changed.

## Install

**Needs Anki 26.08.1 or newer** (the package's `min_point_version` is 260801). Desktop only.

1. Tools → Add-ons → **Install from file…** → pick `recall_drill-<version>.ankiaddon`.
2. Restart Anki. Tools → **Recall Drill…**, the deck gear menu's **Recall Drill this deck**, and the **Recall Drill** button on the deck overview all open the setup panel.

Build the package yourself: `python anki-addon/build.py` (clean git tree required; runs the engine tests first). It writes `anki-addon/dist/recall_drill-<version>.ankiaddon`.

**Dev install (Windows).** Link the repo's `anki-addon` folder into Anki's add-ons folder:

```
cmd /c mklink /J "%APPDATA%\Anki2\addons21\recall_drill_dev" "C:\path\to\Recall-drill\anki-addon"
```

The link name `recall_drill_dev` must differ from the package name `recall_drill`. The Tools menu entry and About box say "Recall Drill (dev)" only when running from that folder; an installed package shows plain "Recall Drill".

> **Never "Install from file" while the junction exists.** Anki empties the target folder on install, and through a junction that deletes the repo's files. Remove the junction first with `rmdir "%APPDATA%\Anki2\addons21\recall_drill_dev"`, and never `del /s` (it follows the junction into the repo).

## Daily use

Open the setup panel on a deck. It reads the collection but writes nothing until you press **Start**, **Save settings** or **Hand off**.

**Cards.** Cards are sorted into classes, each with an eligible count: flagged, leech, **stable**, suspended new, suspended review, lapsed, learning, new, young (under 21 days), mature, plus filtered-deck and buried cards. Flagged, leech, suspended new, lapsed, new and young are on by default; **stable** (well-known cards: FSRS stability ≥ 30 days and difficulty ≤ 5, not a leech) is **off by default**, and the panel counts the ones it skips. The **template filter** picks which templates of a multi-template note type are drilled (their siblings still go to Anki with them). Other controls: Max cards (0 = all), an exact tag, order (priority first, or deck order). **Edit mapping…** sets, per note type and template, which field is the answer and which is the Extra.

**Settings for this deck** (saved per deck): batch size, blind typings, cycle order, strict punctuation, word-ending tolerance, hints. For a deck of short terminology answers the panel offers **Use terminology settings** in one click.
- **Hints** tell apart prompts that look the same but want different answers (the front reads "meaning (2 forms; hint)"). They are on by default only on standard (non-cloze) note types with strict punctuation. Flagged prompts are listed in the panel, and the hint is editable in place; clear it to remove it.
- **Adjust reps by difficulty** changes the drill for *reviewed* cards only: high FSRS difficulty (≥ 7) gets one more blind typing and chunks earlier; low (≤ 3) gets one fewer. **New cards have no FSRS data and are unchanged.**
- **Holdout %** (0–50, **default 0 = off**): that share of new cards skips the drill and goes to Anki as plain new cards (tagged `rd::holdout`), as a fair comparison for the drilled ones.

**Lists** (v0.2). An answer with three or more items separated by commas or semicolons is a list. A list of 4+ items is chunked by items (the chunk-difficulty percentage applied to items, at least 2 items per chunk), and a 3-item list longer than the word threshold is chunked one item per chunk (v0.2.1); an item is never split. A chunk or a combination is the card's own text as written, with its commas, its "and" and its parentheses, so typing the card exactly is never marked wrong, strict punctuation or not. Its items can be typed **in any order**, in every chunk, combination and review, and the feedback marks the items you missed. The card shows "any order". The order matters, and is kept, when the note is tagged `ListKind::Sequence`, or when it has no `ListKind` tag and the front says so ("in order", "steps", "sequence", "proximal to distal", "superior to inferior", "then", an arrow, …). A `ListKind::AttributeSet` or `ListKind::Taxonomy` tag means any order whatever the wording. One-word items may be typed with spaces only ("nervous muscle epithelial connective").

**Fewer clicks** (v0.2). A correct answer in the review cycle and the Final check moves on by itself after a short pause, as encoding does; wrong answers and reveals still wait for Enter (`auto_advance_correct`). A card's Extra shows, and waits for Enter, the first time you see the card's full answer in a session and after a miss or a reveal; otherwise it stays hidden, and **Show Extra** (Ctrl+I) brings it up (`extra_display`; "always" restores the old behavior).

**Waiting drill cards** (v0.2). The `anki-cards` skill suspends the cards it tags `rd::drill` until they are drilled. When a deck is never drilled, they wait forever. Tools → **Recall Drill: waiting cards** lists, per deck, the drill cards still suspended and new, how many are **stale** (added more than `stale_drill_days`, 7, days ago, or in a deck whose pacing target has passed or has no drill days left), the oldest, and the pacing target. Each row has **Drill…** (the setup panel on that deck) and **Send to Anki undrilled…**, which asks whether to send **Stale only (N)** (the default) or **All waiting (M)**, so a deck whose exam is still ahead can release just its old cards (v0.2.1; with nothing stale, only All waiting is offered). Sending unsuspends the cards and their notes' suspended new siblings as plain new cards, in their current place in the new queue (nothing moved or buried), tags the notes `rd::undrilled`, and is one undo step (Edit → Undo "Recall Drill: send undrilled"). Those cards then wait for Anki like handed-off ones. Once a day after the profile opens, a tooltip says when stale cards are waiting (`waiting_notice`), and the setup panel shows an amber line on a deck that has them.

**The review cycle.** After a batch is encoded, each card comes back in a shuffled review cycle. A card you have never missed or revealed in this session is **mastered by one correct answer**; a card you missed or revealed needs **two correct answers in a row**, with other cards in between (a near miss counts as correct and doesn't make a card need two). This holds whatever "Blind typings" is set to. The Final check at the end is unchanged: one correct answer per card.

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
| **Ctrl+I** | show the card's Extra on a feedback screen that hides it |

Edits happen in Anki's own editor: close the Browser (or press **Done editing**) and the card reloads in the session.

**Done → Hand off.** A finished session ends on the Done screen. **Hand off** shows what will happen, tomorrow's load, and any warning, then does it as **one undo step**. **Edit → Undo "Recall Drill handoff"** reverts it (the cards go back to suspended and untagged).

How the cards enter Anki depends on `handoff_mode`:
- **B (default):** the cards stay *new*, go to the front of the new queue, and are buried until tomorrow, so Anki's own learning steps run and the FSRS optimizer keeps them (120 optimizer items in the test, against 0 for A).
- **A:** the cards become review cards due tomorrow. No learning steps, and the FSRS optimizer **never trains on them**.

Cards that already have a schedule keep it either way.

**Finishing early.** To hand off before the whole session is mastered, press **Finish with N cards** (on the batch screen, on the Session Saved screen, or **Finish with N mastered cards** in the deck's panel next to Resume). The mastered cards get the Final check and are then handed off as usual. The other cards go back to the pool: they stay suspended and the next session picks them first. Progress on a card that was part-way through its batch is dropped, and a card you edited in Anki since the drill goes back too. Their trials and time stay in the session's history.

## Tags

| Tag | Meaning |
|---|---|
| `rd::drilled` | The note was handed off by a finished session. |
| `rd::hard` | A card of the note had misses + reveals + Final-check misses of at least `hard_threshold` (3). Replaced at the next handoff: removed if the note no longer qualifies. |
| `rd::final-miss` | A card missed in the Final check. Replaced the same way. |
| `rd::holdout` | The note was a held-out control (only exists when Holdout % is on). |
| `rd::long` | The note's answer was drilled in chunks. **Off by default** (`tag_long`). |
| `rd::undrilled` | The note's drill cards were sent to Anki without the drill (Tools → Recall Drill: waiting cards). |
| `rd::held` | The note has cards held back from Anki until drilled (**Keep new cards out of Anki until drilled**). Removed by the handoff and by sending the cards to Anki undrilled. |

Tools → **Recall Drill: my rd::hard cards** opens the panel on `tag:rd::hard`; **Recall Drill: filtered deck for rd::hard** opens Anki's own filtered-deck dialog with that search filled in. The `anki-cards` skill's `rd::drill::*` tags are a different family: always search an exact tag, never `tag:rd::*` (it would also match `rd::drilled`, `rd::undrilled` and `rd::held`).

## Time figures

Every minute figure comes from **your own data**, and says where:
- **Drill minutes:** measured active drill time per card from your recent sessions. Time between two actions in the drill window counts, but a gap over **120 s** counts as 120 s (`idle_cap_seconds`), so a break doesn't.
- **Anki minutes:** Anki's FSRS simulator (needs 50 learning and 50 review ratings of yours in the deck) or, failing that, your revlog answer times (30 days, 50 ratings).
- Otherwise it says **"no estimate yet"**. There is no cold-start guess and **no daily time budget**: minutes are information only.

## Data and sync

**In the collection** (syncs with Anki): the tags, what the handoff changes (suspension, queue position, due dates and review log rows for A, burying, flag clearing), and what sending waiting cards undrilled changes (suspension, the `rd::undrilled` tag), and what holding cards back changes (suspension, the `rd::held` tag). That is all that reaches your phone.

**In `user_files/profiles/<profile>/`** inside the add-on folder (local, **does not sync, not on your phone**):
- `sessions/`: in-progress sessions;
- `history/`: the append-only session, handoff, release and tuning logs (the tuning report reads them);
- `waiting_notice.json`: the last day the waiting-cards tooltip showed;
- `exports/outcomes.csv`: the light outcomes export (rewritten, never read back);
- `deck_settings.json`: each deck's drill settings;
- `hints.json`: manual hints;
- `mappings.json`: your answer and Extra field choices;
- `pacing.json`: target dates, drill weekdays and exam dates;
- `holdout.json`: the holdout's random salt;
- `estimates.json`: an old estimate cache nothing reads any more.

Each Anki profile has its own folder, since card and deck ids only mean something in one collection. **Back this folder up with the add-on folder.** Anki keeps `user_files/` when the add-on is upgraded, but deleting the add-on deletes it. Tuning values you accept live in the add-on's config (Tools → Add-ons → Recall Drill → Config; Anki stores it in the add-on's `meta.json`), not in `user_files/`: copy that JSON too.

A file the add-on can't read is renamed `<name>.corrupt-<timestamp>` and the defaults are used.

## Tuning report

Tools → **Recall Drill: tuning report**. Its metric is the **next-day Again rate**: for each drilled card, whether the first rating Anki recorded after the handoff (on a later Anki day, within 2 days) was Again. Holdout and baseline cards get the same measure from their first rating to their next-day rating, and so do cards sent to Anki undrilled (a "Released undrilled" row: the cards that waited longest, not a random control). A "cycle rule" breakdown splits sessions before and after v0.2's one-answer rule for clean cards. Trials per card are always shown beside it, because fewer trials is still the priority. Groups under 30 cards show "n too small" and produce no suggestion. It can suggest a new chunk threshold or a number of blind typings; nothing changes without your confirmation.

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
