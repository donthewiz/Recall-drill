"""Layer progress (v0.3.1) on a scratch deck shaped like the anki-cards skill's."""

from __future__ import annotations

from pathlib import Path

from anki.collection import Collection
from anki_fixtures import add_note, deck
from layer_scene import CHAPTERS, build

from recalldrill.anki_io.sections import read_progress
from recalldrill.sections import render_progress
from recalldrill.storage import Storage


def _storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def test_rows_are_layers_with_a_column_per_chapter(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    scene = build(col, st)
    p = read_progress(col, st, scene.lab)
    assert p.by_layer
    assert [r.label for r in p.rows] == ["Layer 1", "Layer 2", "Layer 3", "Layer 4"]
    # Chapter columns follow the order the cards were made, not the deck tree's.
    assert [c.label for c in p.chapters] == list(CHAPTERS)
    l1, l2, l3, l4 = p.rows
    # Layer 1: 8 drillable + 2 image occlusion; 2 drilled.
    assert (l1.cards, l1.drilled, l1.cant_drill, l1.open, l1.held) == (10, 2, 2, 6, 0)
    assert l1.new == 8 and l1.to_go == 6 and l1.status == "6 to go" and not l1.done
    # done/total per chapter: Muscles + Bones are drilled (1 of 2 each); IO cards aren't counted.
    assert l1.chapters == ((1, 2), (1, 2), (0, 2), (0, 2))
    assert l3.cards == 1 and l3.chapters == ((0, 0), (0, 0), (0, 1), (0, 0))
    assert l2.chapters == ((0, 2),) * 4 and l4.chapters == ((0, 2),) * 4


def test_image_occlusion_cards_are_cant_drill_and_never_block_done(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    scene = build(col, st)
    # Release every drillable Layer 1 card undrilled: only the IO cards remain.
    for name, card in scene.cards.items():
        if name.startswith("L1-"):
            note = card.note()
            note.add_tag("rd::undrilled")
            col.update_note(note)
    l1 = read_progress(col, st, scene.lab).rows[0]
    assert l1.cant_drill == 2 and l1.to_go == 0 and l1.done and l1.status == "done"
    assert l1.chapters == ((2, 2), (2, 2), (2, 2), (2, 2))


def test_next_is_the_first_unfinished_layer(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    scene = build(col, st)
    p = read_progress(col, st, scene.lab)
    assert p.next_index == 0 and p.next_row is not None and p.next_row.label == "Layer 1"
    assert p.next_target == scene.lab  # layers drill from the chosen deck, in Deck order
    # Finish Layer 1 and Layer 2: Next moves on to Layer 3, the late card.
    for name, card in scene.cards.items():
        if name.startswith(("L1-", "L2-")):
            note = card.note()
            note.add_tag("rd::undrilled")
            col.update_note(note)
    p = read_progress(col, st, scene.lab)
    assert [r.done for r in p.rows] == [True, True, False, False]
    assert p.next_index == 2 and p.next_row is not None and p.next_row.label == "Layer 3"
    text = render_progress(p).splitlines()
    assert text[0].split()[0] == "Layer" and text[0].endswith("Next")
    assert [line.endswith("Next") for line in text[1:]] == [False, False, True, False]


def test_a_layer_less_card_gets_a_no_layer_row_last(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    scene = build(col, st)
    add_note(col, "Basic", deck(col, "AP Lab::Lab 2::Bones"), {"Front": "x", "Back": "y"})  # type: ignore[arg-type]
    p = read_progress(col, st, scene.lab)
    assert [r.label for r in p.rows][-1] == "No layer"
    assert p.rows[-1].layer is None and p.rows[-1].open == 1


def test_the_progress_table_as_text(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    scene = build(col, st)
    text = render_progress(read_progress(col, st, scene.lab))
    print(text)
    head, first, *_ = text.splitlines()
    assert head.split("  ")[0] == "Layer"
    assert "Can't drill" in head and all(c in head for c in CHAPTERS)
    assert first.rstrip().endswith("Next") and "6 to go" in first


def test_without_layer_tags_rows_are_subdecks_in_the_order_cards_were_made(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Course"))
    # Alphabetical order (Alpha, Beta, Gamma) differs from creation order.
    names = ("Gamma", "Alpha", "Beta")
    dids = {n: int(deck(col, f"Course::{n}")) for n in sorted(names)}
    for n in names:
        add_note(col, "Basic", dids[n], {"Front": n, "Back": "a"})  # type: ignore[arg-type]
    p = read_progress(col, st, lab)
    assert not p.by_layer
    assert [r.label for r in p.rows] == ["Gamma", "Alpha", "Beta"]
    assert p.next_row is not None and p.next_row.label == "Gamma"
    assert p.next_target == dids["Gamma"]  # subdeck rows drill that subdeck
    assert "Layer" not in render_progress(p).splitlines()[0]
