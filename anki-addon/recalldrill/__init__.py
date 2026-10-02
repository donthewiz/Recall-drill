"""Recall Drill add-on package.

Layers (enforced by tests/test_layering.py):
- engine/: pure Python. No anki, aqt or Qt imports.
- anki_io/: may import anki and aqt.operations, never Qt.
- ui/: may import Qt.
"""

VERSION = "0.1.0"
"""The packaged version (build.py writes it to the manifest)."""

__version__ = VERSION
