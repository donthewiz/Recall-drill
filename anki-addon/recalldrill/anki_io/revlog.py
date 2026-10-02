"""The revlog join and what the tuning report reads from the collection. Read only.

:func:`read_revlog` is one query per batch of card ids (at most
:data:`BATCH` ids in an ``IN`` list). :func:`read_report_inputs` gathers what
``tuning.build_report`` needs: every history line, the drilled and holdout
cards with every card of their top-level decks (the baseline's candidates),
their decks and revlog rows, and the rollover hour.
"""

from __future__ import annotations

from collections.abc import Iterable, Iterator, Mapping
from dataclasses import dataclass
from typing import Any

from anki.collection import Collection, SearchNode
from anki.decks import DeckId

from .. import deck_settings
from ..history_store import read_every_log
from ..measure import RevlogRow, is_counted
from ..storage import Storage
from ..tuning import CardInfo, collect_cids

BATCH = 500
"""Card ids per ``IN (…)`` list."""


def _batches(ids: Iterable[int], size: int = BATCH) -> Iterator[list[int]]:
    batch: list[int] = []
    for i in ids:
        batch.append(int(i))
        if len(batch) == size:
            yield batch
            batch = []
    if batch:
        yield batch


def _db(col: Collection) -> Any:
    db = col.db
    assert db is not None, "the collection is closed"
    return db


def read_revlog(col: Collection, cids: Iterable[int]) -> list[RevlogRow]:
    """Every revlog row of ``cids``, oldest first within each batch."""
    out: list[RevlogRow] = []
    db = _db(col)
    for batch in _batches(sorted(set(cids))):
        rows = db.all(
            "select id, cid, ease, type, ivl, time from revlog "
            f"where cid in ({','.join(map(str, batch))}) order by id"
        )
        out += [RevlogRow(*(int(x) for x in r)) for r in rows]
    out.sort(key=lambda r: r.id)
    return out


def waiting_for_anki(col: Collection, handed_at: Mapping[int, int]) -> frozenset[int]:
    """The handed-off cards (id -> handoff time, ms) Anki hasn't rated since: no
    counted rating (``measure.is_counted``: ``ease >= 1``, type learn, review or
    relearn) with a later revlog id. A ``set_due_date`` row (type 4) doesn't count."""
    rated: set[int] = set()
    for r in read_revlog(col, handed_at):
        if is_counted(r) and r.id > handed_at.get(r.cid, 0):
            rated.add(r.cid)
    return frozenset(c for c in handed_at if c not in rated)


def card_decks(col: Collection, cids: Iterable[int]) -> dict[int, CardInfo]:
    """Each existing card's home deck (the original deck while it sits in a
    filtered deck) and top-level deck. Deleted cards are left out."""
    names: dict[int, str] = {}

    def name(did: int) -> str:
        if did not in names:
            names[did] = col.decks.name(DeckId(did))
        return names[did]

    out: dict[int, CardInfo] = {}
    db = _db(col)
    for batch in _batches(sorted(set(cids))):
        for cid, did, odid in db.all(
            f"select id, did, odid from cards where id in ({','.join(map(str, batch))})"
        ):
            full = name(int(odid) or int(did))
            out[int(cid)] = CardInfo(deck=full, top=full.split("::")[0])
    return out


@dataclass(frozen=True)
class ReportInputs:
    lines: list[dict[str, Any]]
    cards: dict[int, CardInfo]
    revlog: list[RevlogRow]
    rollover: int


def read_report_inputs(col: Collection, storage: Storage) -> ReportInputs:
    lines = read_every_log(storage)
    drilled, holdout = collect_cids(lines)
    cards = card_decks(col, drilled | holdout)
    tops = sorted({c.top for c in cards.values()})
    pool: set[int] = set(cards)
    for top in tops:
        pool.update(int(c) for c in col.find_cards(col.build_search_string(SearchNode(deck=top))))
    cards = card_decks(col, pool)
    return ReportInputs(
        lines=lines,
        cards=cards,
        revlog=read_revlog(col, pool | drilled | holdout),
        rollover=col.get_preferences().scheduling.rollover,
    )


def encode_reps_overrides(col: Collection, storage: Storage, proposed: int) -> list[str]:
    """Decks whose saved ``encodeReps`` differs from ``proposed``: it wins over
    the config default there."""
    out: list[str] = []
    for did, settings in deck_settings.load_all(storage).items():
        reps = settings.get("encodeReps")
        if reps is None or reps == proposed:
            continue
        deck = col.decks.get(DeckId(int(did)), default=False) if did.isdigit() else None
        if deck is not None:
            out.append(f"{deck['name']} ({reps})")
    return sorted(out)
