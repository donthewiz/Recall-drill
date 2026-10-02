"""What to drill: cards in a scope, filtered by class and template, in order.

Order:

- **Deck order**: new cards (type 0) by new-queue position (``due``), then
  everything else by ``(note id, ord)``. New cards keep their queue position,
  so a deck whose new cards were laid out ``Layer::1 -> 4`` keeps that order;
  they are never re-sorted by note id.
- **Priority first** (default): by class rank (:data:`PRIORITY_RANK`), then
  deck order.

A card is ineligible, and counted by reason, when (first match wins):
image occlusion, marked ineligible in mappings.json, unmapped, empty answer,
or (unless that class is enabled) in a filtered deck or buried. Every other
card is eligible; it's picked when its class is enabled, up to ``max_cards``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Literal

from anki.collection import Collection, SearchNode
from anki.decks import DeckId

from .cards import (
    CARD_CLASSES,
    DEFAULT_ENABLED,
    RED_FLAG,
    YOUNG_IVL,
    CardClass,
    CardSnapshot,
    NoteCache,
    classify,
    read_snapshots,
)
from .notetypes import MappingTable, NoteMapping, answer_text, is_io_note

OrderMode = Literal["priority_first", "deck_order"]

PRIORITY_RANK: tuple[CardClass, ...] = (
    "flagged",
    "leech",
    "lapsed",
    "suspended_new",
    "new",
    "young",
    # Off by default; ranked last when switched on.
    "suspended_review",
    "learning",
    "mature",
    "in_filtered_deck",
    "buried",
)
_RANK = {c: i for i, c in enumerate(PRIORITY_RANK)}

IneligibleReason = Literal[
    "image_occlusion", "marked_ineligible", "unmapped", "empty_answer", "filtered_deck", "buried"
]
INELIGIBLE_REASONS: tuple[IneligibleReason, ...] = (
    "image_occlusion",
    "marked_ineligible",
    "unmapped",
    "empty_answer",
    "filtered_deck",
    "buried",
)


@dataclass(frozen=True)
class Scope:
    """A deck (with its subdecks) or a raw Anki search."""

    deck_id: int | None = None
    search: str | None = None

    def __post_init__(self) -> None:
        if (self.deck_id is None) == (self.search is None):
            raise ValueError("Scope needs exactly one of deck_id or search")

    def deck_name(self, col: Collection) -> str | None:
        if self.deck_id is None:
            return None
        deck = col.decks.get(DeckId(self.deck_id), default=False)
        if deck is None:
            raise KeyError(f"deck {self.deck_id} not found")
        return str(deck["name"])

    def to_search(self, col: Collection, extra_tag: str | None = None) -> str:
        """``deck:"<full name>"`` (subdecks included, and cards of the deck that
        sit in a filtered deck) or the raw search, AND an exact ``tag:``."""
        name = self.deck_name(col)
        base: str | SearchNode = SearchNode(deck=name) if name is not None else f"({self.search})"
        if extra_tag:
            return col.build_search_string(base, SearchNode(tag=extra_tag))
        return col.build_search_string(base)


@dataclass(frozen=True)
class SelectOptions:
    enabled: frozenset[CardClass] = DEFAULT_ENABLED
    card_ords: Mapping[int, frozenset[int]] = field(default_factory=dict[int, frozenset[int]])
    """Template filter per note type id. A note type that isn't here: all templates."""
    max_cards: int | None = None
    extra_tag: str | None = None
    order: OrderMode = "priority_first"
    young_ivl: int = YOUNG_IVL
    flag: int = RED_FLAG


@dataclass(frozen=True)
class Candidate:
    """An eligible card, with what selection learned about it."""

    snap: CardSnapshot
    card_class: CardClass
    mapping: NoteMapping
    answer: str
    """Grading text of the answer (non-empty)."""


@dataclass
class Selection:
    scope: Scope
    options: SelectOptions
    picked: list[Candidate]
    eligible_counts: dict[CardClass, int]
    picked_counts: dict[CardClass, int]
    ineligible: dict[IneligibleReason, int]
    template_excluded: int
    """Cards left out by ``card_ords``."""
    total: int
    """Cards the scope's search found."""
    sibling_cards: int
    """Picked cards that share a note with another picked card."""
    sibling_notes: int
    mappings: dict[tuple[int, int], NoteMapping]
    """Every (note type, template) met in the scope."""


# ---------------------------------------------------------------------------
# Pure
# ---------------------------------------------------------------------------


def deck_order_key(snap: CardSnapshot) -> tuple[int, int, int, int]:
    if snap.type == 0:
        return (0, snap.new_position, snap.nid, snap.ord)
    return (1, 0, snap.nid, snap.ord)


def order_candidates(cands: Iterable[Candidate], order: OrderMode) -> list[Candidate]:
    if order == "deck_order":
        return sorted(cands, key=lambda c: deck_order_key(c.snap))
    return sorted(cands, key=lambda c: (_RANK[c.card_class], deck_order_key(c.snap)))


def sibling_counts(picked: Sequence[Candidate]) -> tuple[int, int]:
    """(cards, notes) among ``picked`` where a note has two or more picked cards."""
    per_note = Counter(c.snap.nid for c in picked)
    shared = [n for n in per_note.values() if n > 1]
    return sum(shared), len(shared)


def state_reason(card_class: CardClass, enabled: frozenset[CardClass]) -> IneligibleReason | None:
    if card_class == "in_filtered_deck" and card_class not in enabled:
        return "filtered_deck"
    if card_class == "buried" and card_class not in enabled:
        return "buried"
    return None


def apply_holdout(selection: Selection) -> Selection:
    """Hook for Phase 5 (holding cards back for a later check). No-op for now."""
    return selection


# ---------------------------------------------------------------------------
# Collection
# ---------------------------------------------------------------------------


def content_check(
    col: Collection, snap: CardSnapshot, mapping: NoteMapping, notes: NoteCache
) -> tuple[IneligibleReason | None, str]:
    """(reason, answer text): why the card can't be drilled, else its answer."""
    if mapping.kind == "image_occlusion":
        return "image_occlusion", ""
    if mapping.ineligible:
        return "marked_ineligible", ""
    if mapping.answer_field is None:
        return "unmapped", ""
    note = notes.get(snap.nid)
    if is_io_note(note, mapping):
        return "image_occlusion", ""
    answer = answer_text(col, note, mapping, snap.ord)
    if not answer:
        return "empty_answer", ""
    return None, answer


def select_cards(
    col: Collection,
    scope: Scope,
    options: SelectOptions,
    mappings: MappingTable,
    notes: NoteCache | None = None,
) -> Selection:
    cache = notes if notes is not None else NoteCache(col)
    cids = col.find_cards(scope.to_search(col, options.extra_tag))
    eligible: dict[CardClass, int] = dict.fromkeys(CARD_CLASSES, 0)
    ineligible: dict[IneligibleReason, int] = dict.fromkeys(INELIGIBLE_REASONS, 0)
    template_excluded = 0
    met: dict[tuple[int, int], NoteMapping] = {}
    cands: list[Candidate] = []

    for snap in read_snapshots(col, cids, cache):
        mapping = mappings.for_card(snap.ntid, snap.ord)
        met[(mapping.ntid, mapping.template_ord)] = mapping
        allowed = options.card_ords.get(snap.ntid)
        if allowed is not None and mapping.template_ord not in allowed:
            template_excluded += 1
            continue
        card_class = classify(snap, options.young_ivl, options.flag)
        reason, answer = content_check(col, snap, mapping, cache)
        if reason is None:
            reason = state_reason(card_class, options.enabled)
        if reason is not None:
            ineligible[reason] += 1
            continue
        eligible[card_class] += 1
        if card_class in options.enabled:
            cands.append(Candidate(snap, card_class, mapping, answer))

    picked = order_candidates(cands, options.order)
    if options.max_cards is not None:
        picked = picked[: max(0, options.max_cards)]
    picked_counts: dict[CardClass, int] = dict.fromkeys(CARD_CLASSES, 0)
    for c in picked:
        picked_counts[c.card_class] += 1
    sib_cards, sib_notes = sibling_counts(picked)
    selection = Selection(
        scope=scope,
        options=options,
        picked=picked,
        eligible_counts=eligible,
        picked_counts=picked_counts,
        ineligible=ineligible,
        template_excluded=template_excluded,
        total=len(cids),
        sibling_cards=sib_cards,
        sibling_notes=sib_notes,
        mappings=dict(sorted(met.items())),
    )
    return apply_holdout(selection)
