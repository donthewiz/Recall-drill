"""What to drill: cards in a scope, filtered by class and template, in order.

Order:

- **Deck order**: new cards (type 0) by new-queue position (``due``), then
  everything else by ``(note id, ord)``. New cards keep their queue position,
  so a deck whose new cards were laid out ``Layer::1 -> 4`` keeps that order;
  they are never re-sorted by note id.
- **Priority first** (default): by class rank (:data:`PRIORITY_RANK`), then
  deck order.

``exclude_cids`` leaves given cards out before anything else (counted as
``excluded``): the "my rd::hard cards" entry uses it for the cards of a tagged
note that weren't hard in their last handoff (``rd::hard`` is a note tag, so
siblings and cloze siblings share it; the template filter can't tell cloze
cards apart).

``exclude_holdout_tag`` (config ``holdout_exclude``) leaves out the cards of
notes tagged ``rd::holdout`` (counted as ``holdout_tagged``): a past holdout
stays an undrilled control.

**Holdout** (Phase 5, :func:`apply_holdout`): with ``holdout_pct`` above 0 and
a deck scope, eligible ``new`` / ``suspended_new`` cards whose hash falls in the
holdout are set aside (``Selection.holdout``) while walking the ordered list,
until ``max_cards`` drill cards are picked.

A card is ineligible, and counted by reason, when (first match wins):
image occlusion, marked ineligible in mappings.json, unmapped, empty answer,
or (unless that class is enabled) in a filtered deck or buried. Every other
card is eligible; it's picked when its class is enabled, up to ``max_cards``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, cast

from anki.collection import Collection, SearchNode
from anki.decks import DeckId

from ..difficulty import SKIP_MAX_DIFFICULTY, SKIP_MIN_STABILITY
from ..holdout import HOLDOUT_CLASSES, TAG_HOLDOUT, is_holdout
from .cards import (
    CARD_CLASSES,
    DEFAULT_ENABLED,
    RED_FLAG,
    YOUNG_IVL,
    CardClass,
    CardSnapshot,
    NoteCache,
    classify,
    has_tag,
    read_snapshots,
)
from .handoff import TAG_DRILLED
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
    "stable",
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
    exclude_cids: frozenset[int] = frozenset()
    """Cards left out, whatever their class (counted as ``Selection.excluded``)."""
    exclude_holdout_tag: bool = False
    """Leave out notes tagged ``rd::holdout`` (counted as ``Selection.holdout_tagged``)."""
    holdout_pct: int = 0
    """Holdout percentage (0 = off). Applied to deck scopes only."""
    holdout_salt: str = ""
    skip_min_stability: float = SKIP_MIN_STABILITY
    """The ``stable`` class (``classify``): FSRS stability at least this ..."""
    skip_max_difficulty: float = SKIP_MAX_DIFFICULTY
    """... and difficulty at most this."""


def scope_to_json(scope: Scope) -> dict[str, Any]:
    """``sessions.ScopeJson``."""
    return {"deckId": scope.deck_id, "search": scope.search}


def scope_from_json(d: Mapping[str, Any]) -> Scope:
    return Scope(deck_id=d.get("deckId"), search=d.get("search"))


def options_to_json(o: SelectOptions) -> dict[str, Any]:
    """For the session save's ``selectOptions``."""
    return {
        "enabled": sorted(o.enabled),
        "card_ords": {str(k): sorted(v) for k, v in sorted(o.card_ords.items())},
        "max_cards": o.max_cards,
        "extra_tag": o.extra_tag,
        "order": o.order,
        "young_ivl": o.young_ivl,
        "flag": o.flag,
        "exclude_cids": sorted(o.exclude_cids),
        "exclude_holdout_tag": o.exclude_holdout_tag,
        "holdout_pct": o.holdout_pct,
        "holdout_salt": o.holdout_salt,
        "skip_min_stability": o.skip_min_stability,
        "skip_max_difficulty": o.skip_max_difficulty,
    }


def options_from_json(d: Mapping[str, Any]) -> SelectOptions:
    """Inverse of :func:`options_to_json`; unknown classes are dropped."""
    enabled = frozenset(c for c in d.get("enabled", DEFAULT_ENABLED) if c in CARD_CLASSES)
    ords = cast(Mapping[str, Any], d.get("card_ords") or {})
    return SelectOptions(
        enabled=cast(frozenset[CardClass], enabled),
        card_ords={int(k): frozenset(int(x) for x in v) for k, v in ords.items()},
        max_cards=d.get("max_cards"),
        extra_tag=d.get("extra_tag"),
        order=d.get("order", "priority_first"),
        young_ivl=int(d.get("young_ivl", YOUNG_IVL)),
        flag=int(d.get("flag", RED_FLAG)),
        exclude_cids=frozenset(int(x) for x in cast(list[Any], d.get("exclude_cids") or [])),
        exclude_holdout_tag=bool(d.get("exclude_holdout_tag", False)),
        holdout_pct=int(d.get("holdout_pct") or 0),
        holdout_salt=str(d.get("holdout_salt") or ""),
        skip_min_stability=float(d.get("skip_min_stability", SKIP_MIN_STABILITY)),
        skip_max_difficulty=float(d.get("skip_max_difficulty", SKIP_MAX_DIFFICULTY)),
    )


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
    excluded: int = 0
    """Cards left out by ``exclude_cids``."""
    holdout: list[Candidate] = field(default_factory=list[Candidate])
    """Eligible cards set aside as the measurement control: not drilled, handed
    off as new cards (``apply_holdout``)."""
    holdout_tagged: int = 0
    """Cards left out because their note is tagged ``rd::holdout``."""


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


@dataclass(frozen=True)
class HoldoutSpec:
    pct: int
    salt: str


def holdout_spec(scope: Scope, options: SelectOptions) -> HoldoutSpec | None:
    """The holdout a selection applies: deck scopes only (never a search such as
    ``tag:rd::hard``; a drill-again session never selects), and only when on."""
    if scope.deck_id is None or options.holdout_pct <= 0 or not options.holdout_salt:
        return None
    return HoldoutSpec(options.holdout_pct, options.holdout_salt)


def holdout_candidate(c: Candidate, spec: HoldoutSpec) -> bool:
    """A new card (suspended or not) of a note never drilled or held out, in the hash's
    share. A note already tagged ``rd::drilled`` isn't a clean control."""
    return (
        c.card_class in HOLDOUT_CLASSES
        and not has_tag(c.snap.tags, TAG_DRILLED)
        and not has_tag(c.snap.tags, TAG_HOLDOUT)
        and is_holdout(spec.salt, c.snap.cid, spec.pct)
    )


def apply_holdout(
    ordered: Sequence[Candidate], max_cards: int | None, spec: HoldoutSpec | None
) -> tuple[list[Candidate], list[Candidate]]:
    """(drill, holdout): walks ``ordered``, setting holdout cards aside, until
    ``max_cards`` drill cards are picked (None: all of them).

    A holdout card whose note also has a picked drill card is dropped from the
    holdout (and not drilled): its sibling's drill would contaminate the control.
    """
    limit = None if max_cards is None else max(0, max_cards)
    drill: list[Candidate] = []
    held: list[Candidate] = []
    for c in ordered:
        if limit is not None and len(drill) >= limit:
            break
        if spec is not None and holdout_candidate(c, spec):
            held.append(c)
        else:
            drill.append(c)
    drilled_notes = {c.snap.nid for c in drill}
    return drill, [c for c in held if c.snap.nid not in drilled_notes]


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
    excluded = 0
    holdout_tagged = 0
    met: dict[tuple[int, int], NoteMapping] = {}
    cands: list[Candidate] = []

    for snap in read_snapshots(col, cids, cache):
        mapping = mappings.for_card(snap.ntid, snap.ord)
        met[(mapping.ntid, mapping.template_ord)] = mapping
        if snap.cid in options.exclude_cids:
            excluded += 1
            continue
        if options.exclude_holdout_tag and has_tag(snap.tags, TAG_HOLDOUT):
            holdout_tagged += 1
            continue
        allowed = options.card_ords.get(snap.ntid)
        if allowed is not None and mapping.template_ord not in allowed:
            template_excluded += 1
            continue
        card_class = classify(
            snap,
            options.young_ivl,
            options.flag,
            options.skip_min_stability,
            options.skip_max_difficulty,
        )
        reason, answer = content_check(col, snap, mapping, cache)
        if reason is None:
            reason = state_reason(card_class, options.enabled)
        if reason is not None:
            ineligible[reason] += 1
            continue
        eligible[card_class] += 1
        if card_class in options.enabled:
            cands.append(Candidate(snap, card_class, mapping, answer))

    picked, held = apply_holdout(
        order_candidates(cands, options.order), options.max_cards, holdout_spec(scope, options)
    )
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
        excluded=excluded,
        holdout=held,
        holdout_tagged=holdout_tagged,
    )
    return selection
