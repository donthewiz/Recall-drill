Math Path keeps local, non-syncing data here: your progress through each recipe's learn
stages and the history of every problem you solved.

Each Anki profile has its own folder, profiles/<profile name>/, because note, card and deck ids
only mean something in one profile's collection:

- progress.json: per Math Path note, the learn stage, faded level, unaided solo count and last seen
- history.jsonl: one line per problem (the seed, what you typed, the help you used, the rating
  given) and one per handoff to Anki

A file the add-on can't read is renamed <name>.corrupt-<timestamp> and the defaults are used; the
renamed copy is left for you to inspect.

Anki preserves this folder when the add-on is upgraded. Nothing in it syncs through AnkiWeb;
what must sync (tags, scheduling) goes into the collection instead.
