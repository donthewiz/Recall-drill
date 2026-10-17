"""The one place that touches ``sys.path`` for SymPy and the copied checker (pure, lazy).

Anki's bundled Python has no SymPy, so the add-on ships SymPy and mpmath in ``vendor/`` and
the plugin's checker files in ``core/`` (``core/SOURCE.md``). Nothing here runs at import
time: the first call to :func:`load` puts ``vendor/`` and ``core/`` on ``sys.path`` and imports
the modules, which takes a second or two, so it runs off the main thread (the engine asks for
it as soon as the window opens). Every other module reaches SymPy and the core through the
:class:`Core` this returns, never by importing them.
"""

from __future__ import annotations

import importlib
import sys
import threading
import warnings
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = ROOT / "vendor"
CORE_DIR = ROOT / "core"

PINS: dict[str, str] = {"sympy": "1.14.0", "mpmath": "1.3.0"}
"""The vendored versions."""


@dataclass(frozen=True)
class Core:
    """The imported modules. All ``Any``: they are third-party and copied code."""

    sympy: Any
    verify: Any
    """``core/verify_math.py``: ``check_answer``, ``form_problems``, ``parse_keyboard``, ..."""
    validator: Any
    """``core/recipe_validator.py``: ``fill``, ``tex``, ``_truth``, ``check_step``, ..."""
    parse: Any
    """``core/drill_check/math_parse.py``: ``latex_to_keyboard``, ``to_latex``, ``parse``."""


_lock = threading.Lock()
_core: list[Core] = []


def ensure_paths() -> None:
    """Put ``vendor/`` first and ``core/`` second on ``sys.path`` (once each)."""
    for entry in (str(CORE_DIR), str(VENDOR_DIR)):
        if entry not in sys.path:
            sys.path.insert(0, entry)


def is_loaded() -> bool:
    return bool(_core)


def load() -> Core:
    """Import SymPy and the core (once, thread-safe) and return them."""
    if _core:
        return _core[0]
    with _lock:
        if _core:
            return _core[0]
        ensure_paths()
        sympy: Any = importlib.import_module("sympy")
        _quiet(sympy)
        core = Core(
            sympy=sympy,
            verify=importlib.import_module("verify_math"),
            validator=importlib.import_module("recipe_validator"),
            parse=importlib.import_module("drill_check.math_parse"),
        )
        _core.append(core)
        return core


def _quiet(sympy: Any) -> None:
    """SymPy 1.14 warns about ``Mul`` of a ``Tuple`` inside its own parser for some inputs; the
    warning is noise for the learner (and for Anki's console)."""
    try:
        category = importlib.import_module("sympy.utilities.exceptions").SymPyDeprecationWarning
    except Exception:  # noqa: BLE001
        return
    warnings.filterwarnings("ignore", category=category)
