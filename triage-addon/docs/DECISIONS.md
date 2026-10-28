# Card Triage: decisions and facts

Decisions by Don (2026-10-28) or made while building (**built**), and facts checked against the installed `aqt`/`anki` 26.8.1.

## Why

Don wants a quick way to set aside a new card he is stuck on during normal review, without grading it, so it stays new and can be studied another way later. Card Triage is its **own add-on** (`triage-addon/`, package `card_triage`, name "Card Triage"), standalone: it imports nothing from Recall Drill or Math Path (a test enforces it). **Anki is the only scheduler.**

## Settled

- Setting aside never grades a card and writes no review-log row. A new card stays new (type, `due`), a learning card keeps its learning state.
- Marker: the card's `custom_data` key `tri` = the flag before setting aside (0 to 7); other keys kept. Search: `has-cd:tri`. Visible: red flag (1) and note tag `triage`, both fixed.
- A card without `tri` is never set aside, unsuspended, reflagged or retagged.
- Only new (type 0) and learning (type 1) cards. Review and relearning cards are refused with a tooltip.

## Decisions

- **2026-10-28, default key `X`, not `T` (Don, after a test).** Anki's main window binds `t` and `Shift+t` to Statistics (`AnkiQt.setupKeys`, also d, s, a, b, y). A reviewer state shortcut with the same key makes Qt report the pair as ambiguous and *neither fires* (reproduced offscreen: `activatedAmbiguously`). `Reviewer._shortcutKeys` does not list these, so the key-clash check covers both lists: `card_triage/keys.py`, kept honest by `tests/test_keys.py`, which reads the installed `aqt` source (reviewer, Korean keys, main window). The Settings dialog also adds the reviewer's live keys (answer keys can be rebound).
- **built** Key grammar: one key with optional `Ctrl`/`Alt`/`Shift`/`Meta`, or a named key (F1-F12, Space…). Plain letters compare case-insensitively (`X` = `x`, as Qt treats `QKeySequence("X")`); `Shift+t` is a different key. A hand-edited bad key falls back to `x`.
- **built** Settings uses a text field for the key, not a key-capture widget: simple, testable, and it shows exactly what is saved. Errors show inline in the dialog.
- **built** Saving settings while reviewing re-applies the reviewer's shortcuts at once.
- **built** Cards that can't be set aside and why: already marked (nothing changes), already suspended by something else (refused, never marked), `custom_data` unreadable or no room (over 100 bytes / key over 8 bytes) → tooltip, nothing changed.
- **built** Release unsuspends only cards still suspended and with the marker; flag restored only if still red; `tri` removed (other keys kept); `triage` removed from a note when none of its cards still has `tri` (all marked cards are released together, so in practice at once). A `triage` tag the user added by hand to such a note is removed too. A marker with a bad value restores flag 0. A tooltip says how many were released.
- **built** Bar: `Set aside (X)` does exactly what the key does; `Keep going` hides it for this card (the timer won't fire again). Pressing the key while the bar shows works the same, and the bar goes with the next card. If the Again-count bar shows, the timer isn't started (no second prompt). The timer counts from the card's first question through its answer side; the same card drawn again (edit, refresh) does not restart it; answering the card resets, so a learning card that returns at once starts fresh. One single-shot `QTimer`, stopped on every new question, answer, dismiss and when the reviewer closes. Eligibility: new or learning, not suspended, no marker.
- **built** Bar messages carry the prefix `card_triage:`; the `webview_did_receive_js_message` filter claims only those and returns `handled` untouched for all else.
- **built** Release asks with `askUser`; 0 set-aside cards → tooltip `No set-aside cards.`, no dialog.

## Found in review (2026-10-28, Opus review of the v0.1.0 build)

- **Menu shortcuts clash too.** The main window's menu items have their own keys (`_aqt/forms/main_qt6.py`: `F` Create Filtered Deck, `/` Study Deck, `Ctrl+Z` Undo, `Ctrl+Shift+Z` Redo, `Ctrl+Q`, `Ctrl+P`, `Ctrl+E`, `Ctrl+Shift+I`, `Ctrl+Shift+P`, `Ctrl+Shift+N`, `Ctrl+Shift+A`, `Ctrl+0`, `F1`). A set-aside key on one of them is ambiguous to Qt exactly like `T`: neither fires (reproduced offscreen, now a test). Fix: `keys.py` lists them as "Anki's menus" (a test re-reads the form source), and the Settings dialog also reads every menu shortcut on Anki's main window at that moment (`entry.action_keys`), which catches other add-ons' menu keys too. Keys other add-ons bind with a bare `QShortcut` still can't be known.
- Checked and fine: gates (ruff, pytest, pyright); the bar in light and dark, both texts; the Settings dialog with the clash message; the Release confirm; a scratch probe with a scheduler-made learning card, a prior orange flag, a prior `custom_data` key, one card of a two-card note whose sibling another tool suspended, 3 other-tool red-flagged `rd::drill` cards, one undo, one hand-unsuspend, then release, undo and redo of the release: every card back to its start state field by field, no revlog rows, other-tool cards and the sibling untouched.

## Facts (Anki 26.8.1)

| Item | Fact | Consequence |
|---|---|---|
| Undo | `add_custom_undo_entry` … `merge_undo_entries` makes several writes one step; Anki keeps 30 steps | Bulk calls only: `update_cards`, one `suspend_cards`, one `unsuspend_cards`, one `bulk_add`/`bulk_remove` |
| Reviewer refresh | `CollectionOp` result changes with `study_queues` make the reviewer fetch the next card | The merged step's changes carry `study_queues` (tested) |
| Search | `has-cd:tri` finds cards with that `custom_data` key (not suspended-only, not tag-based) | Release and Show use it |
| Revlog | A learn-type Again row is `type = 0, ease = 1` (checked with a card the scheduler really answered) | `learn_again_count` |
| Night mode | Anki adds `night-mode` to `<html>` and `nightMode`/`night_mode` to `<body>` | The bar's dark colours hang off those classes |
| Shortcuts | `AnkiQt._normalize_shortcuts` dedups only within one list | Main-window globals and state shortcuts are separate lists, hence the ambiguity |
| Config button | `addonManager.setConfigAction(module, fn)`; a truthy return counts as handled | Opens the Settings dialog |

## Versions and tooling

Anki 26.08.1, Python 3.13 (`min_point_version` 260801). Dev pins as Math Path (`requirements-dev.txt`). Layers in `tests/test_layering.py`; strict pyright on the Qt-free modules and `anki_io/`. The bar's look is tested in real Chromium (the cloud image's Chromium is used when the pinned Playwright's build is missing).

## Not in v0.1

Recall Drill picking up set-aside cards; `.ankiaddon` packaging; AnkiWeb listing; review and relearning cards.
