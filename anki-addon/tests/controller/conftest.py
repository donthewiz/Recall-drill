from __future__ import annotations

import sys
from pathlib import Path

# Make tests/controller/controller_support.py importable, and the engine tests'
# golden helpers (tests/engine/session_runner.py, engine_test_support.py) for
# the parity test (pytest runs with --import-mode=importlib, which doesn't put
# test directories on sys.path).
_HERE = Path(__file__).resolve().parent
for _path in (_HERE, _HERE.parent / "engine", _HERE.parents[1] / "tools"):
    if str(_path) not in sys.path:
        sys.path.insert(0, str(_path))
