# Partial handoff: design (Phase 8)

Status: **design for review. Nothing is implemented.** Written 2026-10-07 against `main` at
8117244 ("fix(addon): show (dev) in the menu and About text only from the dev folder").

## The idea in one paragraph

A stopped session can be **finished early**. "Finish with the 20 mastered cards" cuts the session
down to the cards that have passed the cycle. Those cards get the normal Final check, then the
session completes and is handed off exactly as a complete session is today. The other 60 cards
**go back to the pool**: nothing in Anki changes for them (they stay suspended), and the next
selection picks them first, in deck order, as it would have anyway. The result is the session Don
would have had if he had set Max cards to 20, apart from when it ran. `apply_handoff`, the
forecast, the tags and the one undo step are unchanged. There is no engine change.

## What the code does today (checked)

Every fact in the prompt holds. Some details matter for the design:

| Prompt's fact | In the code |
|---|---|
| `drilled_cards()` raises unless every card is `finalDone` | True (`anki_io/handoff.py`, `drilled_cards`). `read_input` calls it, so `plan_handoff` refuses an incomplete save. |
| `finalDone` is set only in the Final check, one shuffled pass over all cards after the last batch | True (`engine/session.py`, `_grade_and_advance`, final branch). A miss or reveal goes to the end of the same pass, so every card must be answered right once. The pass is built from **every** item (`_advance_batch_state`: `shuffle([i["id"] for i in items])`), whatever their `finalDone`. |
| Cards are drilled in batches, each finished before the next | True. A batch ends when every card in it is `mastered` (two correct cycle answers). Then comes the `batch-done` interstitial, or the Final check after the last batch. |
| Item ids are indexes into `addon.sources` | True. `DrillController.__init__` checks it. `self._sources[item_id]` is used throughout the controller, along with `sources[it["id"]]` in `drilled_cards` and `build_session_line`, and `read_saved._describe`. `check_resume` walks **`sources`**, not items. |
| One history line at completion, read by tuning and pacing | True (`SessionStore.finish`). `append_session` **skips a line whose `sessionId` already has one**. `record_cold_start` also runs on every stop, but nothing reads `estimates.json` since Phase 6 (`get_cold_start_history` has no caller). Nothing reads the session line's `stats` either. Tuning reads per-card `cards`/`anki`, and pacing reads per-card `anki[i].activeMs` and `finishedAt`. |
| Selection excludes handed-off cards Anki hasn't rated | True, per card, **unless suspended**. It covers the `drilled_new`, `siblings`, `holdout` and `holdout_siblings` groups (`history_store.HANDED_OFF_GROUPS`), but not `drilled_scheduled`. |

Checked by running the engine (scratch script, not committed): a state whose items are all
`mastered`, put in `phase: "cycle"` with an empty queue and `batchIndex` on its last batch, goes
through `init_session` straight into the Final check. That gives `phase: "final"`, a shuffled queue
over every item, and `finalCheckStartAttempts` = the attempts so far. The design uses this path, so
it needs no engine change.

## Decisions for Don

| # | Decision | Recommendation | Alternatives and what they cost |
|---|---|---|---|
| 1 | What happens to the unfinished cards | **Back to the pool**: they stay suspended, untouched, and the next selection picks them | **A continuation session** (a second save that resumes with the rest). It keeps the unfinished cards' progress (at most one batch's worth) and the exact card list. It costs a second save lifecycle under the same key, id remapping and a new `sessionId` lineage, stats rules for a session that starts half-way, and about one more commit of code and tests. See §2. |
| 2 | Final check before an early handoff | **Yes**, the normal Final check over the kept cards | **Skip it**: saves one pass over the kept cards (plus requeued misses). It costs a second handoff rule (`drilled_cards` accepting unchecked cards), `rd::final-miss` handling (skipping it, or the "replaced" rule removes an existing tag), "Final check: not run" markers in history so tuning doesn't read 0 final misses as measured, and no "Drill these cards again" for those cards. See §6. |
| 3 | Which cards count as done | **Mastered** (passed the cycle). A returned card of the same note stays suspended rather than going as a sibling | **Finished batches only**: an easier rule, but it throws away the mastered cards of the batch in progress. **Keep a note's cards together** (a mastered card waits if a note-mate isn't mastered): no half-handed-off notes, but that card is drilled again from scratch. See §1. |

Everything else below is my call, with the alternative stated where there is one.

## 1. Which cards are done enough

A card's progress in the engine is `new → encoding → ready → mastered`, then `finalDone` in the
Final check.

| Definition | What it means | Trade-off |
|---|---|---|
| **`mastered`** (recommended) | Encoded, then two correct answers in the batch's cycle, with other cards between them | It's the engine's own "this card is learned" before the Final check. Nothing already mastered is thrown away. Mastered cards of the batch in progress count too. |
| Finished batches only | Every card of each batch that reached the interstitial | Same as `mastered` at the interstitial. Mid-batch, it returns that batch's mastered cards, which are then drilled again from scratch next time. |
| `ready` or later | Encoded, cycle not passed | Hands off cards that never had a spaced retrieval. With the Final check it would be one cue-free answer instead of the cycle's two. Too weak. |
| `finalDone` (today's rule) | Final check passed | Never true before the last batch. This is the rule that needs relaxing. |

**Rules on top of `mastered`:**

- **Missing cards** (deleted in Anki) are left out of the kept set and listed. They would be skipped
  at handoff anyway.
- **Changed cards** (`check_resume`'s answer hash differs) go back to the pool, not into the Final
  check. Their drill was on the old answer, and the next selection rebuilds them with the new one.
  Edits made through the drill window's "Edit in Anki" update the save's source, so they don't
  count as changed.
- **Notes split by the cut** (one card kept, a note-mate returned): recommended, the returned card
  stays suspended and is **not** handed off as a sibling (§4). Alternative, decision 3: keep the
  note's cards together by returning the mastered one too. Splits are rare. New cards of one note
  share a queue position, so they sit next to each other in deck order and are split only by a
  batch boundary, by the cut, or by having different classes (a leech and a new sibling).

## 2. The unfinished cards and the session

### Recommended: cut the session, return the rest to the pool

**"Finish with N cards"** turns the saved session into a smaller one, in one atomic save write:

| Part of the save | After the cut |
|---|---|
| `items` | The kept cards only, in their original order, **renumbered 0…k−1**. Each item keeps everything else: counters, `hardSpans`, chunks, overrides. |
| `addon.sources` | The kept cards' sources, in the same new order, so ids still index sources. This must be compacted because `check_resume` walks `sources`: a leftover entry would show up as a false "missing" or "changed". |
| `addon.activeMsByItem` | Remapped to the new ids. Returned cards' shares move to `addon.cut.returned`. |
| `addon.sessionId`, `startedAt`, `scope`, `selectOptions`, `deckSettings`, `hints`, `holdout`, `collisions` | Unchanged. Same session, so the history stays one line per session. |
| `addon.cut` (new) | `{at, total, missing: [cid], returned: [{cid, nid, ord, did, card_class, status, attempts, misses, reveals, nearMisses, activeMs, reason}]}` where `reason` is `unfinished` or `changed`. These are exact per-card values from the items, with nothing allocated. |
| `stats`, `addon.activeMs` | Unchanged: they stay the **sitting's** totals (see §5). |
| Engine position | `phase: "cycle"`, `queue: []`, `batchIndex` = the last batch of the kept cards (with the session's batch size), `currentId` = complete. `init_session` then moves it into the Final check through the engine's own `_advance_batch_state`. |

The returned cards need nothing done to them. They were suspended new cards, and they still are.
Selection orders new cards by queue position, so the next session picks them first unless
higher-priority classes (flagged, leech, lapsed) have appeared since, which is selection's
existing rule. Pacing still counts them as remaining. Don picks the next session's size as usual
("Use N as max cards").

After the cut, the session is an ordinary save. It resumes into its Final check, completes,
writes its history line, waits for its handoff and is handed off, all through today's code.

### Compared: a continuation session

The returned cards would become a second session that resumes another day.

- **Gains:** the unfinished cards keep their progress (at most the cards of one batch, minus those
  already mastered), and the session's exact card list and settings snapshot carry over.
- **Costs:**
  - **One save per scope key.** The continuation can't exist while the cut session waits for its
    handoff. It would have to live inside the cut save until the handoff and be written after
    it, or use a second key the panel would have to show.
  - It needs **a new `sessionId`**, because `append_session` silently drops a second line with the
    same id. It also needs a link back to the parent.
  - Its items need renumbering, and its engine state needs rebuilding (batch 0, empty queue,
    fresh stats against items that carry old counters).
  - On resume it needs `check_resume`, for cards that changed while it waited.
- **Learning value:** progress that is a day old is resumed today when a stopped session is
  resumed, so keeping it is no worse than today. But whether it saves trials over a fresh encode
  hasn't been measured, and nothing in Don's data says so.

Return to the pool gets the same cards drilled with less machinery, and the next selection sees
Anki as it is then (edits, deletions, lapses, the pacing N).

### Rejected: continue in place, same save

This would keep the handed-off cards in the save, flag them and drill on. The Final check would
serve them again, because its pass is built from every item. Skipping them needs an **engine
change**: the TS `_advance_batch_state` builds its pass only from cards that aren't `finalDone`,
then the goldens are regenerated and the change is ported to Python. The goldens might not move,
since no TS path pre-sets `finalDone`. But the session's single history line would then cover
cards handed off on two days, and the handoff, `check_resume` and the history writer would all
need to filter out flagged items. That's more cost than the cut, for no gain.

## 3. Where it's offered

| Where | Session state | Offered? |
|---|---|---|
| Drill window, card on screen (encode, cycle, Final check) | running | **No.** End session first (one click, which flushes the dwell and saves). |
| Drill window, **batch interstitial** | `batch-done` | **Yes: "Finish with these N cards"**, beside Next batch and Save and stop. Nothing is lost here: every card is mastered or untouched. |
| Drill window, **stopped screen** ("Session Saved") | stopped, 0 < kept < total | **Yes: "Finish with N mastered cards"**. The Final check starts in the same window, as "Drill these cards again" swaps sessions today (`_set_session`). |
| Setup panel banner, resumable save | 0 < kept < total, no window open | **Yes**, beside Resume / Start fresh. The banner already says "20 of 80 mastered". It opens the drill window on the Final check. |
| Setup panel, a window is open for that key | — | **No.** Same as Resume: `raise_window` brings the window to the front, so two writers never drive one save. |
| Final check, or every card mastered | — | No: nothing would go back. Resume finishes it. |
| Pending handoff, drill-again sessions | — | No. |

**The confirmation** (before the save is rewritten): "Finish with 20 cards? They get the Final
check now, then you can hand them off. The other 60 stay suspended and are picked first next time.
3 of them were part-way through the current batch: that progress is dropped." Lines for changed
or missing cards are added when there are any. **Finish** / **Cancel**.

## 4. The handoff

Unchanged: `plan_handoff`, `build_plan`'s groups, the forecast, tags, flags, the confirmation
dialog, `apply_handoff` as the only collection write and one undo step, rollback on failure, and
the history line format. `drilled_cards` still requires every card to be `finalDone`, and the cut
session meets that.

Changes:

- **Siblings.** `build_plan`'s `taken` (cards that are never siblings) adds the save's returned
  card ids. A returned card of a kept card's note stays suspended and goes back to the pool, so it
  isn't handed off undrilled (§1).
- **Holdout.** The session's held-out cards (`addon.holdout`) go with this handoff, unchanged.
  Their outcome is measured from their own introduction, so going in now, before some of the
  cards they were selected beside, doesn't bias the metric. They show in the forecast. Holdout is
  off by default.
  - Alternative: hold them back, so the next selection's walk holds them out again. That needs a
    one-line clear in the cut, and a % change in between would release some.
- **The dialog** adds one line when the save has a cut: "60 cards from this session went back to
  the pool: not handed off, still suspended."
- **The handoff line** adds `groups.returned` (card ids), for the record. `handed_off_at` doesn't
  read it, so those cards stay selectable.

Failure and rollback are as today. The cut is a save write, not a collection change, so a failed
handoff leaves the cut session pending, and it can be retried or declined.

## 5. History and measurement

With return to the pool, **one session stays one session**: one `sessionId`, one session line,
one handoff line. The returned cards are drilled later in a **new** session with its own id and
lines. Nothing is split or allocated:

| Value | Where it goes | Why it's honest |
|---|---|---|
| Per-card counters (`attempts`, `misses`, `reveals`, `nearMisses`, `finalMisses`, `hardSpans`) and per-card `activeMs` | Kept cards: the session line's `cards`/`anki`, as today. Returned cards: `cut.returned` on that line | Each is the card's own count, never divided. |
| `stats` (attempts, misses, …) and `activeMs` | The session line, as the **sitting's** totals: returned cards' trials and the Final check included | They can't be split per card: item `attempts` count overrides and `stats.attempts` doesn't, and Final-check misses are in `stats.misses` but in item `finalMisses`. Nothing reads the line's `stats`. Pacing uses `activeMs` only as a "this line is timed" test. |
| `cut` block | The session line, copied from the save | It records the cut (when, how many, which cards went back and why). |
| `startedAt` / `finishedAt` | As today: the session's start, and the Final check's end | Pacing's "completed today" is then true on the day of the Final check (§7). |

**Readers:**

- **Tuning**: drilled outcomes join the handoff line's `cards` to the session line's per-card
  values by `sessionId`, so kept cards measure exactly as before, and returned cards aren't
  drilled outcomes. One known under-count: a card returned once and handed off in a later session
  shows that later session's trials only. The earlier ones are in `cut.returned` if a future cost
  report wants them (optional).
- **Pacing's drill speed**: a median of per-card active time. Kept cards carry their whole drill
  time, and returned cards aren't in `anki`, so a part-drilled card can't pull the median down.
  Each finished-early session counts as one timed session toward the "3 sessions" and "last 10"
  windows, which is true: it's one sitting.
- **Cold-start record** (`estimates.json`): skipped when a cut session completes. Its multiplier
  would set the sitting's attempts against the kept cards' minimum, which overstates it. The value
  written at the stop stays. Nothing reads the file. Alternative: keep writing it, knowing it's
  inflated, or remove `record_cold_start` altogether (a separate cleanup).

## 6. The Final check

**Recommended: the kept cards get the normal Final check before the handoff.**

- It's the session Don would have had with Max cards = N: the same gate, the same `rd::final-miss`
  and `rd::hard` evidence, "Drill these cards again" for misses, and the same `drilled_cards` rule.
- From the stopped screen it runs right away. From the panel the next day, it runs then. The
  check is then a day later than usual, an extra spaced retrieval before Anki's first learning step.
  Resuming a stopped session already does this today. The line's `startedAt`/`finishedAt` and
  `cut.at` show the gap if tuning ever wants to split on it (optional).
- Cost: one cue-free pass over the kept cards, plus requeued misses.

Alternative (decision 2): hand off without it (costs in the decisions table). The cards handed off
early would never get a Final check. Their struggle score would be misses + reveals only.

## 7. Edge cases

| Case | What happens |
|---|---|
| **Stop mid-batch** | The batch's mastered cards are kept. Its `encoding`/`ready` cards (and any with one correct cycle answer) go back, and their progress is dropped and recorded in `cut.returned`. The confirmation says how many. |
| **Stop at the interstitial** | Nothing is dropped. |
| **A second partial handoff of the same session** | Can't happen: after the cut every card is mastered, so "Finish" isn't offered again. Stopping during the cut session's Final check gives a normal resumable save. The returned cards' later session is a new session, which can itself be finished early. |
| **Undo after a partial handoff** | As today: Edit → Undo re-suspends the handed-off cards. The save is already gone, and the cards are selectable again (the "unless suspended" rule). Returned cards were never touched. The history lines stay, as for any undone handoff. |
| **Discard / Start fresh on the cut save** | As today for any save: deleted. No session line is written (it's written at completion). Kept and returned cards are all still suspended and back in the pool. |
| **Start over a cut session waiting for its handoff** | As today: declines it (declined line), and the cards stay suspended. |
| **Cards deleted in Anki** | Before the cut: left out and listed. Between the cut and the handoff: skipped by `plan_handoff` (`missing`), as today. |
| **Cards edited in Anki** | Before the cut: changed cards go back (§1). After the cut, before the Final check: the cut save resumes through `check_resume`, as any save does ("Resume with saved text" or "Start fresh"). After the Final check: the handoff doesn't look at answers, as today. |
| **Only one card mastered** | A one-card Final check, then a one-card handoff. Fine. |
| **A note split by the cut** | The kept card is handed off, and the returned note-mate stays suspended (§4). Both cards' tags are note tags, so the note gets `rd::drilled` now. That doesn't stop the returned card being selected (selection is per card), but a note tagged `rd::drilled` is never held out. |
| **Pacing on the day of a panel cut** | Finishing early the next morning completes a session that day, so pacing treats today as done and shows tomorrow's N. Drilling the rest the same day completes another session, and N is recounted. Pacing is information only. |
| **Profile closes during the Final check** | As today: saves and stops. Resume continues the Final check. |

## 8. Tests and commits

**What's already proven and not retested:** `apply_handoff`, rollback, undo, the forecast, the tag
rules, `handed_off_at` and the selection exclusion, the engine's Final check, `check_resume`, and
pacing's and tuning's per-card readers. None of that code changes.

**New tests:**

1. **The cut (pure, `tests/storage/`)**:
   - kept = mastered, in original order, renumbered 0…k−1, with sources and `activeMsByItem`
     remapped, so every id still indexes sources;
   - item counters, `hardSpans` and overrides unchanged;
   - `cut.returned` holds each returned card's exact counters, and changed and missing cards are
     sorted correctly;
   - the result goes through `init_session` into the Final check with `finalCheckStartAttempts`
     equal to the attempts, and the queue is every kept id;
   - refused when 0 cards or every card is kept, for a drill-again save, and for a pending save;
   - `stats` and `activeMs` unchanged;
   - a save → resume → save round trip keeps `cut`.
2. **End to end (controller harness plus `SessionStore`)**:
   - a session of 6 cards in batches of 2, drilled through batch 1 plus one mastered card of
     batch 2, stopped, cut;
   - the Final check is answered, and completion writes **one** session line whose `cards`/`anki`
     are the 3 kept cards, with `cut.returned` for the 3 others;
   - the save is pending, and no cold-start value is written at the cut's completion.
3. **Handoff (scratch collection, `tests/anki_io/`)**:
   - a returned note-mate isn't a sibling and stays suspended;
   - the plan is otherwise identical to the same session uncut over the kept cards;
   - the line has `groups.returned`, and the dialog text has the returned line;
   - a following `select_cards` picks the returned cards first.
4. **Readers**: one tuning test and one pacing test, showing that a line with `cut` gives the same
   result as the same line without it. These are cheap and pin that `returned` cards never count
   as drilled.
5. **UI (`tests/ui`, local only)**: the button shows on the interstitial and the stopped screen
   only when 0 < kept < total, and the panel button is hidden while a window is open.

**Don's manual check** (what headless tests can't show): the button on the interstitial, the
stopped screen and the panel banner; the Final check starting in the same window; the confirmation
and handoff dialog wording.

**Commits** (each reviewable on its own, the gate green after each):

1. `feat(addon): cut a stopped session down to its mastered cards` — `sessions.finish_early`
   (pure) plus test group 1.
2. `feat(addon): history and handoff for a session finished early` — the `cut` block in the
   session line, skipping the cold-start record, returned cards excluded from siblings,
   `groups.returned`, the dialog line, plus test groups 2–4.
3. `feat(addon): Finish with N cards in the drill window and setup panel` —
   `launch.finish_early`, the buttons, the confirmation, plus test group 5.
4. `docs: partial handoff` — a `DECISIONS.md` section, the README's handoff section and the smoke
   checklist. This design doc stays as the record.

If decision 1 goes to a continuation session, add one commit between 2 and 3 for the continuation
save (its lifecycle, new id, renumbering and resume check). If decision 2 goes to skipping the
Final check, commit 2 also takes the handoff and tag changes from §6.

## Surprising in the code

- **`append_session` silently drops a second session line with the same `sessionId`**
  (`history_store.py`). Any design that reuses an id for a second part loses that part's history
  without an error.
- **The Final check serves every item, even ones already `finalDone`.** Its pass is built from all
  ids. So "mark them done and carry on" can't work without an engine change.
- **`check_resume` walks `sources`, not `items`.** A save whose sources outlive its items would
  report cards as missing or changed that aren't in the session. Any trimming must compact both.
- **A later handoff can remove `rd::hard` from a note an earlier one tagged.** `rd::hard` and
  `rd::final-miss` are "replaced" per note from the cards in this handoff. So if one session hands
  off a hard card and a later session hands off its easy note-mate, the tag goes, and that hard
  card drops out of "my rd::hard cards" (a tag search), even though `hard_cards` still records it
  as hard. This predates Phase 8. Partial handoffs make split notes a little more common. It's out
  of scope here, but worth a look.
- **`estimates.json` is still written on every stop and completion, and nothing reads it** (it's
  documented as unread since Phase 6). It could be removed in a later cleanup.
- **The session line's `stats` has no reader.** That's why keeping the sitting's totals there is
  safe.
