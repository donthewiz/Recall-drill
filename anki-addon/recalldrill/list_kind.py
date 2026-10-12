"""Whether a card's list answer grades in any order (pure, 2026-10-12).

The anki-cards skill tags list notes with a ``ListKind::*`` tag. A tag decides
first: ``ListKind::Sequence`` is ordered; ``ListKind::AttributeSet`` and
``ListKind::Taxonomy`` are any order (Sequence wins if a note has both). With
no ``ListKind`` tag, the front's wording decides
(``engine.items.list_order_from_wording``). A card whose answer isn't a list
(``engine.items.list_items``) gets no ``anyOrder`` at all.
"""

from __future__ import annotations

from collections.abc import Iterable

from .card_state import has_tag
from .engine.items import list_items, list_order_from_wording

SEQUENCE_TAG = "ListKind::Sequence"
UNORDERED_TAGS = ("ListKind::AttributeSet", "ListKind::Taxonomy")


def any_order_for(front: str, back: str, tags: Iterable[str]) -> bool | None:
    """True (any order), False (ordered) or None (the answer isn't a list).

    ``front`` is the front's grading text, without the hint suffix; tags compare
    case-insensitively."""
    if list_items(back) is None:
        return None
    tag_list = list(tags)
    if has_tag(tag_list, SEQUENCE_TAG):
        return False
    if any(has_tag(tag_list, t) for t in UNORDERED_TAGS):
        return True
    return list_order_from_wording(front) == "any"
