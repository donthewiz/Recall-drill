"""Is a saved session still true to the collection? (``check_resume``)

Before a save is resumed, its cards are checked against what Anki has now:

- ``missing``: cards that no longer exist;
- ``changed``: cards whose answer (as ``build`` reads it today, under the current
  mappings) hashes differently from the one the session was built with.

If either is non-empty, the panel offers "Start fresh" (recommended) or "Resume
with the saved text". Engine state is never patched to drop items; missing
cards are skipped at handoff instead.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from anki.cards import CardId
from anki.collection import Collection
from anki.errors import NotFoundError

from ..sessions import saved_sources
from .build import answer_hash
from .notetypes import MappingTable, answer_text


@dataclass(frozen=True)
class ResumeCheck:
    missing: tuple[int, ...]
    """Card ids no longer in the collection."""
    changed: tuple[int, ...]
    """Card ids whose answer changed since the session was built."""

    @property
    def ok(self) -> bool:
        return not self.missing and not self.changed


def check_resume(
    col: Collection, saved: Mapping[str, Any], mappings: MappingTable | None = None
) -> ResumeCheck:
    """``mappings``: the table ``build`` would use now (overrides from
    ``mappings.json``); defaults only if None."""
    table = mappings if mappings is not None else MappingTable(col)
    missing: list[int] = []
    changed: list[int] = []
    for src in saved_sources(saved):
        try:
            card = col.get_card(CardId(src.cid))
        except NotFoundError:
            missing.append(src.cid)
            continue
        note = card.note()
        mapping = table.for_card(note.mid, card.ord)
        if answer_hash(answer_text(col, note, mapping, card.ord)) != src.answer_hash:
            changed.append(src.cid)
    return ResumeCheck(tuple(missing), tuple(changed))
