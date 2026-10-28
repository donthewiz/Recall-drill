# triage-addon/: Card Triage add-on

Loads when you work in this folder. The full record is `docs/DECISIONS.md`.

## What it is

A standalone add-on (package `card_triage`) for Anki's normal review: one key sets a stuck
**new or learning** card aside without grading it (red flag, tag `triage`, suspended, marker in
the card's `custom_data`), and **Release all** puts every set-aside card back. It imports nothing
from Recall Drill or Math Path and does not mention them. Anki is the only scheduler: setting
aside or releasing never grades a card, writes no review-log row and never touches `due`/`type`.

## Layout and layers (`tests/test_layering.py`)

| Part | Rules |
|---|---|
| `card_triage/*.py` (top level) | Qt-free **and** Anki-free. Strict pyright |
| `card_triage/anki_io/` | May import `anki` and `aqt.operations`, never Qt. Strict pyright |
| `card_triage/ui/` | Qt. Standard pyright. Style only the add-on's own dialog and bar, never `QApplication.setStyleSheet` |

No module imports `recalldrill` or `math_path` (tested).

## Things that bite

- **The marker is the only authority.** A card without `custom_data["tri"]` is never set aside,
  unsuspended, reflagged or retagged. Other tools' suspended cards (siblings too) stay as they are.
- **Anki's limits:** `custom_data` is at most 100 bytes and a key at most 8 bytes. Writing over
  them is refused (a tooltip, nothing changed).
- **One undo step** = `add_custom_undo_entry` … `merge_undo_entries` (`anki_io/undo.py`), run through
  `CollectionOp` so the reviewer refreshes and moves on. Anki keeps only 30 undo steps, so writes
  are bulk calls.
- **Keys:** the reviewer's `_shortcutKeys` is not the whole story. The main window's global keys
  (d, s, a, b, t, Shift+t, y) and its menu shortcuts (F, /, Ctrl+Z…) clash with a state shortcut
  too (Qt makes the pair ambiguous and neither fires). `card_triage/keys.py` lists all three;
  `tests/test_keys.py` re-reads the installed `aqt` source so the lists can't drift, and Settings
  also reads the live menu shortcuts (`entry.action_keys`).
- **The `webview_did_receive_js_message` filter** sees every web view's messages: only
  `card_triage:` ones are ours; pass everything else on unchanged.
- **The bar** is injected into the reviewer page and removed on every new question. QtWebEngine
  can't start offscreen, so UI tests use stand-ins and the bar's look is checked in Chromium.

## Tests

- From the repo root: `triage-addon/.venv/bin/python -m pytest triage-addon/tests -q`.
- Always scratch collections (`tests/anki_io/scenes.py`), never a real profile.
- Gate: `triage-addon/.venv/bin/ruff check triage-addon`, pytest, and
  `cd triage-addon && .venv/bin/pyright`.
