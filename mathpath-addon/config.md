Global settings for Math Path. A value that is missing or of the wrong type takes its default. Change them in Tools → Add-ons → Math Path → Config.

- `problems_per_session` (default 3, 1 to 12): how many recipes one learn session takes from a section. Recipes already learned, and locked ones, are left out; the session goes through them one problem each in turn, so the practice on one recipe is spaced by problems from the others.
- `auto_open_in_review` (default true): when Anki's reviewer shows a Math Path card, the Math Path window opens by itself with a fresh problem. With false, the card shows a "Solve in Math Path" link instead.
- `prereq_lock` (default true): a recipe whose prerequisite recipe (one that exists as a Math Path note) is not learned yet is locked: the progress map says what it needs, and learn sessions skip it. With false, nothing is locked.
