"""list_kind.py: whether a card's list answer grades in any order (2026-10-12)."""

from __future__ import annotations

import pytest

from recalldrill.list_kind import any_order_for

LIST = "skeletal, cardiac, smooth"


@pytest.mark.parametrize(
    ("front", "tags", "expected"),
    [
        # No ListKind tag: the front's wording decides.
        ("Name the types of muscle tissue", (), True),
        ("List the regions from superior to inferior", (), False),
        ("Name the steps of the process", (), False),
        ("The cell cycle phases are [...]", (), False),
        # A tag beats the wording.
        ("List the regions from superior to inferior", ("ListKind::AttributeSet",), True),
        ("List the regions from superior to inferior", ("ListKind::Taxonomy",), True),
        ("Name the types of muscle tissue", ("ListKind::Sequence",), False),
        # Tags compare case-insensitively; Sequence wins over an unordered tag.
        ("Name the types of muscle tissue", ("listkind::sequence",), False),
        ("Name the steps", ("LISTKIND::ATTRIBUTESET",), True),
        ("Name the types", ("ListKind::Taxonomy", "ListKind::Sequence"), False),
        # Other tags don't count, nor does a ListKind child tag.
        ("Name the steps", ("rd::drill::A", "Layer::2"), False),
        ("Name the steps", ("ListKind::AttributeSet::x",), False),
    ],
)
def test_list_answers(front: str, tags: tuple[str, ...], expected: bool) -> None:
    assert any_order_for(front, LIST, tags) is expected


@pytest.mark.parametrize("back", ["radius and ulna", "alpha, beta", "a single answer"])
def test_not_a_list_gets_nothing(back: str) -> None:
    assert any_order_for("Name the types", back, ("ListKind::AttributeSet",)) is None
