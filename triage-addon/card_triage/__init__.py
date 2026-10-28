"""Card Triage add-on package.

Layers (enforced by tests/test_layering.py):
- the top-level modules: pure Python. No anki, aqt or Qt imports.
- anki_io/: may import anki and aqt.operations, never Qt.
- ui/: may import Qt.
Nothing here imports Recall Drill or Math Path.
"""

VERSION = "0.1.1"
"""The packaged version (kept equal to ``manifest.json`` ``human_version`` by a test)."""

__version__ = VERSION
