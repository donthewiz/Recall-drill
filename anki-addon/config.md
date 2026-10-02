Global defaults for new drill sessions. They match the web app's `recall_drill_*` defaults. A deck's own settings (set in the Recall Drill panel: batch size, blind typings, cycle order, strict punctuation, word-ending tolerance, hints) win over `encode_reps`, `batch_size`, `stem_tolerance` and `cycle_order`. A value that is missing or of the wrong type takes its default. Each key shows its default and the phase that introduced it (Phase 0 is the scaffold: the keys that mirror the web app's `recall_drill_*` defaults). Change them in Tools → Add-ons → Recall Drill → Config. 27 keys in all.

- `encode_reps` (default 3; Phase 0): consecutive blind correct answers a card needs on its whole-answer step.
- `chunk_difficulty` (default 35; Phase 0): chunking percentage. 100 means never chunk.
- `batch_size` (default 5; Phase 0): cards per batch, 3 to 10, or 0 for the whole deck.
- `stem_tolerance` (default true; Phase 0): accept light-stem differences as "near". Turn it off for terminology decks.
- `ladder_mode` (default "cumulative"; Phase 0): "cumulative" (forward chaining) or "exhaustive". Same values as the web app's `LadderMode`.
- `cycle_order` (default "shuffled"; Phase 0): "shuffled" or "inOrder". Same values as the web app's `CycleOrder`.
- `collision_catch` (default true; Phase 3a): add-on only. When a whole-answer trial (full answer, cycle, Final check) is answered with the exact answer of *another* card whose prompt conflicts with this one (same rule as the disambiguation hints), the drill says so and lets you try again. Nothing is graded and nothing is saved for that try.
- `play_audio_on_feedback` (default true; Phase 3a): add-on only. Play the card's answer audio when the feedback shows the full answer.
- `autoplay_question_audio` (default false; Phase 3b): add-on only. Play a card's question audio when it comes up in the drill (once per card, not on every trial of it).

**Handing off a finished session to Anki** (one undo step: Edit → Undo "Recall Drill handoff"):

- `handoff_mode` (default "B"; Phase 4): how drilled *new* cards get their first Anki review. "B": they stay new, go to the front of the new queue and are buried until tomorrow, so Anki's learning steps run and the FSRS optimizer keeps them. "A": they become review cards due tomorrow (no learning steps; the FSRS optimizer never trains on them). Already-scheduled cards keep their schedule either way.
- `handoff_siblings` (default true; Phase 4): also hand off the suspended new cards of the same notes that weren't drilled (e.g. the Normal card of a drilled Reverse card): unsuspended, queued right after the drilled cards, buried until tomorrow.
- `hard_threshold` (default 3; Phase 4): a card's misses + reveals + Final-check misses at or above this tags its note `rd::hard`.
- `clear_flag_on_handoff` (default true; Phase 4): remove the red flag from drilled cards that have it.
- `tag_long` (default false; Phase 4): tag notes whose answer was drilled in chunks `rd::long`.

**Measurement** (Tools → Recall Drill: tuning report):

- `min_words_to_chunk` (default 8; Phase 5): answers with at most this many words are drilled whole; longer ones are chunked. The tuning report can suggest a new value, applied only when you confirm it.
- `holdout_pct` (default 0, off; Phase 5): the default **Holdout %** for decks without their own. Percent of eligible new cards, in deck sessions only, that skip the drill and go to Anki as plain new cards at the handoff (tagged `rd::holdout`), as a fair comparison for the drilled cards. Set it per deck in the Recall Drill panel (Holdout %, saved with the deck's settings). Which cards is decided by a hash, so changing the % only changes which cards are held out from now on. At most 50.
- `holdout_exclude` (default true; Phase 5): leave cards tagged `rd::holdout` out of later sessions, so the control stays undrilled.
- `exclude_handed_off_new` (default true; Phase 6 fix): leave out cards a handoff sent to Anki (the drilled cards, under A or B, their siblings, holdout cards) until Anki has rated them since the handoff, so a session before your Anki reviews doesn't drill yesterday's cards again. A suspended card isn't left out (undoing a handoff re-suspends its cards, so they're drillable again). Per card: a note's other cards that were never handed off stay selectable. Doesn't apply to "my rd::hard cards".
- `min_n` (default 30; Phase 5): the tuning report's minimum sample per compared group. Smaller groups show "n too small", and no suggestion is made from them.

**Difficulty** (cards that already have review history; new cards have no FSRS data and keep the deck's settings):

- `difficulty_adjust` (default true; Phase 6): the default for a deck's **Adjust reps by difficulty** (Recall Drill panel, saved with the deck's settings).
- `hard_d` (default 7; Phase 6): a card whose FSRS difficulty (1–10) is at least this gets one more blind typing, and chunks earlier.
- `easy_d` (default 3; Phase 6): a card whose FSRS difficulty is at most this gets one fewer blind typing.
- `min_encode_reps` (default 2; Phase 6): an easy card never goes below this many blind typings (nor below the deck's own setting, if that is lower).
- `hard_chunk_shift` (default 2; Phase 6): a hard card's chunk threshold is `min_words_to_chunk` minus this, never under 4.
- Without FSRS data, a reviewed card with 3+ lapses, an ease under 200% or the `leech` tag gets one more blind typing.
- `skip_min_stability` (default 30; Phase 6): with `skip_max_difficulty`, defines the **stable** class: a card with FSRS stability at least this many days, difficulty at most `skip_max_difficulty`, and not a leech. The class is off by default; the panel counts the stable cards it skips.
- `skip_max_difficulty` (default 5; Phase 6): the difficulty ceiling of the stable class (see `skip_min_stability`).

**Pacing** (Recall Drill panel → Pacing; target date and drill weekdays are saved per deck in `pacing.json`):

- `idle_cap_seconds` (default 120; Phase 6): active drill time counts the time between your actions in the drill window, but at most this much per gap, so a break doesn't count. The panel's drill-time figures come from that measured time.
