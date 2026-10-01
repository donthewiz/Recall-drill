from __future__ import annotations

import sys
from pathlib import Path

# Make tests/engine/engine_test_support.py importable (pytest runs with
# --import-mode=importlib, which doesn't put test directories on sys.path).
_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)
