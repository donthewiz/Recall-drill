"""Layer progress (v0.3.1), pure: layer rows, the can't-drill bucket, Next."""

from __future__ import annotations

from recalldrill.sections import (
    CardFacts,
    Chapter,
    bucket,
    build_progress,
    progress_cells,
    progress_columns,
    section_row,
)

CHAPTERS = (Chapter(11, "L::A", "A"), Chapter(12, "L::B", "B"))


def card(
    cid: int,
    layer: int | None = 1,
    chapter: int = 0,
    *,
    new: bool = True,
    suspended: bool = False,
    cant: bool = False,
    tags: tuple[str, ...] = (),
) -> CardFacts:
    layer_tag = (f"Layer::{layer}",) if layer is not None else ()
    return CardFacts(cid, new, suspended, (*layer_tag, *tags), cant, chapter)


def test_cant_drill_is_a_bucket_for_new_undrilled_cards_only() -> None:
    assert bucket(card(1, cant=True), set()) == "cant_drill"
    assert bucket(card(1, cant=True, suspended=True, tags=("rd::held",)), set()) == "cant_drill"
    assert bucket(card(1, cant=True), {1}) == "drilled"
    assert bucket(card(1, cant=True, tags=("rd::undrilled",)), set()) == "released"
    assert bucket(card(1, cant=True, new=False), set()) == "introduced"


def test_cant_drill_cards_never_block_done_and_are_not_new() -> None:
    row = section_row(1, "L", "Layer 1", [card(1, cant=True), card(2, cant=True)], set())
    assert (row.cant_drill, row.new, row.to_go) == (2, 0, 0)
    assert row.done and row.status == "done (no new cards)"
    mixed = section_row(1, "L", "Layer 1", [card(1, cant=True), card(2)], set())
    assert mixed.to_go == 1 and mixed.status == "1 to go" and not mixed.done


def test_chapter_cells_count_drilled_released_and_introduced_over_drillable_cards() -> None:
    cards = [
        card(1, chapter=0),  # drilled
        card(2, chapter=0, tags=("rd::undrilled",)),  # released
        card(3, chapter=0, new=False),  # introduced
        card(4, chapter=0),  # open
        card(5, chapter=0, cant=True),  # not counted
        card(6, chapter=1),  # open
    ]
    row = section_row(1, "L", "Layer 1", cards, {1}, layer=1, chapter_count=2)
    assert row.chapters == ((3, 4), (0, 1))


def test_layer_rows_are_sorted_by_number_with_no_layer_last() -> None:
    cards = [card(1, 3), card(2, None), card(3, 1), card(4, 10), card(5, 2)]
    p = build_progress(7, "L", CHAPTERS, cards, set())
    assert p.by_layer
    assert [r.label for r in p.rows] == ["Layer 1", "Layer 2", "Layer 3", "Layer 10", "No layer"]
    assert all(r.did == 7 for r in p.rows)  # a layer row drills from the chosen deck


def test_next_is_the_first_row_not_done_and_targets_the_chosen_deck() -> None:
    cards = [card(1, 1, tags=("rd::undrilled",)), card(2, 2), card(3, 3)]
    p = build_progress(7, "L", CHAPTERS, cards, set())
    assert [r.done for r in p.rows] == [True, False, False]
    assert p.next_index == 1 and p.next_target == 7
    assert [progress_cells(p, i)[-1] for i in range(3)] == ["", "Next", ""]
    assert progress_columns(p)[-1] == "Next" and progress_columns(p)[0] == "Layer"
    assert progress_columns(p)[-4:-1] == ["Can't drill", "A", "B"]
    done = build_progress(7, "L", CHAPTERS, [card(1, 1, tags=("rd::undrilled",))], set())
    assert done.next_index is None and done.next_target is None


def test_without_layers_rows_are_the_chapters_in_the_given_order() -> None:
    cards = [card(1, None, 1), card(2, None, 0), card(3, None, -1)]
    p = build_progress(7, "L", CHAPTERS, cards, set())
    assert not p.by_layer
    assert [r.label for r in p.rows] == ["(cards in this deck itself)", "A", "B"]
    assert [r.did for r in p.rows] == [7, 11, 12]
    assert p.next_target == 7  # the first row not done: the deck's own cards
    only = build_progress(7, "L", CHAPTERS, [card(2, None, 1)], set())
    assert only.rows[0].did == 11 and only.next_target == 12


def test_drill_next_targets_the_next_layer_with_its_tag_or_the_next_subdeck() -> None:
    # Layer 1 done, Layer 2 has a card left: the chosen deck, Only with tag = Layer::2.
    by_layer = build_progress(
        7, "L", CHAPTERS, [card(1, 1), card(2, 1), card(3, 2), card(4, 2)], {1, 2}
    )
    assert by_layer.by_layer and by_layer.next_row is not None and by_layer.next_row.layer == 2
    assert (by_layer.next_target, by_layer.next_tag) == (7, "Layer::2")
    # The tag is written as the skill writes it, whatever the note's own case.
    cased = build_progress(
        7, "L", CHAPTERS, [card(1, None, tags=("LAYER::3",)), card(2, None)], set()
    )
    assert cased.next_row is not None and cased.next_row.layer == 3
    assert cased.next_tag == "Layer::3"
    # A "No layer" row next: no tag (it has no layer to name).
    bare = build_progress(7, "L", CHAPTERS, [card(1, 1), card(2, None)], {1})
    assert bare.next_row is not None and bare.next_row.layer is None
    assert (bare.next_target, bare.next_tag) == (7, None)
    # Subdeck rows: the next subdeck, no tag.
    subdecks = build_progress(
        7, "L", CHAPTERS, [card(1, None, chapter=0), card(2, None, chapter=1)], {1}
    )
    assert not subdecks.by_layer
    assert (subdecks.next_target, subdecks.next_tag) == (12, None)
    # Everything done: nothing to drill.
    done = build_progress(7, "L", CHAPTERS, [card(1, 1), card(2, 2)], {1, 2})
    assert (done.next_target, done.next_tag) == (None, None)
