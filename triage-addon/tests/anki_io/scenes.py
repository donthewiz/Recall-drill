"""Scratch collections for the Anki I/O tests. Never a real profile."""

from __future__ import annotations

import itertools
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection
from anki.consts import CardQueue, CardType
from anki.notes import NoteId


def new_collection(tmp_path: Path) -> Collection:
    return Collection(str(tmp_path / "scratch.anki2"))


def add_note(
    col: Collection, deck: str, front: str, *, model: str = "Basic", tags: str = ""
) -> NoteId:
    nt = col.models.by_name(model)
    assert nt is not None
    note = col.new_note(nt)
    note["Front"] = front
    note["Back"] = "back " + front
    if tags:
        note.tags = tags.split()
    deck_id = col.decks.id(deck)
    assert deck_id is not None
    col.add_note(note, deck_id)
    return note.id


def card_ids(col: Collection, nid: NoteId) -> list[CardId]:
    return sorted(col.get_note(nid).card_ids())


def make_learning(col: Collection, cid: CardId, *, agains: int = 0) -> None:
    """Put a card in the learning state (type 1, queue 1) with ``agains`` learn-type Again rows."""
    card = col.get_card(cid)
    card.type = CardType(1)
    card.queue = CardQueue(1)
    card.due = int(time.time()) + 600
    card.left = 1001
    col.update_card(card)
    for i in range(agains):
        add_revlog(col, cid, type_=0, ease=1, when=i)


def make_review(col: Collection, cid: CardId, *, relearning: bool = False) -> None:
    card = col.get_card(cid)
    card.type = CardType(3 if relearning else 2)
    card.queue = CardQueue(1 if relearning else 2)
    card.due = int(time.time()) + 600 if relearning else col.sched.today
    card.ivl = 5
    col.update_card(card)


_revlog_ids = itertools.count(int(time.time() * 1000))


def add_revlog(col: Collection, cid: CardId, *, type_: int, ease: int, when: int = 0) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog values (?, ?, -1, ?, 0, 0, 2500, 1000, ?)",
        next(_revlog_ids),
        cid,
        ease,
        type_,
    )


@dataclass(frozen=True)
class CardState:
    """Everything a set-aside / release must restore, field by field."""

    flag: int
    queue: int
    type: int
    due: int
    ivl: int
    left: int
    custom_data: str
    tags: tuple[str, ...]
    suspended: bool


def state(col: Collection, cid: CardId) -> CardState:
    card = col.get_card(cid)
    return CardState(
        flag=card.user_flag(),
        queue=card.queue,
        type=card.type,
        due=card.due,
        ivl=card.ivl,
        left=card.left,
        custom_data=card.custom_data,
        tags=tuple(sorted(col.get_note(card.nid).tags)),
        suspended=card.queue == -1,
    )


def states(col: Collection, cids: list[CardId]) -> dict[int, dict[str, Any]]:
    return {int(c): asdict(state(col, c)) for c in cids}


def revlog_count(col: Collection) -> int:
    assert col.db is not None
    return int(col.db.scalar("select count() from revlog") or 0)


def set_flag(col: Collection, cid: CardId, flag: int) -> None:
    col.set_user_flag_for_cards(flag, [cid])


def set_custom_data(col: Collection, cid: CardId, raw: str) -> None:
    card = col.get_card(cid)
    card.custom_data = raw
    col.update_card(card)
