# Copied code: never edit these files here

Everything in `core/` is copied **unchanged** from the anki-math-cards plugin **v1.1.2**
(`skills/anki-math-cards/scripts/`), the skill that writes the cards and the problem
recipes. Math Path grades a learner exactly the way the skill checked the recipe.

`core/drill_check/` is the plugin's own copy of Recall Drill's math checker
(`anki-addon/recalldrill/math_parse.py` and `math_answer.py` at commit 522d866),
plus the plugin's stand-in `math_vendor.py` (it imports whatever `sympy` is on
`sys.path`; in Anki that is Math Path's `vendor/`).

| File | SHA-256 |
|---|---|
| `verify_math.py` | `8f604aa69033da9bbc7db5bce9e0d413292648ac517bf0e6e0f7be61fb58e77a` |
| `recipe_validator.py` | `b04c655b203c1169bb123b0bacd889a0aa8aabfef2b2d5cf10cc5649dbb4f2ca` |
| `drill_check/__init__.py` | `5f482152f0444102c671f417499380ba570a4254c39926e9fd269e2ba16b4fd8` |
| `drill_check/math_answer.py` | `fc8180349b76964896b50c8c922662bf07b10d2a63441e1d28f43daaccdad2d1` |
| `drill_check/math_parse.py` | `be7b98068164fceae66b02051e109cd8fd4903f85d4bcf32025a4eee20106697` |
| `drill_check/math_vendor.py` | `70899c6a5aac7e9d4ac33ca06fd6ae39f5fed5b3799734613f1a463620674211` |

When the plugin changes, copy the files again from the new plugin version and update
this table; a test checks the hashes. Fix bugs in the plugin, never here; work around
them in Math Path's own adapter code until the plugin is updated.

`tests/fixtures/recipes/ch03/` holds the 30 College Algebra Chapter 3 recipes
(Bittinger 7e sections 3.1-3.5) the skill wrote on 2026-10-16/17, all passing the
plugin's validator (20 instances each). `tests/fixtures/recipes/v2_examples/` holds the
plugin's 7 format-2 examples. `docs/recipe-format.md` is the plugin's format reference
(v1.1.2), copied for reading.
