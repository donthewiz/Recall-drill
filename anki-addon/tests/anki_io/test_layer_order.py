"""Deck order follows the skill's layers (v0.3.1): new cards by (layer, queue
position, nid, ord); a deck without ``Layer::`` tags is ordered exactly as before."""

from __future__ import annotations

import random
from dataclasses import replace

from anki.cards import Card
from anki.collection import Collection
from anki.notes import NoteId
from anki_fixtures import add_note, deck

from recalldrill.anki_io.cards import CardSnapshot
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.select import (
    Candidate,
    Scope,
    SelectOptions,
    deck_order_key,
    order_candidates,
    select_cards,
)


def _basic(col: Collection, did: int, front: str, *tags: str) -> Card:
    return add_note(col, "Basic", did, {"Front": front, "Back": f"{front} a"}, tags).cards()[0]  # type: ignore[arg-type]


def _order(col: Collection, did: int, order: str = "deck_order", **kw: object) -> list[str]:
    options = SelectOptions(order=order, **kw)  # type: ignore[arg-type]
    sel = select_cards(col, Scope(deck_id=did), options, MappingTable(col))
    return [col.get_note(NoteId(c.snap.nid))["Front"] for c in sel.picked]


def test_a_late_layer_3_card_comes_before_the_layer_4_cards(col: Collection) -> None:
    did = int(deck(col, "Lab"))
    for ch in (1, 2):
        _basic(col, did, f"L1-c{ch}", "Layer::1")
    for ch in (1, 2):
        _basic(col, did, f"L2-c{ch}", "Layer::2")
    for ch in (1, 2):
        _basic(col, did, f"L4-c{ch}", "Layer::4")
    _basic(col, did, "L3-late", "Layer::3")  # added days later: end of the new queue
    assert _order(col, did) == ["L1-c1", "L1-c2", "L2-c1", "L2-c2", "L3-late", "L4-c1", "L4-c2"]


def test_within_a_layer_cards_keep_their_queue_position(col: Collection) -> None:
    did = int(deck(col, "Lab"))
    a = _basic(col, did, "a", "Layer::1")
    b = _basic(col, did, "b", "Layer::1")
    c = _basic(col, did, "c", "Layer::1")
    col.sched.reposition_new_cards(
        [c.id, a.id, b.id],
        starting_from=10,
        step_size=1,  # type: ignore[list-item]
        randomize=False,
        shift_existing=False,
    )
    assert _order(col, did) == ["c", "a", "b"]  # queue position, not note id


def test_layered_and_unlayered_cards_mix(col: Collection) -> None:
    did = int(deck(col, "Lab"))
    _basic(col, did, "none1")
    _basic(col, did, "L2", "Layer::2")
    _basic(col, did, "other-tag", "Chapter::7")
    _basic(col, did, "L1", "Layer::1")
    # No-layer cards after every numbered layer, in queue order.
    assert _order(col, did) == ["L1", "L2", "none1", "other-tag"]


def test_several_layer_tags_use_the_lowest_and_case_is_ignored(col: Collection) -> None:
    did = int(deck(col, "Lab"))
    _basic(col, did, "first", "layer::3")
    _basic(col, did, "multi", "Layer::4", "LAYER::2", "Layer::5")
    _basic(col, did, "last", "Layer::4")
    assert _order(col, did) == ["multi", "first", "last"]


def test_priority_first_sorts_layers_inside_each_class(col: Collection) -> None:
    did = int(deck(col, "Lab"))
    flagged_l2 = _basic(col, did, "flag-L2", "Layer::2")
    flagged_l1 = _basic(col, did, "flag-L1", "Layer::1")
    for card in (flagged_l1, flagged_l2):
        card.set_user_flag(1)
        col.update_card(card)
    _basic(col, did, "new-L2", "Layer::2")
    _basic(col, did, "new-L1", "Layer::1")
    _basic(col, did, "new-none")
    assert _order(col, did, "priority_first") == [
        "flag-L1",
        "flag-L2",
        "new-L1",
        "new-L2",
        "new-none",
    ]


def _snap(i: int, rng: random.Random, tags: tuple[str, ...]) -> CardSnapshot:
    return CardSnapshot(
        cid=i, nid=rng.randrange(1, 10_000), did=1, odid=0, ord=rng.randrange(3), ntid=1,
        type=rng.choice((0, 0, 2)), queue=0, ivl=0, due=rng.randrange(1, 50), lapses=0,
        reps=0, factor=0, flags=0, tags=tags, fsrs_d=None, fsrs_s=None,
    )  # fmt: skip


def _v030_key(s: CardSnapshot) -> tuple[int, int, int, int]:
    """The v0.3.0 deck-order key, kept here as the reference."""
    if s.type == 0:
        return (0, s.new_position, s.nid, s.ord)
    return (1, 0, s.nid, s.ord)


def test_a_deck_without_layer_tags_sorts_exactly_as_before() -> None:
    rng = random.Random(7)
    plain = ((), ("Chapter::1",), ("rd::drill::A",), ("APLab::Ch7::LongBone",))
    snaps = [_snap(i, rng, rng.choice(plain)) for i in range(400)]
    cands = [Candidate(s, "new", None, "a") for s in snaps]  # type: ignore[arg-type]
    for mode in ("deck_order", "priority_first"):
        got = [c.snap.cid for c in order_candidates(cands, mode)]  # type: ignore[arg-type]
        want = sorted(snaps, key=_v030_key)  # one class: the same order
        assert got == [s.cid for s in want]
    # The relative order of every pair of cards is the old key's.
    keys = [deck_order_key(s) for s in snaps]
    assert [k for _, k in sorted(zip(map(_v030_key, snaps), keys, strict=True))] == sorted(keys)


def test_non_new_cards_keep_their_key() -> None:
    s = _snap(1, random.Random(1), ("Layer::1",))
    review = replace(s, type=2)
    assert deck_order_key(review)[:3] == (1, 0, 0)
    assert deck_order_key(replace(s, tags=()))[0] == 0
