"""Where the vendored SymPy lives and the one place that makes it importable (pure, lazy).

Anki's bundled Python has no SymPy, so the add-on ships SymPy and mpmath in its own
``vendor/`` folder (``docs/DECISIONS.md``, "v0.6 math answer mode"). Nothing here
runs at import time: the folder is put on ``sys.path`` and SymPy imported the first
time a math card needs an equivalence check. No network is involved.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

VENDOR_DIR = Path(__file__).resolve().parent.parent / "vendor"
"""``<add-on folder>/vendor``: next to ``recalldrill/``, ``web/`` and ``config.json``."""

PINS: dict[str, str] = {"sympy": "1.14.0", "mpmath": "1.3.0"}
"""The vendored versions. ``requirements-dev.txt`` pins the same ones."""

_cache: list[Any] = []


def ensure_path() -> None:
    """Put ``vendor/`` first on ``sys.path`` (once)."""
    entry = str(VENDOR_DIR)
    if entry not in sys.path:
        sys.path.insert(0, entry)


def sympy() -> Any | None:
    """The ``sympy`` module, imported on first use, or None when it can't be loaded
    (a broken install: the callers then fall back to the numeric check alone)."""
    if _cache:
        return _cache[0]
    ensure_path()
    try:
        module: Any = importlib.import_module("sympy")
    except Exception:  # a missing or damaged vendor folder must never break a drill
        module = None
    _cache.append(module)
    return module
