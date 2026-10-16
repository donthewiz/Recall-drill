"""The one-line summaries of the setup panel's folds (v0.5.1; docs/DECISIONS.md, "v0.5.1
streamline"). Pure: the panel passes in what its controls show right now."""

from __future__ import annotations

import re
from collections.abc import Collection
from datetime import date

from .anki_io.cards import CARD_CLASSES
from .pacing import WEEKDAY_NAMES, PacingView, short_date

SEP = " · "

_CLASS_NAMES = {c: c.replace("_", " ") for c in CARD_CLASSES}
_FIRST: tuple[str, ...] = ("new", "suspended_new")
"""Named first: "new + suspended new" is what Drill next ticks."""
_LAYER = re.compile(r"Layer::(\d+)", re.IGNORECASE)


def tag_text(tag: str) -> str:
    """ "Layer::3" reads "Layer 3"; any other tag as typed."""
    m = _LAYER.fullmatch(tag.strip())
    return f"Layer {m.group(1)}" if m else tag.strip()


def classes_text(enabled: Collection[str]) -> str:
    """The ticked card types in the panel's order: "new + suspended new"."""
    order = sorted(
        CARD_CLASSES, key=lambda c: (c not in _FIRST, _FIRST.index(c) if c in _FIRST else 0)
    )
    ticked = [_CLASS_NAMES[c] for c in order if c in enabled]
    return " + ".join(ticked) if ticked else "no card types"


def cards_summary(
    tag: str, enabled: Collection[str], order_label: str, max_cards: int, math_cards: int = 0
) -> str:
    """ "Layer 3 · new + suspended new · Deck order" ("all cards" without a tag); with math
    cards in the pick (v0.6) a last part counts them: "... · 12 math"."""
    parts = [tag_text(tag) if tag.strip() else "all cards", classes_text(enabled), order_label]
    if max_cards:
        parts.append(f"max {max_cards:,}")
    if math_cards:
        parts.append(f"{math_cards:,} math")
    return SEP.join(parts)


def math_gap_line(gaps: int) -> str:
    """The amber line for ``rd::math`` cards that have no usable ``MathAnswer`` (v0.6): they
    are drilled as normal cards. "" when there are none."""
    if not gaps:
        return ""
    if gaps == 1:
        return (
            "1 card tagged rd::math has no usable MathAnswer field, so it is drilled as a "
            "normal card."
        )
    return (
        f"{gaps:,} cards tagged rd::math have no usable MathAnswer field, so they are drilled "
        "as normal cards."
    )


def settings_summary(batch_size: int, encode_reps: int, hold_back: bool | None) -> str:
    """ "5 per batch · 2 blind typings · hold back on" (no hold back part for a search)."""
    parts = [
        f"{batch_size} per batch" if batch_size else "whole deck in one batch",
        f"{encode_reps} blind {'typing' if encode_reps == 1 else 'typings'}",
    ]
    if hold_back is not None:
        parts.append("hold back on" if hold_back else "hold back off")
    return SEP.join(parts)


def days_text(weekdays: Collection[int]) -> str:
    """ "every day" when all seven are ticked, else "Mon, Wed, Fri"."""
    days = sorted(set(weekdays))
    if len(days) == len(WEEKDAY_NAMES):
        return "every day"
    return ", ".join(WEEKDAY_NAMES[i] for i in days) if days else "no drill days"


def pacing_summary(
    on: bool,
    last_drill_day: date | None,
    view: PacingView | None,
    weekdays: Collection[int],
) -> str:
    """ "finish Tue Oct 20 · 111 today · every day", or "off"."""
    if not on:
        return "off"
    parts: list[str] = []
    if last_drill_day is not None:
        parts.append(f"finish {short_date(last_drill_day)}")
    if view is not None and view.pace.status == "ok":
        p = view.pace
        parts.append(f"{p.today_n} today" if p.drills_today else f"{p.per_day} a day")
    parts.append(days_text(weekdays))
    return SEP.join(parts)


def scope_summary(is_deck: bool, label: str, tag: str) -> str:
    """ "Lab 2 · whole deck", "Lab 2 · tag Layer 3", "search: tag:X"."""
    if is_deck:
        return f"{label}{SEP}{'tag ' + tag_text(tag) if tag.strip() else 'whole deck'}"
    return f"search: {label}" + (f"{SEP}tag {tag_text(tag)}" if tag.strip() else "")
