Recall Drill keeps local, non-syncing data here: in-progress sessions,
session history and per-profile settings.

Each Anki profile has its own folder, profiles/<profile name>/, because note,
card and deck ids only mean something in one profile's collection:

- mappings.json: which field is the answer / Extra, per note type and template
- deck_settings.json: per-deck drill settings
- hints.json: manual disambiguation hints, per card ("" turns a hint off)

A file the add-on can't read is renamed <name>.corrupt-<timestamp> and the
defaults are used; the renamed copy is left for you to inspect.

Anki preserves this folder when the add-on is upgraded. Nothing in it syncs
through AnkiWeb; signals that must sync (tags, scheduling) go into the
collection instead.
