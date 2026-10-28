Settings for Card Triage. Change them in Tools → Card Triage → Settings… (or the Config button on the Add-ons screen). A value that is missing or of the wrong type takes its default.

- `set_aside_key` (default `x`): the reviewer key that sets the current card aside. One key (`X`) or a combination (`Ctrl+X`). A key Anki already uses (`e`, `r`, `u`, `1`, `t`, `d`…) is refused in the dialog, and a hand-edited one falls back to the default.
- `timer_prompt` (default false): when on, a slim bar offers to set the card aside after `timer_seconds` on it, counted from when its question shows.
- `timer_seconds` (default 30, 5 to 600).
- `again_prompt` (default false): when on, a learning card that has been answered Again `again_count` times while learning gets the bar as soon as its question shows.
- `again_count` (default 2, 1 to 10).
