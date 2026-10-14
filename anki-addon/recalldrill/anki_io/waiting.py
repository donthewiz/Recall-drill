"""Read the drill cards left waiting (2026-10-12). Read only.

``waiting.py`` (pure) has the rules. Here: the exact search (``(tag:rd::drill OR
tag:rd::held) is:new is:suspended``, built with ``SearchNode(tag=…)`` so nothing
else in ``rd::`` matches), the cards waiting for Anki after a handoff or release left
out, each card's home deck and added day, and each deck's pacing (its own
target, else its nearest parent's).
"""

from __future__ import annotations

import time
from collections.abc import Sequence

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, SearchNode
from anki.consts import QUEUE_TYPE_SUSPENDED
from anki.decks import DeckId

from .. import pacing
from ..addon_config import AddonConfig
from ..history_store import handed_off_at
from ..measure import anki_day
from ..pacing import PacingSettings
from ..storage import Storage
from ..waiting import HELD_TAG, WAITING_TAG, WaitingCard, WaitingRow, waiting_rows
from .revlog import waiting_for_anki


def waiting_search(col: Collection, deck_id: int | None = None) -> str:
    """``(tag:rd::drill OR tag:rd::held) is:new is:suspended`` (exact tags),
    optionally in one deck (with its subdecks)."""
    group = SearchNode.Group
    either = SearchNode(
        group=group(
            joiner=group.OR, nodes=[SearchNode(tag=WAITING_TAG), SearchNode(tag=HELD_TAG)]
        )
    )
    terms: list[str | SearchNode] = [either, "is:new", "is:suspended"]
    if deck_id is not None:
        terms.insert(0, SearchNode(deck=col.decks.name(DeckId(deck_id))))
    return col.build_search_string(*terms)


def read_waiting_cards(
    col: Collection, storage: Storage, deck_id: int | None = None
) -> list[WaitingCard]:
    """The waiting cards (in ``deck_id`` and its subdecks, or everywhere)."""
    cids = [int(c) for c in col.find_cards(waiting_search(col, deck_id))]
    handed = handed_off_at(storage)
    waiting_for = waiting_for_anki(col, {c: handed[c] for c in cids if c in handed})
    rollover = col.get_preferences().scheduling.rollover
    out: list[WaitingCard] = []
    for cid in cids:
        card = col.get_card(CardId(cid))
        # Waiting for Anki after a handoff or release: only while not suspended,
        # as in selection (an undone handoff re-suspends its cards).
        if cid in waiting_for and card.queue != QUEUE_TYPE_SUSPENDED:
            continue
        out.append(
            WaitingCard(
                cid=cid,
                nid=int(card.nid),
                did=int(card.odid or card.did),
                added=anki_day(int(card.nid), rollover),
            )
        )
    return out


def deck_pacing(
    col: Collection, storage: Storage, did: int, cache: dict[int, PacingSettings | None]
) -> PacingSettings | None:
    """The pacing that applies to a deck: its own with a target date, else the
    nearest parent's with one, else None."""
    if did in cache:
        return cache[did]
    found: PacingSettings | None = None
    for deck in [col.decks.get(DeckId(did)), *reversed(col.decks.parents(DeckId(did)))]:
        if deck is None:
            continue
        s = pacing.load(storage, int(deck["id"]))
        if s.target_date is not None:
            found = s
            break
    cache[did] = found
    return found


def read_waiting(
    col: Collection,
    storage: Storage,
    cfg: AddonConfig,
    deck_id: int | None = None,
    now_ms: float | None = None,
) -> list[WaitingRow]:
    """The waiting cards by deck, with their stale counts."""
    rollover = col.get_preferences().scheduling.rollover
    today = anki_day(time.time() * 1000 if now_ms is None else now_ms, rollover)
    cache: dict[int, PacingSettings | None] = {}
    return waiting_rows(
        read_waiting_cards(col, storage, deck_id),
        today,
        cfg.stale_drill_days,
        lambda did: deck_pacing(col, storage, did, cache),
        lambda did: col.decks.name(DeckId(did)),
    )


def stale_in(rows: Sequence[WaitingRow]) -> int:
    return sum(r.stale for r in rows)
