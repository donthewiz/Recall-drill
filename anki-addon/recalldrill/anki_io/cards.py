"""Card state, read once, and the class each card falls in.

:class:`CardSnapshot` and :func:`classify` are pure, so classification is
tested without a collection. :func:`read_snapshots` is the one pass over
``col.get_card``.
"""

from __future__ import annotations

from collections.abc import Iterable

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

# Pure, so difficulty.py can take a snapshot; re-exported here.
from ..card_state import CardSnapshot as CardSnapshot
from ..card_state import has_tag as has_tag
from ..difficulty import SKIP_MAX_DIFFICULTY, SKIP_MIN_STABILITY, is_stable

# Defined in the pure sources module (SourceRef carries it); re-exported here.
from ..sources import CardClass as CardClass

CARD_CLASSES: tuple[CardClass, ...] = (
    "in_filtered_deck",
    "buried",
    "flagged",
    "leech",
    "stable",
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


def classify(
    snap: CardSnapshot,
    young_ivl: int = YOUNG_IVL,
    flag: int = RED_FLAG,
    skip_min_stability: float = SKIP_MIN_STABILITY,
    skip_max_difficulty: float = SKIP_MAX_DIFFICULTY,
) -> CardClass:
    """The card's class. First match wins, so a red-flagged mature card is
    ``flagged`` and a suspended leech is ``leech``.

    ``stable`` (Phase 6, off by default in selection): FSRS says the card is
    already well learned (stability at least ``skip_min_stability`` days,
    difficulty at most ``skip_max_difficulty``), so drilling it spends trials
    for nothing."""
    if snap.odid != 0:
        return "in_filtered_deck"
    if snap.queue in (QUEUE_TYPE_SIBLING_BURIED, QUEUE_TYPE_MANUALLY_BURIED):
        return "buried"
    if flag and snap.flags == flag:
        return "flagged"
    if has_tag(snap.tags, "leech"):
        return "leech"
    if is_stable(snap, skip_min_stability, skip_max_difficulty):
        return "stable"
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
