"""The success metric, defined once: next-day Again on Anki's own ratings (pure).

docs/DECISIONS.md, "Measurement and holdout (Phase 5)".

- **Anki day** of a time: the local date after subtracting the rollover hour
  (:func:`anki_day`). Everything here uses that one function.
- **Counted rating**: a revlog row with ``ease >= 1`` and ``type`` 0, 1 or 2
  (learn, review, relearn). Filtered-deck / cram (3), manual (4) and
  rescheduled (5) rows, and ``ease 0`` rows, never count.
- **Drilled card**: ``t0`` is its handoff. The outcome is its first counted
  rating on an Anki day after ``day(t0)``.
- **Holdout and baseline card**: ``t0`` is its first counted rating (its
  introduction). The outcome is its first counted rating on a later Anki day.
- **Again**: ``ease == 1``. ``elapsed = day(rating) - day(t0)``, in days.
- The primary analysis keeps ``elapsed`` 1 or 2 (:data:`PRIMARY_ELAPSED`).
  Longer gaps (a card that spilled over the new-card limit, say) are
  ``late``: counted and reported, never in the rate.
- A card with no outcome yet is ``pending``: counted, never a success.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta, tzinfo
from typing import Literal

COUNTED_TYPES = frozenset({0, 1, 2})
"""Revlog types that count: learn, review, relearn."""
AGAIN = 1
PRIMARY_ELAPSED = frozenset({1, 2})
Z95 = 1.959963984540054


@dataclass(frozen=True)
class RevlogRow:
    """One ``revlog`` row: ``id`` is the rating time in epoch milliseconds."""

    id: int
    cid: int
    ease: int
    type: int
    ivl: int = 0
    time: int = 0


def is_counted(row: RevlogRow) -> bool:
    return row.ease >= 1 and row.type in COUNTED_TYPES


def anki_day(ms: float, rollover_hour: int, tz: tzinfo | None = None) -> date:
    """The Anki day of a time (epoch ms): the local date, rollover hour subtracted.
    ``tz`` None is the machine's local time zone (Anki's)."""
    local = datetime.fromtimestamp(ms / 1000, tz)
    return (local - timedelta(hours=rollover_hour)).date()


OutcomeStatus = Literal["outcome", "late", "pending"]


@dataclass(frozen=True)
class Outcome:
    status: OutcomeStatus
    """``outcome``: in the primary analysis. ``late``: a rating more than
    2 days after ``t0``. ``pending``: no rating yet (or, for a holdout card, no
    introduction yet)."""
    t0_ms: int | None
    rating_ms: int | None = None
    elapsed: int | None = None
    ease: int | None = None

    @property
    def again(self) -> bool | None:
        return None if self.ease is None else self.ease == AGAIN


def counted(rows: Iterable[RevlogRow]) -> list[RevlogRow]:
    """The counted ratings, oldest first."""
    return sorted((r for r in rows if is_counted(r)), key=lambda r: r.id)


def _first_after(
    rows: Sequence[RevlogRow], t0_ms: int, rollover_hour: int, tz: tzinfo | None
) -> Outcome:
    day0 = anki_day(t0_ms, rollover_hour, tz)
    for r in rows:
        if r.id < t0_ms:
            continue
        d = anki_day(r.id, rollover_hour, tz)
        if d <= day0:
            continue
        elapsed = (d - day0).days
        status: OutcomeStatus = "outcome" if elapsed in PRIMARY_ELAPSED else "late"
        return Outcome(status, t0_ms, r.id, elapsed, r.ease)
    return Outcome("pending", t0_ms)


def drilled_outcome(
    rows: Iterable[RevlogRow], handoff_ms: int, rollover_hour: int, tz: tzinfo | None = None
) -> Outcome:
    """A drilled card: the first counted rating on an Anki day after the handoff's."""
    return _first_after(counted(rows), handoff_ms, rollover_hour, tz)


def introduction_ms(rows: Iterable[RevlogRow]) -> int | None:
    """The card's first counted rating (its introduction), or None."""
    c = counted(rows)
    return c[0].id if c else None


def introduced_outcome(
    rows: Iterable[RevlogRow], rollover_hour: int, tz: tzinfo | None = None
) -> Outcome:
    """A holdout or baseline card: ``t0`` = its introduction, the outcome its
    first counted rating on a later Anki day."""
    c = counted(rows)
    if not c:
        return Outcome("pending", None)
    return _first_after(c, c[0].id, rollover_hour, tz)


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for ``k`` successes in ``n`` trials (95% by default)."""
    if n <= 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


def overlaps(a: tuple[float, float], b: tuple[float, float]) -> bool:
    return a[0] <= b[1] and b[0] <= a[1]


def iso_ms(text: str) -> int | None:
    """An ISO 8601 time (``js_iso_string``'s ``…Z``, or with an offset) as epoch ms."""
    try:
        dt = datetime.fromisoformat(text)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        return None
    return int(dt.timestamp() * 1000)
