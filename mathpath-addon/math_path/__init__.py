"""Math Path add-on package.

Layers (enforced by tests/test_layering.py):
- the top-level modules and ``engine``-style helpers: pure Python. No anki, aqt or Qt imports.
- anki_io/: may import anki and aqt.operations, never Qt.
- ui/: may import Qt.
"""

VERSION = "0.1.1"
"""The packaged version (build.py writes it to the manifest)."""

__version__ = VERSION
