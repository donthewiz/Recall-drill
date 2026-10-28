# Card Triage

An Anki add-on for the card you are **stuck on** in normal review. One key sets a **new or learning** card aside without grading it, so it stays exactly as it was and you can study it another way later. Anki stays the only scheduler: setting aside and releasing never grade a card, never write a review-log row and never touch a card's type, due position or learning state.

Standalone: it needs nothing else installed.

## What it does (v0.1)

- **Set aside** (key `X` by default, question or answer side): the card is suspended, flagged red and its note tagged `triage`; Anki shows the next card. The card's old flag is kept in its `custom_data` (`tri`). One undo step, `Set aside card` (Ctrl+Z or `u`). Review and relearning cards are left alone.
- **Release all** (Tools → Card Triage → Release all set-aside cards…): asks first, then puts every set-aside card back: unsuspended, old flag restored (only if it is still red), marker and tag removed. One undo step.
- **Show set-aside cards** (Tools → Card Triage): Browse, searching `has-cd:tri`.
- **Prompt bar** (off by default): after N seconds on a card, or when a learning card has N Agains, a slim bar at the top offers `Set aside (X) · Keep going`. It never takes keyboard focus and goes away with the card.
- **Settings** (Tools → Card Triage → Settings…): the key and the two prompts. Keys Anki already uses are refused.

Only cards with Card Triage's marker are ever touched; cards suspended by anything else stay as they are, siblings included.

## Install for development

Link this folder into Anki's `addons21` folder under the name `card_triage_dev` (a junction on Windows, a symlink elsewhere), then fully close and reopen Anki.

## Tests

```sh
triage-addon/.venv/bin/ruff check triage-addon
triage-addon/.venv/bin/python -m pytest triage-addon/tests -q
cd triage-addon && .venv/bin/pyright
```

Scratch collections only, never a real profile. Decisions: `docs/DECISIONS.md`.
