"""Card state, read once, and the class each card falls in.

:class:`CardSnapshot` and :func:`classify` are pure, so classification is
tested without a collection. :func:`read_snapshots` is the one pass over
``col.get_card``.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import Card, CardId
from anki.collection import Collection
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_RELEARNING,
    CARD_TYPE_REV,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_SIBLING_BURIED,
    QUEUE_TYPE_SUSPENDED,
)
from anki.notes import Note, NoteId

# Defined in the pure sources module (SourceRef carries it); re-exported here.
from ..sources import CardClass as CardClass

CARD_CLASSES: tuple[CardClass, ...] = (
    "in_filtered_deck",
    "buried",
    "flagged",
    "leech",
    "suspended_new",
    "suspended_review",
    "lapsed",
    "learning",
    "new",
    "young",
    "mature",
)
"""Every class, in :func:`classify`'s order (first match wins)."""

DEFAULT_ENABLED: frozenset[CardClass] = frozenset(
    {"flagged", "leech", "suspended_new", "lapsed", "new", "young"}
)
"""Classes a selection picks from unless told otherwise."""

RED_FLAG = 1
"""Anki's red flag: the anki-cards skill's repair mark (its export is ``flag:1``)."""

YOUNG_IVL = 21
"""Review cards with an interval below this many days are young."""


@dataclass(frozen=True)
class CardSnapshot:
    cid: int
    nid: int
    did: int
    odid: int
    ord: int
    ntid: int
    type: int
    queue: int
    ivl: int
    due: int
    lapses: int
    reps: int
    factor: int
    flags: int
    """The user flag (``card.user_flag()``, 0-7), not the raw flags column."""
    tags: tuple[str, ...]
    fsrs_d: float | None
    """FSRS difficulty, 1-10 (``memory_state.difficulty``), or None."""
    fsrs_s: float | None
    """FSRS stability in days, or None."""
    odue: int = 0
    """The home deck's due while in a filtered deck (new-queue position for new cards)."""

    @property
    def home_did(self) -> int:
        """The deck the card belongs to, even while it sits in a filtered deck."""
        return self.odid or self.did

    @property
    def new_position(self) -> int:
        """New-queue position (meaningful for type 0 only)."""
        return self.odue if self.odid else self.due


def has_tag(tags: Iterable[str], tag: str) -> bool:
    """Anki tags compare case-insensitively."""
    want = tag.casefold()
    return any(t.casefold() == want for t in tags)


def classify(snap: CardSnapshot, young_ivl: int = YOUNG_IVL, flag: int = RED_FLAG) -> CardClass:
    """The card's class. First match wins, so a red-flagged mature card is
    ``flagged`` and a suspended leech is ``leech``."""
    if snap.odid != 0:
        return "in_filtered_deck"
    if snap.queue in (QUEUE_TYPE_SIBLING_BURIED, QUEUE_TYPE_MANUALLY_BURIED):
        return "buried"
    if flag and snap.flags == flag:
        return "flagged"
    if has_tag(snap.tags, "leech"):
        return "leech"
    if snap.queue == QUEUE_TYPE_SUSPENDED:
        return "suspended_new" if snap.type == CARD_TYPE_NEW else "suspended_review"
    if snap.type in (CARD_TYPE_REV, CARD_TYPE_RELEARNING) and snap.lapses > 0:
        return "lapsed"
    if snap.type in (CARD_TYPE_LRN, CARD_TYPE_RELEARNING):
        return "learning"
    if snap.type == CARD_TYPE_NEW:
        return "new"
    if snap.ivl < young_ivl:
        return "young"
    return "mature"


def snapshot(card: Card, note: Note) -> CardSnapshot:
    mem = card.memory_state
    return CardSnapshot(
        cid=card.id,
        nid=card.nid,
        did=card.did,
        odid=card.odid,
        ord=card.ord,
        ntid=note.mid,
        type=card.type,
        queue=card.queue,
        ivl=card.ivl,
        due=card.due,
        lapses=card.lapses,
        reps=card.reps,
        factor=card.factor,
        flags=card.user_flag(),
        tags=tuple(note.tags),
        fsrs_d=mem.difficulty if mem is not None else None,
        fsrs_s=mem.stability if mem is not None else None,
        odue=card.odue,
    )


class NoteCache:
    """Notes by id, so a note's sibling cards share one read."""

    def __init__(self, col: Collection) -> None:
        self.col = col
        self._notes: dict[int, Note] = {}

    def get(self, nid: int) -> Note:
        note = self._notes.get(nid)
        if note is None:
            note = self.col.get_note(NoteId(nid))
            self._notes[nid] = note
        return note


def read_snapshots(
    col: Collection, cids: Iterable[int], notes: NoteCache | None = None
) -> list[CardSnapshot]:
    """One pass over ``col.get_card``, in ``cids`` order."""
    cache = notes if notes is not None else NoteCache(col)
    out: list[CardSnapshot] = []
    for cid in cids:
        card = col.get_card(CardId(cid))
        out.append(snapshot(card, cache.get(card.nid)))
    return out
