Global defaults for new drill sessions. They match the web app's `recall_drill_*` defaults. Nothing reads this file yet: the Phase 3a drill controller takes `collision_catch` and `play_audio_on_feedback` as arguments, and Phase 3b wires the file in.

- `encode_reps` (3): consecutive blind correct answers a card needs on its whole-answer step.
- `chunk_difficulty` (35): chunking percentage. 100 means never chunk.
- `batch_size` (5): cards per batch, 3 to 10, or 0 for the whole deck.
- `stem_tolerance` (true): accept light-stem differences as "near". Turn it off for terminology decks.
- `ladder_mode` ("cumulative"): "cumulative" (forward chaining) or "exhaustive". Same values as the web app's `LadderMode`.
- `cycle_order` ("shuffled"): "shuffled" or "inOrder". Same values as the web app's `CycleOrder`.
- `collision_catch` (true): add-on only. When a whole-answer trial (full answer, cycle, Final check) is answered with the exact answer of *another* card whose prompt conflicts with this one (same rule as the disambiguation hints), the drill says so and lets you try again. Nothing is graded and nothing is saved for that try.
- `play_audio_on_feedback` (true): add-on only. Play the card's answer audio when the feedback shows the full answer.
