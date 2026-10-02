Global defaults for new drill sessions. They match the web app's `recall_drill_*` defaults. A deck's own settings (set in the Recall Drill panel: batch size, blind typings, cycle order, strict punctuation, word-ending tolerance, hints) win over `encode_reps`, `batch_size`, `stem_tolerance` and `cycle_order`. A value that is missing or of the wrong type takes its default.

- `encode_reps` (3): consecutive blind correct answers a card needs on its whole-answer step.
- `chunk_difficulty` (35): chunking percentage. 100 means never chunk.
- `batch_size` (5): cards per batch, 3 to 10, or 0 for the whole deck.
- `stem_tolerance` (true): accept light-stem differences as "near". Turn it off for terminology decks.
- `ladder_mode` ("cumulative"): "cumulative" (forward chaining) or "exhaustive". Same values as the web app's `LadderMode`.
- `cycle_order` ("shuffled"): "shuffled" or "inOrder". Same values as the web app's `CycleOrder`.
- `collision_catch` (true): add-on only. When a whole-answer trial (full answer, cycle, Final check) is answered with the exact answer of *another* card whose prompt conflicts with this one (same rule as the disambiguation hints), the drill says so and lets you try again. Nothing is graded and nothing is saved for that try.
- `play_audio_on_feedback` (true): add-on only. Play the card's answer audio when the feedback shows the full answer.
- `autoplay_question_audio` (false): add-on only. Play a card's question audio when it comes up in the drill (once per card, not on every trial of it).

**Handing off a finished session to Anki** (one undo step: Edit → Undo "Recall Drill handoff"):

- `handoff_mode` ("B"): how drilled *new* cards get their first Anki review. "B": they stay new, go to the front of the new queue and are buried until tomorrow, so Anki's learning steps run and the FSRS optimizer keeps them. "A": they become review cards due tomorrow (no learning steps; the FSRS optimizer never trains on them). Already-scheduled cards keep their schedule either way.
- `handoff_siblings` (true): also hand off the suspended new cards of the same notes that weren't drilled (e.g. the Normal card of a drilled Reverse card): unsuspended, queued right after the drilled cards, buried until tomorrow.
- `hard_threshold` (3): a card's misses + reveals + Final-check misses at or above this tags its note `rd::hard`.
- `clear_flag_on_handoff` (true): remove the red flag from drilled cards that have it.
- `tag_long` (false): tag notes whose answer was drilled in chunks `rd::long`.

**Measurement** (Tools → Recall Drill: tuning report):

- `min_words_to_chunk` (8): answers with at most this many words are drilled whole; longer ones are chunked. The tuning report can suggest a new value, applied only when you confirm it.
- `holdout_pct` (0, off): the default **Holdout %** for decks without their own. Percent of eligible new cards, in deck sessions only, that skip the drill and go to Anki as plain new cards at the handoff (tagged `rd::holdout`), as a fair comparison for the drilled cards. Set it per deck in the Recall Drill panel (Holdout %, saved with the deck's settings). Which cards is decided by a hash, so changing the % only changes which cards are held out from now on. At most 50.
- `holdout_exclude` (true): leave cards tagged `rd::holdout` out of later sessions, so the control stays undrilled.
- `min_n` (30): the tuning report's minimum sample per compared group. Smaller groups show "n too small", and no suggestion is made from them.
