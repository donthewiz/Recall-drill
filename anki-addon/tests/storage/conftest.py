from __future__ import annotations

import sys
from pathlib import Path

# Make the controller tests' builders (tests/controller/controller_support.py)
# and the Anki fixtures (tests/anki_io/anki_fixtures.py) importable (pytest runs
# with --import-mode=importlib, which doesn't put test directories on sys.path).
_TESTS = Path(__file__).resolve().parent.parent
for _path in (_TESTS / "controller", _TESTS / "anki_io"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
