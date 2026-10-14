"""Read section progress (v0.3). Read only.

``sections.py`` (pure) has the rules. The chosen deck's subdecks come in deck-tree
order (``col.decks.deck_tree()``); a section's cards are everything whose home
deck is the subdeck or one of its own subdecks. Cards sitting directly in the
chosen deck (not in a subdeck) get a row of their own, listed first.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterator

from anki.collection import Collection, SearchNode
from anki.decks import DeckId, DeckTreeNode

from ..history_store import handed_off_by_addon
from ..sections import CardFacts, SectionRow, section_row
from ..storage import Storage

SELF_LABEL = "(cards in this deck itself)"
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


def read_sections(col: Collection, storage: Storage, did: int) -> list[SectionRow]:
    """The progress rows for the subdecks of ``did`` (its own cards first, if any)."""
    root = col.decks.name(DeckId(did))
    cids = [int(c) for c in col.find_cards(col.build_search_string(SearchNode(deck=root)))]
    db = col.db
    assert db is not None, "the collection is closed"
    by_home: dict[str, list[CardFacts]] = defaultdict(list)
    names: dict[int, str] = {}
    for batch in _batches(cids):
        rows = db.all(
            "select c.id, c.type, c.queue, c.did, c.odid, n.tags from cards c "
            f"join notes n on n.id = c.nid where c.id in ({','.join(map(str, batch))})"
        )
        for cid, type_, queue, cdid, odid, tags in rows:
            home = int(odid) or int(cdid)
            if home not in names:
                names[home] = col.decks.name(DeckId(home))
            by_home[names[home]].append(
                CardFacts(int(cid), int(type_) == 0, int(queue) == -1, tuple(str(tags).split()))
            )
    drilled = handed_off_by_addon(storage)
    out: list[SectionRow] = []
    own = by_home.get(root, [])
    if own:
        out.append(section_row(did, root, SELF_LABEL, own, drilled))
    for cdid, name in children(col, did):
        facts = [f for home, fs in by_home.items() if _within(home, name) for f in fs]
        out.append(section_row(cdid, name, name[len(root) + 2 :], facts, drilled))
    return out
