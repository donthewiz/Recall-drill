"""Read the handed-off cards that Anki hasn't rated yet (v0.3). Read only.

``unrated.py`` (pure) has the rules. The cards are the measurement's drilled
and holdout cards (``history_store.measured_handoffs``) with no counted rating
since their handoff (``revlog.waiting_for_anki``, the same ``measure.is_counted``
rule), still in the collection and not suspended (an undone handoff re-suspends
its cards). Read in the background op that reads the waiting cards.
"""

from __future__ import annotations

import time

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.decks import DeckId
from anki.errors import NotFoundError

from ..history_store import measured_handoffs
from ..storage import Storage
from ..unrated import PendingCard, UnratedWarning, unrated_warning
from .revlog import waiting_for_anki


def pending_cards(
    col: Collection, storage: Storage, deck_id: int | None = None
) -> list[PendingCard]:
    """The handed-off drilled and holdout cards still waiting for their first
    rating (in ``deck_id`` and its subdecks, or everywhere), with the filtered
    deck each sits in."""
    handed = measured_handoffs(storage)
    waiting = waiting_for_anki(col, handed)
    scope = col.decks.name(DeckId(deck_id)) if deck_id is not None else None
    out: list[PendingCard] = []
    for cid in sorted(waiting):
        try:
            card = col.get_card(CardId(cid))
        except NotFoundError:
            continue
        if card.queue == QUEUE_TYPE_SUSPENDED:
            continue
        home = int(card.odid or card.did)
        if scope is not None:
            name = col.decks.name(DeckId(home))
            if name != scope and not name.startswith(scope + "::"):
                continue
        filtered = col.decks.name(DeckId(int(card.did))) if card.odid else None
        out.append(PendingCard(cid, handed[cid], filtered))
    return out


def read_unrated(
    col: Collection,
    storage: Storage,
    deck_id: int | None = None,
    now_ms: float | None = None,
) -> UnratedWarning | None:
    rollover = col.get_preferences().scheduling.rollover
    now = time.time() * 1000 if now_ms is None else now_ms
    return unrated_warning(pending_cards(col, storage, deck_id), now, rollover)
