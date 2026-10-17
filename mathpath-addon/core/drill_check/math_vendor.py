"""Stand-in for Recall Drill's ``math_vendor`` (the only file not copied).

The add-on loads SymPy from its own ``vendor/`` folder; here the plugin's Python
already has SymPy, so this just imports it. Same API: ``sympy()`` returns the
module or None.
"""

from __future__ import annotations

from typing import Any

_cache: list[Any] = []


def sympy() -> Any | None:
    if _cache:
        return _cache[0]
    try:
        import sympy as module  # noqa: PLC0415
    except Exception:  # noqa: BLE001
        module = None
    _cache.append(module)
    return module
