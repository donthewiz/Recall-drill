"""Section progress (v0.3), pure: the buckets, the counts, "done"."""

from __future__ import annotations

from recalldrill.sections import (
    COLUMNS,
    CardFacts,
    bucket,
    cells,
    render_text,
    section_row,
)

DRILLED = {1, 2, 3}


def card(
    cid: int, *, new: bool = True, suspended: bool = False, tags: tuple[str, ...] = ()
) -> CardFacts:
    return CardFacts(cid, new, suspended, tags)


def test_each_card_falls_in_one_bucket_first_match_wins() -> None:
    assert bucket(card(1), DRILLED) == "drilled"
    assert bucket(card(1, new=False), DRILLED) == "drilled"  # drilled, then rated in Anki
    assert bucket(card(1, tags=("rd::undrilled",)), DRILLED) == "drilled"
    assert bucket(card(9, tags=("rd::undrilled",)), DRILLED) == "released"
    assert bucket(card(9, new=False, tags=("rd::undrilled",)), DRILLED) == "released"
    assert bucket(card(9, new=False), DRILLED) == "introduced"
    assert bucket(card(9, suspended=True, tags=("rd::drill::A",)), DRILLED) == "held"
    assert bucket(card(9, suspended=True, tags=("rd::held",)), DRILLED) == "held"
    assert bucket(card(9, suspended=True, tags=("RD::Held",)), DRILLED) == "held"
    # Only the exact tags: rd::drilled / rd::holdout / rd::heldx are not waiting tags.
    assert bucket(card(9, suspended=True, tags=("rd::drilled",)), DRILLED) == "open"
    assert bucket(card(9, suspended=True, tags=("rd::heldx",)), DRILLED) == "open"
    # Unsuspended and undrilled: not in Anki yet, not held.
    assert bucket(card(9), DRILLED) == "open"
    assert bucket(card(9, tags=("rd::held",)), DRILLED) == "open"  # tag but not suspended


def test_a_row_counts_and_is_done_when_every_new_card_is_drilled_or_released() -> None:
    cards = [
        card(1),  # drilled, still new (waiting for its first rating)
        card(2, new=False),  # drilled and rated
        card(3),  # drilled
        card(10, new=False),  # introduced before the add-on
        card(11, tags=("rd::undrilled",)),  # released undrilled
    ]
    row = section_row(7, "Lab 2::Bones", "Bones", cards, DRILLED)
    assert (row.cards, row.new, row.introduced) == (5, 3, 2)
    assert (row.drilled, row.released, row.held, row.open) == (3, 1, 0, 0)
    assert row.pct_drilled == 60 and row.done and row.status == "done"


def test_a_row_with_a_card_left_is_not_done() -> None:
    cards = [card(1), card(20, suspended=True, tags=("rd::held",)), card(21), card(22)]
    row = section_row(7, "Lab 2::Joints", "Joints", cards, DRILLED)
    assert (row.drilled, row.held, row.open) == (1, 1, 2)
    assert row.to_go == 3 and not row.done and row.status == "3 to go"
    assert row.pct_drilled == 25


def test_a_row_without_new_cards_is_done_with_a_note() -> None:
    row = section_row(7, "Lab 2::Old", "Old", [card(10, new=False), card(11, new=False)], DRILLED)
    assert row.new == 0 and row.done and row.status == "done (no new cards)"
    empty = section_row(8, "Lab 2::Empty", "Empty", [], DRILLED)
    assert (empty.cards, empty.pct_drilled, empty.status) == (0, 0, "done (no new cards)")


def test_the_table_text() -> None:
    rows = [
        section_row(1, "L::Bones", "Bones", [card(1), card(2), card(3)], DRILLED),
        section_row(
            2, "L::Joints", "Joints", [card(20, suspended=True, tags=("rd::held",))], DRILLED
        ),
    ]
    assert cells(rows[0]) == ["Bones", "3", "3", "0", "0", "0", "100%", "done"]
    assert render_text(rows).splitlines() == [
        "Section  Cards  Drilled  Released undrilled  Held / waiting  Not in Anki, not held  "
        "% drilled  Status",
        "Bones    3      3        0                   0               0                      "
        "100%       done",
        "Joints   1      0        0                   1               0                      "
        "0%         1 to go",
    ]
    assert len(COLUMNS) == 8
