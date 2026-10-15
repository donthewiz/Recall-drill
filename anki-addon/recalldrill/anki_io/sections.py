"""Read section progress (v0.3). Read only.

``sections.py`` (pure) has the rules. The chosen deck's direct subdecks (chapters) are
sorted by their earliest note id, the order the cards were made (v0.3.1; v0.3.0 used
deck-tree order); a section's cards are everything whose home deck is the subdeck or
one of its own subdecks. Cards sitting directly in the chosen deck (not in a
subdeck) get a row of their own, listed first. New cards the drill can never take are
counted apart (``content_check``).
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator

from anki.collection import Collection, SearchNode
from anki.decks import DeckId, DeckTreeNode

from ..history_store import handed_off_by_addon
from ..sections import SELF_LABEL as SELF_LABEL
from ..sections import CardFacts, Chapter, Progress, SectionRow, build_progress
from ..storage import Storage
from ..waiting import TAG_UNDRILLED
from .cards import NoteCache, read_snapshots
from .notetypes import MappingTable, load_overrides
from .select import content_check

BATCH = 500
"""Card ids per ``IN (…)`` list."""


def _find(node: DeckTreeNode, did: int) -> DeckTreeNode | None:
    if node.deck_id == did:
        return node
    for child in node.children:
        hit = _find(child, did)
        if hit is not None:
            return hit
    return None


def children(col: Collection, did: int) -> list[tuple[int, str]]:
    """(deck id, full name) of the deck's direct subdecks, in deck-tree order."""
    root = _find(col.decks.deck_tree(), did)
    if root is None:
        return []
    return [(int(c.deck_id), col.decks.name(DeckId(int(c.deck_id)))) for c in root.children]


def _batches(ids: list[int]) -> Iterator[list[int]]:
    for i in range(0, len(ids), BATCH):
        yield ids[i : i + BATCH]


def _within(home: str, section: str) -> bool:
    return home == section or home.startswith(section + "::")


def read_progress(col: Collection, storage: Storage, did: int) -> Progress:
    """The progress table for ``did``: layer rows when any card carries a ``Layer::N``
    tag, else its subdecks' rows (its own cards first, if any). The chapters, and the
    subdeck rows, come in the order their cards were made (earliest note id)."""
    root = col.decks.name(DeckId(did))
    cids = [int(c) for c in col.find_cards(col.build_search_string(SearchNode(deck=root)))]
    db = col.db
    assert db is not None, "the collection is closed"
    kids = children(col, did)
    names: dict[int, str] = {}
    cards: list[tuple[int, int, bool, bool, tuple[str, ...], int]] = []
    for batch in _batches(cids):
        rows = db.all(
            "select c.id, c.nid, c.type, c.queue, c.did, c.odid, n.tags from cards c "
            f"join notes n on n.id = c.nid where c.id in ({','.join(map(str, batch))})"
        )
        for cid, nid, type_, queue, cdid, odid, tags in rows:
            home = int(odid) or int(cdid)
            if home not in names:
                names[home] = col.decks.name(DeckId(home))
            chapter = next((i for i, (_d, n) in enumerate(kids) if _within(names[home], n)), -1)
            cards.append(
                (
                    int(cid),
                    int(nid),
                    int(type_) == 0,
                    int(queue) == -1,
                    tuple(str(tags).split()),
                    chapter,
                )
            )
    earliest: dict[int, int] = {}
    for _cid, nid, *_rest, chapter in cards:
        earliest[chapter] = min(nid, earliest.get(chapter, nid))
    order = sorted(range(len(kids)), key=lambda i: (earliest.get(i, 1 << 62), kids[i][1]))
    position = {old: new for new, old in enumerate(order)}
    chapters = tuple(Chapter(kids[i][0], kids[i][1], kids[i][1][len(root) + 2 :]) for i in order)
    drilled = handed_off_by_addon(storage)
    undrillable = _undrillable(
        col,
        storage,
        [c[0] for c in cards if c[2] and c[0] not in drilled and not _released(c[4])],
    )
    facts = [
        CardFacts(cid, is_new, suspended, tags, cid in undrillable, position.get(chapter, -1))
        for cid, _nid, is_new, suspended, tags, chapter in cards
    ]
    return build_progress(did, root, chapters, facts, drilled)


def _released(tags: tuple[str, ...]) -> bool:
    return any(t.casefold() == TAG_UNDRILLED for t in tags)


def _undrillable(col: Collection, storage: Storage, new_cids: list[int]) -> set[int]:
    """The new, undrilled cards the drill can never take (``select.content_check``)."""
    if not new_cids:
        return set()
    notes = NoteCache(col)
    table = MappingTable(col, load_overrides(storage))
    bad: set[int] = set()
    for snap in read_snapshots(col, new_cids, notes):
        reason, _answer = content_check(col, snap, table.for_card(snap.ntid, snap.ord), notes)
        if reason is not None:
            bad.add(snap.cid)
    return bad


def undrillable_new(
    col: Collection,
    storage: Storage,
    cards: Iterable[tuple[int, bool, tuple[str, ...]]],
    drilled: frozenset[int] | set[int],
) -> set[int]:
    """The cards the sections table counts as "can't drill", for ``(card id, is new, note
    tags)`` rows: new, not handed off, not released, and refused by ``content_check``.
    The exam tracker reuses this, so it and the table can't disagree."""
    return _undrillable(
        col,
        storage,
        [
            cid
            for cid, is_new, tags in cards
            if is_new and cid not in drilled and not _released(tags)
        ],
    )


def read_sections(col: Collection, storage: Storage, did: int) -> list[SectionRow]:
    """The progress rows (see :func:`read_progress`)."""
    return list(read_progress(col, storage, did).rows)
