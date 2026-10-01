Global defaults for new drill sessions. They match the web app's `recall_drill_*` defaults. Nothing reads them yet (Phase 0).

- `encode_reps` (3): consecutive blind correct answers a card needs on its whole-answer step.
- `chunk_difficulty` (35): chunking percentage. 100 means never chunk.
- `batch_size` (5): cards per batch, 3 to 10, or 0 for the whole deck.
- `stem_tolerance` (true): accept light-stem differences as "near". Turn it off for terminology decks.
- `ladder_mode` ("cumulative"): "cumulative" (forward chaining) or "exhaustive". Same values as the web app's `LadderMode`.
- `cycle_order` ("shuffled"): "shuffled" or "inOrder". Same values as the web app's `CycleOrder`.
