from __future__ import annotations

import sys
from pathlib import Path

# Make tests/tuning/tuning_support.py importable (pytest runs with
# --import-mode=importlib, which doesn't put test directories on sys.path).
_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))
