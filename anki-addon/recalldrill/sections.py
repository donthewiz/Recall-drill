"""Progress (v0.3 sections, v0.3.1 layers; pure): which parts of a course are drilled.

docs/DECISIONS.md, "v0.3: whole-section drilling, exam dates, export" and
"v0.3.1: layers".

A **section** is a subdeck of the chosen deck (with its own subdecks). When any
card of the chosen deck has a ``Layer::N`` note tag (the anki-cards skill's
layers), the rows are **layers** instead ("Layer 1", "Layer 2", …, "No layer"),
with one "done/total" column per direct subdeck (chapter); otherwise the rows are
the subdecks, in the order their cards were made. The first row not yet done is
the **next** one. Each card falls in exactly one bucket, first match wins:

- ``drilled``: handed off by the add-on (a handoff line names it: a drilled
  card, a sibling or a holdout card), whatever its state now;
- ``released``: its note is tagged ``rd::undrilled`` (sent to Anki undrilled);
- ``introduced``: Anki has already introduced it (not new);
- ``cant_drill`` (v0.3.1): new, and the drill can never take it (image occlusion,
  marked ineligible, unmapped, empty answer: ``select.content_check``). It never
  blocks "done" and is left out of the chapter columns' totals;
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
from .layers import layer_of
from .waiting import TAG_UNDRILLED, WAITING_TAG

Bucket = Literal["drilled", "released", "introduced", "cant_drill", "held", "open"]
BUCKETS: tuple[Bucket, ...] = ("drilled", "released", "introduced", "cant_drill", "held", "open")


@dataclass(frozen=True)
class CardFacts:
    """What section progress needs to know about one card."""

    cid: int
    is_new: bool
    suspended: bool
    tags: tuple[str, ...]
    """Its note's tags."""
    undrillable: bool = False
    """The drill can never take it (v0.3.1); only read for new, undrilled cards."""
    chapter: int = -1
    """Index of its direct subdeck in the progress' chapters; -1: the chosen deck itself."""


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
    if facts.undrillable:
        return "cant_drill"
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
    cant_drill: int = 0
    """New cards the drill can't take (v0.3.1); not in ``new``, never in ``to_go``."""
    layer: int | None = None
    """The row's layer number (a layer row), else None."""
    chapters: tuple[tuple[int, int], ...] = ()
    """Per chapter: (done, total) of the drillable cards; done = drilled + released +
    introduced (layer rows only)."""

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
    layer: int | None = None,
    chapter_count: int = 0,
) -> SectionRow:
    facts = list(cards)
    buckets = [bucket(f, drilled) for f in facts]
    counts = Counter(buckets)
    chapters = [[0, 0] for _ in range(chapter_count)]
    for f, b in zip(facts, buckets, strict=True):
        if b != "cant_drill" and 0 <= f.chapter < chapter_count:
            chapters[f.chapter][1] += 1
            chapters[f.chapter][0] += b in ("drilled", "released", "introduced")
    return SectionRow(
        did=did,
        name=name,
        label=label,
        cards=len(facts),
        new=sum(1 for f, b in zip(facts, buckets, strict=True) if f.is_new and b != "cant_drill"),
        introduced=sum(1 for f in facts if not f.is_new),
        drilled=counts["drilled"],
        released=counts["released"],
        held=counts["held"],
        open=counts["open"],
        cant_drill=counts["cant_drill"],
        layer=layer,
        chapters=tuple((d, t) for d, t in chapters),
    )


@dataclass(frozen=True)
class Chapter:
    """A direct subdeck of the chosen deck."""

    did: int
    name: str
    label: str


@dataclass(frozen=True)
class Progress:
    """The table: layer rows (``by_layer``) or subdeck rows, and where to drill next."""

    did: int
    """The chosen deck."""
    by_layer: bool
    chapters: tuple[Chapter, ...]
    """The direct subdecks, in the order their cards were made."""
    rows: tuple[SectionRow, ...]

    @property
    def next_index(self) -> int | None:
        """The first row (in table order) that isn't done."""
        return next((i for i, r in enumerate(self.rows) if not r.done), None)

    @property
    def next_row(self) -> SectionRow | None:
        i = self.next_index
        return self.rows[i] if i is not None else None

    @property
    def next_target(self) -> int | None:
        """The deck "Drill next" opens (Deck order): the chosen deck when the rows are
        layers (Deck order starts at the lowest unfinished layer), else the next
        subdeck's."""
        row = self.next_row
        if row is None:
            return None
        return self.did if self.by_layer else row.did


NO_LAYER_LABEL = "No layer"
SELF_LABEL = "(cards in this deck itself)"


def build_progress(
    did: int,
    root: str,
    chapters: Sequence[Chapter],
    cards: Iterable[CardFacts],
    drilled: frozenset[int] | set[int],
) -> Progress:
    """Pure: ``cards`` are every card of the chosen deck; ``CardFacts.chapter``
    indexes ``chapters`` (already in the order their cards were made)."""
    facts = list(cards)
    layers = sorted({n for f in facts if (n := layer_of(f.tags)) is not None})
    if layers:
        layer_rows = [
            section_row(
                did,
                root,
                f"Layer {n}",
                [f for f in facts if layer_of(f.tags) == n],
                drilled,
                layer=n,
                chapter_count=len(chapters),
            )
            for n in layers
        ]
        bare = [f for f in facts if layer_of(f.tags) is None]
        if bare:
            layer_rows.append(
                section_row(did, root, NO_LAYER_LABEL, bare, drilled, chapter_count=len(chapters))
            )
        return Progress(did, True, tuple(chapters), tuple(layer_rows))
    rows: list[SectionRow] = []
    own = [f for f in facts if f.chapter < 0]
    if own:
        rows.append(section_row(did, root, SELF_LABEL, own, drilled))
    for i, ch in enumerate(chapters):
        rows.append(
            section_row(ch.did, ch.name, ch.label, [f for f in facts if f.chapter == i], drilled)
        )
    return Progress(did, False, tuple(chapters), tuple(rows))


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


NEXT_TEXT = "Next"
CANT_DRILL_COLUMN = "Can't drill"
NEXT_COLUMN = "Next"


def progress_columns(p: Progress) -> list[str]:
    """The table's header: the v0.3 columns, "Can't drill", one column per chapter
    (layer rows only), and "Next"."""
    first = "Layer" if p.by_layer else COLUMNS[0]
    chapters = [c.label for c in p.chapters] if p.by_layer else []
    return [first, *COLUMNS[1:], CANT_DRILL_COLUMN, *chapters, NEXT_COLUMN]


def progress_cells(p: Progress, index: int) -> list[str]:
    r = p.rows[index]
    chapter_cells = [f"{d}/{t}" for d, t in r.chapters] if p.by_layer else []
    return [
        *cells(r),
        str(r.cant_drill),
        *chapter_cells,
        NEXT_TEXT if p.next_index == index else "",
    ]


def render_progress(p: Progress) -> str:
    """The progress table as plain text (reports and tests)."""
    table = [progress_columns(p), *(progress_cells(p, i) for i in range(len(p.rows)))]
    widths = [max(len(row[i]) for row in table) for i in range(len(table[0]))]
    return "\n".join(
        "  ".join(c.ljust(w) for c, w in zip(row, widths, strict=True)).rstrip() for row in table
    )
