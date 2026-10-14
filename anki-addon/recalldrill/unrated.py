"""Handed-off cards that Anki hasn't rated yet, and the warning about them (v0.3, pure).

docs/DECISIONS.md, "v0.3: whole-section drilling, exam dates, export".

The measurement (``measure.py``) counts a drilled or holdout card's first
counted rating on Anki day ``day(t0) + 1`` or ``+ 2`` (``PRIMARY_ELAPSED``);
later is ``late`` and out of the comparison. So a handed-off card with no
counted rating yet has until the **end of Anki day** ``day(t0) + 2`` (the
rollover hour on the calendar day after it) to stay in the comparison. With
several handoffs pending, the warning names the earliest deadline.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta, tzinfo

from .measure import PRIMARY_ELAPSED, anki_day
from .pacing import short_date

WINDOW_LAST_DAY = max(PRIMARY_ELAPSED)
"""The last Anki day after the handoff that is still in the primary analysis."""


@dataclass(frozen=True)
class PendingCard:
    """A handed-off drilled or holdout card with no counted rating since."""

    cid: int
    t0_ms: int
    """Its handoff time."""
    filtered: str | None = None
    """The filtered deck it sits in now, if any."""


@dataclass(frozen=True)
class UnratedWarning:
    count: int
    last_day: date
    """The Anki day the earliest window ends with: ``day(t0) + 2``."""
    ends: date
    """The calendar day that Anki day ends on, at the rollover hour."""
    rollover: int
    in_filtered: tuple[tuple[str, int], ...] = ()
    """(filtered deck name, cards in it), most cards first."""

    def line(self) -> str:
        return warning_line(self)


def window_last_day(t0_ms: int, rollover_hour: int, tz: tzinfo | None = None) -> date:
    """The last Anki day on which a rating of this card still counts as an outcome."""
    return anki_day(t0_ms, rollover_hour, tz) + timedelta(days=WINDOW_LAST_DAY)


def unrated_warning(
    cards: Iterable[PendingCard], now_ms: float, rollover_hour: int, tz: tzinfo | None = None
) -> UnratedWarning | None:
    """The warning for the cards whose window is still open, or None (no such
    card, or every deadline has passed)."""
    today = anki_day(now_ms, rollover_hour, tz)
    open_cards = [c for c in cards if window_last_day(c.t0_ms, rollover_hour, tz) >= today]
    if not open_cards:
        return None
    last = min(window_last_day(c.t0_ms, rollover_hour, tz) for c in open_cards)
    filtered = Counter(c.filtered for c in open_cards if c.filtered)
    return UnratedWarning(
        count=len(open_cards),
        last_day=last,
        ends=last + timedelta(days=1),
        rollover=rollover_hour,
        in_filtered=tuple(sorted(filtered.items(), key=lambda kv: (-kv[1], kv[0]))),
    )


def hour_text(hour: int) -> str:
    """ "4 AM", "12 PM"."""
    return f"{hour % 12 or 12} {'AM' if hour < 12 else 'PM'}"


def warning_line(w: UnratedWarning) -> str:
    one = w.count == 1
    text = (
        f"{'1 drilled card is' if one else f'{w.count} drilled cards are'} waiting for "
        f"{'its' if one else 'their'} first Anki rating. "
        f"Rate {'it' if one else 'them'} by {short_date(w.ends)} (before {hour_text(w.rollover)}) "
        f"to keep {'it' if one else 'them'} in the comparison."
    )
    if len(w.in_filtered) == 1:
        name, n = w.in_filtered[0]
        text += f" ({n} {'is' if n == 1 else 'are'} in the filtered deck '{name}')"
    elif w.in_filtered:
        parts = ", ".join(f"'{name}' {n}" for name, n in w.in_filtered)
        text += f" (in filtered decks: {parts})"
    return text
