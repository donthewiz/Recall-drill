"""Section progress (v0.3, pure): which parts of a course are drilled.

docs/DECISIONS.md, "v0.3: whole-section drilling, exam dates, export".

A **section** is a subdeck of the chosen deck (with its own subdecks). Each of
its cards falls in exactly one bucket, first match wins:

- ``drilled``: handed off by the add-on (a handoff line names it: a drilled
  card, a sibling or a holdout card), whatever its state now;
- ``released``: its note is tagged ``rd::undrilled`` (sent to Anki undrilled);
- ``introduced``: Anki has already introduced it (not new);
- ``held``: new and suspended, its note tagged ``rd::drill`` or ``rd::held``
  (waiting: the waiting-cards search);
- ``open``: any other new card: not yet in Anki and not held (unsuspended,
  never drilled; a new card suspended by hand is here too).

A row is **done** when no new card is ``held`` or ``open``: every new card has
been drilled or released. A row without a single new card is "done (no new
cards)". ``% drilled`` is the drilled share of the section's cards.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from .holdback import TAG_HELD
from .waiting import TAG_UNDRILLED, WAITING_TAG

Bucket = Literal["drilled", "released", "introduced", "held", "open"]
BUCKETS: tuple[Bucket, ...] = ("drilled", "released", "introduced", "held", "open")


@dataclass(frozen=True)
class CardFacts:
    """What section progress needs to know about one card."""

    cid: int
    is_new: bool
    suspended: bool
    tags: tuple[str, ...]
    """Its note's tags."""


def _has(tags: Iterable[str], tag: str) -> bool:
    """A tag or one of its children (``tag:rd::drill`` matches ``rd::drill::A``)."""
    want = tag.casefold()
    return any(t.casefold() == want or t.casefold().startswith(want + "::") for t in tags)


def bucket(facts: CardFacts, drilled: frozenset[int] | set[int]) -> Bucket:
    if facts.cid in drilled:
        return "drilled"
    if _has(facts.tags, TAG_UNDRILLED):
        return "released"
    if not facts.is_new:
        return "introduced"
    if facts.suspended and (_has(facts.tags, WAITING_TAG) or _has(facts.tags, TAG_HELD)):
        return "held"
    return "open"


@dataclass(frozen=True)
class SectionRow:
    did: int
    name: str
    """The section's full deck name."""
    label: str
    """What the table shows (the part of the name below the chosen deck)."""
    cards: int
    new: int
    introduced: int
    drilled: int
    released: int
    held: int
    open: int

    @property
    def pct_drilled(self) -> int:
        return round(100 * self.drilled / self.cards) if self.cards else 0

    @property
    def to_go(self) -> int:
        """New cards that are neither drilled nor released."""
        return self.held + self.open

    @property
    def done(self) -> bool:
        return self.to_go == 0

    @property
    def status(self) -> str:
        if self.new == 0:
            return "done (no new cards)"
        return "done" if self.done else f"{self.to_go} to go"


def section_row(
    did: int,
    name: str,
    label: str,
    cards: Iterable[CardFacts],
    drilled: frozenset[int] | set[int],
) -> SectionRow:
    facts = list(cards)
    counts = Counter(bucket(f, drilled) for f in facts)
    return SectionRow(
        did=did,
        name=name,
        label=label,
        cards=len(facts),
        new=sum(1 for f in facts if f.is_new),
        introduced=sum(1 for f in facts if not f.is_new),
        drilled=counts["drilled"],
        released=counts["released"],
        held=counts["held"],
        open=counts["open"],
    )


COLUMNS = (
    "Section",
    "Cards",
    "Drilled",
    "Released undrilled",
    "Held / waiting",
    "Not in Anki, not held",
    "% drilled",
    "Status",
)


def cells(r: SectionRow) -> list[str]:
    return [
        r.label,
        str(r.cards),
        str(r.drilled),
        str(r.released),
        str(r.held),
        str(r.open),
        f"{r.pct_drilled}%",
        r.status,
    ]


def render_text(rows: Sequence[SectionRow]) -> str:
    """The table as plain text (reports and tests)."""
    table = [list(COLUMNS), *(cells(r) for r in rows)]
    widths = [max(len(row[i]) for row in table) for i in range(len(COLUMNS))]
    return "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in table
    )
