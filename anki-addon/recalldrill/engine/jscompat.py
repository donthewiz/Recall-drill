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
- ``String.prototype.length`` counts UTF-16 code units, Python's ``len()``
  counts code points. Use :func:`utf16_len`.
- ``arr.reduce((a, b) => a + b, 0)`` adds left to right with one rounding per
  step. Python 3.12+'s ``sum()`` of floats is compensated (more exact), so it
  can differ in the last bit. Use :func:`js_sum`. ``sum(`` is banned elsewhere
  in ``engine/`` by a test.
- ``Number.prototype.toFixed`` rounds the exact binary value with ties away
  from zero. Python's ``format(x, ".1f")`` rounds ties to even, so
  ``format(0.25, ".1f") == "0.2"`` where JS gives ``"0.3"``. Use
  :func:`js_to_fixed`.
- ``Date.prototype.toISOString`` has no Python twin (``datetime`` stops at year
  9999 and prints microseconds). Use :func:`js_iso_string`.
"""

from __future__ import annotations

import decimal
import math
import re
from collections.abc import Iterable, Iterator

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


def utf16_len(s: str) -> int:
    """JS ``s.length``: the number of UTF-16 code units."""
    return len(s.encode("utf-16-le", "surrogatepass")) // 2


def js_sum(values: Iterable[float]) -> float:
    """JS ``values.reduce((a, b) => a + b, 0)``: left to right, one rounding per step.

    Every value is a double, as in JS: ``js_sum([10**16, 1, -10**16])`` is 0.0
    where exact int arithmetic gives 1.
    """
    acc = 0.0
    for v in values:
        acc = acc + float(v)
    return acc


_TO_FIXED_CONTEXT = decimal.Context(prec=200, rounding=decimal.ROUND_HALF_UP)


def js_to_fixed(x: float, digits: int) -> str:
    """JS ``x.toFixed(digits)``.

    Rounds the exact binary value of ``x``. On an exact tie it picks the larger
    magnitude ("let n be an integer for which n / 10^f - x is as close to zero
    as possible; if there are two such n, pick the larger n", applied after the
    sign is taken off). ``(-0).toFixed(1)`` is ``"0.0"``, ``(-0.04).toFixed(1)``
    is ``"-0.0"``, and ``|x| >= 1e21`` falls back to ``String(x)``.
    """
    if not 0 <= digits <= 100:
        raise ValueError("toFixed() digits argument must be between 0 and 100")
    x = float(x)  # a JS number is a double, even when Python holds an exact int
    if math.isnan(x):
        return "NaN"
    sign = "-" if x < 0 else ""
    ax = abs(x)  # also turns -0.0 into 0.0, which has no sign in JS
    if ax >= 1e21:  # includes Infinity
        return sign + ("Infinity" if math.isinf(ax) else repr(float(ax)))
    exact = decimal.Decimal(ax)  # the exact binary value, every digit
    quantum = decimal.Decimal(1).scaleb(-digits)
    rounded = exact.quantize(quantum, context=_TO_FIXED_CONTEXT)
    return sign + format(rounded, "f")


_MS_PER_DAY = 86_400_000
_MAX_TIME_MS = 8.64e15


def js_iso_string(ms: float) -> str:
    """JS ``new Date(ms).toISOString()``: ``YYYY-MM-DDTHH:MM:SS.sssZ`` in UTC.

    ``ms`` is milliseconds since the epoch (``Date.now()``, ``getTime()``). Like
    TimeClip, a fraction is truncated toward zero. Years outside 0..9999 use the
    six-digit signed form (``+010000-01-01T...``, ``-000001-...``). A value JS
    rejects with "RangeError: Invalid time value" (not finite, or more than
    8.64e15 ms from the epoch) raises ``ValueError``.
    """
    if math.isnan(ms) or math.isinf(ms) or abs(ms) > _MAX_TIME_MS:
        raise ValueError("Invalid time value")
    t = int(ms)  # truncates toward zero, like ToIntegerOrInfinity
    days, ms_of_day = divmod(t, _MS_PER_DAY)
    year, month, day = _civil_from_days(days)
    hours, rest = divmod(ms_of_day, 3_600_000)
    minutes, rest = divmod(rest, 60_000)
    seconds, millis = divmod(rest, 1000)
    if 0 <= year <= 9999:
        year_text = f"{year:04d}"
    else:
        year_text = ("-" if year < 0 else "+") + f"{abs(year):06d}"
    return (
        f"{year_text}-{month:02d}-{day:02d}"
        f"T{hours:02d}:{minutes:02d}:{seconds:02d}.{millis:03d}Z"
    )


def _civil_from_days(z: int) -> tuple[int, int, int]:
    """Proleptic Gregorian (year, month, day) for a day count from 1970-01-01.

    Howard Hinnant's ``civil_from_days``; Python's floor division makes the
    negative-era branch unnecessary.
    """
    z += 719_468
    era = z // 146_097
    doe = z - era * 146_097
    yoe = (doe - doe // 1460 + doe // 36_524 - doe // 146_096) // 365
    doy = doe - (365 * yoe + yoe // 4 - yoe // 100)
    mp = (5 * doy + 2) // 153
    day = doy - (153 * mp + 2) // 5 + 1
    month = mp + 3 if mp < 10 else mp - 9
    year = yoe + era * 400 + (1 if month <= 2 else 0)
    return year, month, day
