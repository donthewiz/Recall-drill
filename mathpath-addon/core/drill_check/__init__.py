"""Recall Drill's own math-answer checker, copied unchanged so the plugin grades a
formula card exactly the way the drill will.

Source: github.com/donthewiz/Recall-drill, anki-addon/recalldrill/, commit 522d866
(v0.6 math answer mode, PR #24).
  math_parse.py   sha256 be7b98068164fcea…
  math_answer.py  sha256 fc8180349b769648…
math_vendor.py is a stand-in (system SymPy instead of the add-on's vendor folder).

Never edit the two copied files here. When the drill's checker changes, copy them
again and update the commit and hashes above (evals/check_scripts.py checks the hashes).
"""

SOURCE_COMMIT = "522d866"
SHA256_PREFIX = {"math_parse.py": "be7b98068164fcea", "math_answer.py": "fc8180349b769648"}
