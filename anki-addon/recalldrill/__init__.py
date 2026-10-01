"""Recall Drill add-on package.

Layers (enforced by tests/test_layering.py):
- engine/: pure Python. No anki, aqt or Qt imports.
- anki_io/: may import anki and aqt.operations, never Qt.
- ui/: may import Qt.
"""

__version__ = "0.0.0"
