"""anki_io/select.py: scope, eligibility, counts, order, template filter, siblings."""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from anki.cards import Card
from anki.collection import Collection
from anki.decks import DeckId
from anki.notes import Note
from anki_fixtures import (
    AMC,
    BQE,
    add_amc_models,
    add_bqe_model,
    add_bqe_note,
    add_io_note,
    add_note,
    cards_by_ord,
    deck,
    model,
)

from recalldrill.anki_io.cards import CARD_CLASSES
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.select import (
    Scope,
    Selection,
    SelectOptions,
    apply_holdout,
    select_cards,
)


def set_state(col: Collection, card: Card, **kw: int) -> None:
    card.load()
    for k, v in kw.items():
        setattr(card, k, v)
    col.update_card(card)


def basic(
    col: Collection, did: DeckId, front: str, back: str = "ans", tags: tuple[str, ...] = ()
) -> Card:
    return add_note(col, "Basic", did, {"Front": front, "Back": back}, tags).cards()[0]


def select(col: Collection, scope: Scope, **kw: object) -> Selection:
    return select_cards(col, scope, SelectOptions(**kw), MappingTable(col))  # type: ignore[arg-type]


def fronts(col: Collection, sel: Selection) -> list[str]:
    out: list[str] = []
    for c in sel.picked:
        note = col.get_note(c.snap.nid)  # type: ignore[arg-type]
        out.append(note.fields[0] + ("" if c.snap.ord == 0 else f"/{c.snap.ord}"))
    return out


@dataclass
class Mixed:
    top: DeckId
    cards: dict[str, Card]


@pytest.fixture
def mixed(col: Collection) -> Mixed:
    """One card per class, plus one per ineligible reason, under Top (and a subdeck)."""
    top, sub = deck(col, "Top"), deck(col, "Top::Sub")
    c: dict[str, Card] = {}
    for name in ("new1", "new2"):
        c[name] = basic(col, sub if name == "new2" else top, name)
    c["suspended_new"] = basic(col, top, "suspended_new")
    c["young"] = basic(col, top, "young")
    c["mature"] = basic(col, top, "mature")
    c["lapsed"] = basic(col, top, "lapsed")
    c["learning"] = basic(col, top, "learning")
    c["flagged"] = basic(col, top, "flagged")
    c["leech"] = basic(col, top, "leech", tags=("leech",))
    c["suspended_review"] = basic(col, top, "suspended_review")
    c["buried"] = basic(col, top, "buried")
    c["filtered"] = basic(col, sub, "filtered")
    c["empty"] = basic(col, top, "empty", back="<img src=x.jpg>")
    c["io"] = add_io_note(col, top).cards()[0]
    mm = col.models
    m = mm.new("No answer side")
    mm.add_field(m, mm.new_field("F"))
    t = mm.new_template("Card 1")
    t["qfmt"] = t["afmt"] = "{{F}}"
    mm.add_template(m, t)
    mm.add(m)
    c["unmapped"] = add_note(col, "No answer side", top, {"F": "unmapped"}).cards()[0]
    basic(col, deck(col, "Elsewhere"), "outside scope")

    review = {"type": 2, "queue": 2, "due": 100, "reps": 3}
    set_state(col, c["young"], **review, ivl=5)
    set_state(col, c["mature"], **review, ivl=60)
    set_state(col, c["lapsed"], **review, ivl=3, lapses=2)
    set_state(col, c["learning"], type=1, queue=1, due=0)
    set_state(col, c["flagged"], **review, ivl=200)
    set_state(col, c["leech"], **review, ivl=2, lapses=8)
    set_state(col, c["suspended_review"], **review, ivl=10)
    col.sched.suspend_cards([c["suspended_new"].id, c["suspended_review"].id, c["leech"].id])
    col.set_user_flag_for_cards(1, [c["flagged"].id])
    col.sched.bury_cards([c["buried"].id], manual=True)
    fid = col.decks.new_filtered("Filtered")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [['"deck:Top::Sub" Front:filtered', 10, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    return Mixed(top, c)


def test_counts_by_class_and_reason(col: Collection, mixed: Mixed) -> None:
    sel = select(col, Scope(deck_id=mixed.top))
    assert sel.total == 15  # subdeck and filtered-away card included; "Elsewhere" not
    assert {k: v for k, v in sel.eligible_counts.items() if v} == {
        "flagged": 1, "leech": 1, "suspended_new": 1, "suspended_review": 1, "lapsed": 1,
        "learning": 1, "new": 2, "young": 1, "mature": 1,
    }  # fmt: skip
    assert {k: v for k, v in sel.picked_counts.items() if v} == {
        "flagged": 1, "leech": 1, "suspended_new": 1, "lapsed": 1, "new": 2, "young": 1,
    }  # fmt: skip
    assert sel.ineligible == {
        "image_occlusion": 1, "marked_ineligible": 0, "unmapped": 1, "empty_answer": 1,
        "filtered_deck": 1, "buried": 1,
    }  # fmt: skip
    assert sel.template_excluded == 0
    assert set(sel.eligible_counts) == set(CARD_CLASSES)
    kinds = {(m.notetype_name, m.kind) for m in sel.mappings.values()}
    assert kinds == {
        ("Basic", "standard"),
        ("Image Occlusion", "image_occlusion"),
        ("No answer side", "standard"),
    }


def test_priority_first_order(col: Collection, mixed: Mixed) -> None:
    sel = select(col, Scope(deck_id=mixed.top))
    assert [c.card_class for c in sel.picked] == [
        "flagged", "leech", "lapsed", "suspended_new", "new", "new", "young",
    ]  # fmt: skip
    assert fronts(col, sel)[4:6] == ["new1", "new2"]
    assert [c.answer for c in sel.picked] == ["ans"] * 7


def test_deck_order(col: Collection, mixed: Mixed) -> None:
    sel = select(col, Scope(deck_id=mixed.top), order="deck_order")
    # New cards (suspended or not) by queue position, then the rest by note id.
    assert fronts(col, sel) == [
        "new1",
        "new2",
        "suspended_new",
        "young",
        "lapsed",
        "flagged",
        "leech",
    ]


def test_enabling_buried_and_filtered_makes_them_eligible(col: Collection, mixed: Mixed) -> None:
    from recalldrill.anki_io.cards import DEFAULT_ENABLED

    enabled = DEFAULT_ENABLED | {"buried", "in_filtered_deck", "mature"}
    sel = select(col, Scope(deck_id=mixed.top), enabled=enabled)
    assert sel.ineligible["buried"] == sel.ineligible["filtered_deck"] == 0
    assert sel.picked_counts["buried"] == sel.picked_counts["in_filtered_deck"] == 1
    assert [c.card_class for c in sel.picked][-3:] == ["mature", "in_filtered_deck", "buried"]


def test_max_cards_keeps_priority_and_eligible_counts(col: Collection, mixed: Mixed) -> None:
    sel = select(col, Scope(deck_id=mixed.top), max_cards=3)
    assert [c.card_class for c in sel.picked] == ["flagged", "leech", "lapsed"]
    assert sel.picked_counts["new"] == 0 and sel.eligible_counts["new"] == 2
    assert select(col, Scope(deck_id=mixed.top), max_cards=0).picked == []


def test_apply_holdout_is_a_no_op(col: Collection, mixed: Mixed) -> None:
    sel = select(col, Scope(deck_id=mixed.top))
    assert apply_holdout(sel) is sel


# ---------------------------------------------------------------------------
# New-queue order, templates, siblings
# ---------------------------------------------------------------------------


def _layered(col: Collection) -> tuple[DeckId, list[Note]]:
    """Notes created out of layer order, then repositioned Layer::1 -> 3, the way
    the anki-cards skill lays out new cards."""
    add_amc_models(col)
    did = deck(col, "Human A&P::Lecture 2::Bones")
    notes: list[Note] = []
    for layer, text in [(3, "{{c1::c}}"), (1, "{{c1::a}} {{c2::a2}}"), (2, "{{c1::b}}")]:
        notes.append(add_note(col, AMC, did, {"Text": text}, (f"Layer::{layer}", "rd::drill::A")))
    by_layer = sorted(notes, key=lambda n: n.tags)
    cids = [c.id for n in by_layer for c in cards_by_ord(n)]
    col.sched.reposition_new_cards(
        cids, starting_from=0, step_size=1, randomize=False, shift_existing=False
    )
    return did, notes


def test_new_cards_follow_the_new_queue_not_note_id(col: Collection) -> None:
    did, _ = _layered(col)
    for order in ("priority_first", "deck_order"):
        sel = select(col, Scope(deck_id=did), order=order)
        texts = [col.get_note(c.snap.nid)["Text"] for c in sel.picked]  # type: ignore[arg-type]
        assert [t[:9] for t in texts] == ["{{c1::a}}", "{{c1::a}}", "{{c1::b}}", "{{c1::c}}"]
        assert [c.answer for c in sel.picked] == ["a", "a2", "b", "c"]


def test_template_filter_and_sibling_warning(col: Collection) -> None:
    add_bqe_model(col)
    did = deck(col, "Medical Terminology::Ch 1")
    for term, meaning in [
        ("ankyl/o", "crooked, bent, stiff"),
        ("-algia", "pain"),
        ("-dynia", "pain"),
    ]:
        add_bqe_note(col, did, term, meaning)
    add_bqe_note(col, did, "one-way", "no reverse", reverse=False)
    col.sched.suspend_cards(col.find_cards(f"did:{did}"))
    ntid = int(model(col, BQE)["id"])
    scope = Scope(deck_id=deck(col, "Medical Terminology"))

    both = select(col, scope)
    assert len(both.picked) == 7
    assert (both.sibling_cards, both.sibling_notes) == (6, 3)
    assert {c.card_class for c in both.picked} == {"suspended_new"}

    reverse = select(col, scope, card_ords={ntid: frozenset({1})})
    assert [c.snap.ord for c in reverse.picked] == [1, 1, 1]
    assert [c.answer for c in reverse.picked] == ["ankyl/o", "-algia", "-dynia"]
    assert reverse.template_excluded == 4
    assert (reverse.sibling_cards, reverse.sibling_notes) == (0, 0)
    # Other note types are not filtered by a BQE-only setting.
    basic(col, did, "basic")
    assert len(select(col, scope, card_ords={ntid: frozenset({1})}).picked) == 4


def test_exclude_cids_leaves_cards_out_whatever_their_class(col: Collection) -> None:
    """The "my rd::hard cards" entry: a hard card's cloze sibling shares the
    note tag, and the template filter can't tell cloze cards apart."""
    did = deck(col, "X")
    note = add_note(col, "Cloze", did, {"Text": "{{c1::alpha}} and {{c2::beta}}"}, ["rd::hard"])
    c1, c2 = sorted(note.cards(), key=lambda c: c.ord)
    scope = Scope(search="tag:rd::hard")
    assert [c.snap.cid for c in select(col, scope).picked] == [c1.id, c2.id]
    sel = select(col, scope, exclude_cids=frozenset({c2.id, 999}))
    assert [c.snap.cid for c in sel.picked] == [c1.id]
    assert sel.excluded == 1 and sum(sel.eligible_counts.values()) == 1


# ---------------------------------------------------------------------------
# Scope and tags
# ---------------------------------------------------------------------------


def test_scope_needs_one_of_deck_or_search() -> None:
    with pytest.raises(ValueError):
        Scope()
    with pytest.raises(ValueError):
        Scope(deck_id=1, search="x")


def test_deck_names_are_escaped(col: Collection) -> None:
    basic(col, deck(col, "A_b"), "underscore")
    basic(col, deck(col, "Axb"), "wildcard would match")
    basic(col, deck(col, 'Q "quoted" *'), "quoted")
    sel = select(col, Scope(deck_id=deck(col, "A_b")))
    assert fronts(col, sel) == ["underscore"]
    sel = select(col, Scope(deck_id=deck(col, 'Q "quoted" *')))
    assert fronts(col, sel) == ["quoted"]


def test_extra_tag_is_exact(col: Collection) -> None:
    did = deck(col, "X")
    for tag in ("rd::drill::A", "rd::drill::A1", "rd::drill::B", "rd::drill::A::sub"):
        basic(col, did, tag, tags=(tag,))
    sel = select(col, Scope(deck_id=did), extra_tag="rd::drill::A")
    # A tag matches itself and its children, never a prefix (A1).
    assert sorted(fronts(col, sel)) == ["rd::drill::A", "rd::drill::A::sub"]


def test_search_scope_is_grouped_before_the_tag(col: Collection) -> None:
    did = deck(col, "X")
    basic(col, did, "one", tags=("t1",))
    basic(col, did, "two", tags=("t2", "keep"))
    basic(col, did, "three", tags=("t3", "keep"))
    scope = Scope(search="tag:t1 or tag:t2")
    assert sorted(fronts(col, select(col, scope))) == ["one", "two"]
    assert fronts(col, select(col, scope, extra_tag="keep")) == ["two"]
    assert "keep" in scope.to_search(col, "keep") and scope.deck_name(col) is None


def test_io_marker_rules_out_single_cloze_notes_only(col: Collection) -> None:
    did = deck(col, "X")
    io_text = "{{c1::image-occlusion:rect:left=.1:top=.1:width=.2:height=.2}}"
    add_note(col, "Cloze", did, {"Text": io_text})
    add_note(col, "Cloze", did, {"Text": "The {{c1::femur}} is a bone."})
    sel = select(col, Scope(deck_id=did))
    assert sel.ineligible["image_occlusion"] == 1
    assert [c.answer for c in sel.picked] == ["femur"]
    assert {m.kind for m in sel.mappings.values()} == {"cloze"}
