"""JavaScript semantics the engine depends on, in one place.

The TS engine in ``src/utils/`` is the reference. Wherever Python's built-ins
behave differently from the JS operation the TS code uses, the engine calls a
helper from this module instead. No other engine module re-implements any of
this.

Differences handled here (each has a golden case in ``tests/golden/``):

- ``Math.round`` rounds half toward +Infinity. Python's ``round()`` rounds half
  to even, so ``round(2.5) == 2`` where JS gives 3. Use :func:`js_round`.
  ``round(`` is banned elsewhere in ``engine/`` by a test.
- JS ``\\s`` (and so ``trim()`` and ``split(/\\s+/)``) is the ECMAScript
  WhiteSpace + LineTerminator set, :data:`JS_WS`. Python's ``str.strip()``,
  ``str.split()`` and ``re``'s ``\\s`` add U+001C-U+001F and U+0085 and leave
  out U+FEFF. Use :func:`js_trim`, :func:`js_split_ws` and :data:`WS_RE`.
- JS ``\\d`` without the ``u`` flag is ASCII ``[0-9]``. Python's ``re`` ``\\d``
  matches every Unicode decimal digit (Arabic-Indic, Devanagari, ...). Engine
  patterns spell out ``[0-9]``; a test bans ``\\d``, ``\\s``, ``\\w`` and ``\\b``
  in engine patterns outside this module.
- Python's ``$`` also matches just before a trailing newline. Engine patterns
  use ``\\Z`` where the TS pattern has ``$``.
- ``Math.imul``, ``| 0`` and ``>>> 0`` wrap to 32 bits. Python ints don't. Use
  :func:`imul`, :func:`i32` and :func:`u32`.
- ``String.prototype.charCodeAt`` walks UTF-16 code units, Python walks code
  points. Use :func:`utf16_units`.
- JS truthiness (``||``, ``?:``, ``!x``) treats ``[]`` and ``{}`` as true.
  Python treats empty containers as false. Use :func:`truthy`.
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterator

# ECMAScript WhiteSpace (TAB, VT, FF, ZWNBSP, and every Zs character) plus
# LineTerminator (LF, CR, LS, PS). This is exactly what JS `\s` matches.
# Spelled as code points, not string escapes: escapes for invisible
# characters get turned into the raw characters by formatters and editors.
JS_WS_CHARS = "".join(
    chr(cp)
    for cp in (
        *(0x09, 0x0A, 0x0B, 0x0C, 0x0D, 0x20, 0xA0, 0x1680),
        *range(0x2000, 0x200B),  # U+2000..U+200A
        *(0x2028, 0x2029, 0x202F, 0x205F, 0x3000, 0xFEFF),
    )
)
JS_WS = "[" + JS_WS_CHARS + "]"
"""The JS ``\\s`` set as a regex character class, for use inside patterns."""

WS_RE = re.compile(JS_WS + "+")
"""JS ``/\\s+/``."""

_WS_SET = frozenset(JS_WS_CHARS)


def is_js_ws(ch: str) -> bool:
    """Whether the one-character string ``ch`` matches JS ``\\s``."""
    return ch in _WS_SET


def js_trim(s: str) -> str:
    """JS ``String.prototype.trim``."""
    return s.strip(JS_WS_CHARS)


def js_split_ws(s: str) -> list[str]:
    """JS ``s.split(/\\s+/)``.

    Keeps the empty strings JS yields at the ends: ``" a b "`` gives
    ``['', 'a', 'b', '']`` and ``""`` gives ``['']``.
    """
    return WS_RE.split(s)


def js_round(x: float) -> int:
    """JS ``Math.round`` for a finite number: the nearest integer, ties toward +Infinity.

    Not ``math.floor(x + 0.5)``: that addition itself rounds, so it gives 1 for
    0.49999999999999994 and 2**52 + 2 for 2**52 + 1, where JS gives 0 and
    2**52 + 1. ``x - math.floor(x)`` is exact for every finite double.
    """
    floor = math.floor(x)
    return floor + 1 if x - floor >= 0.5 else floor


def i32(x: int) -> int:
    """JS ``x | 0`` (ToInt32) for an integer value."""
    x &= 0xFFFFFFFF
    return x - 0x100000000 if x & 0x80000000 else x


def u32(x: int) -> int:
    """JS ``x >>> 0`` (ToUint32) for an integer value."""
    return x & 0xFFFFFFFF


def imul(a: int, b: int) -> int:
    """JS ``Math.imul``: 32-bit signed multiplication."""
    return i32(u32(a) * u32(b))


def utf16_units(s: str) -> Iterator[int]:
    """The UTF-16 code units of ``s``, as JS ``charCodeAt`` sees them."""
    data = s.encode("utf-16-le", "surrogatepass")
    for i in range(0, len(data), 2):
        yield data[i] | (data[i + 1] << 8)


def truthy(x: object) -> bool:
    """JS truthiness.

    Only ``false``, ``0``, ``NaN``, ``''``, ``null`` and ``undefined`` are falsy.
    """
    if x is None or isinstance(x, bool):
        return bool(x)
    if isinstance(x, int | float):
        return x == x and x != 0
    if isinstance(x, str):
        return x != ""
    return True
