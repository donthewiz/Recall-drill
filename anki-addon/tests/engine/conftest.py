from __future__ import annotations

import sys
from pathlib import Path

# Make tests/engine/engine_test_support.py and session_runner.py importable
# (pytest runs with --import-mode=importlib, which doesn't put test directories
# on sys.path), and anki-addon/tools/simulate.py with them.
_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE.parents[1] / "tools"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
