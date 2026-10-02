"""Phase 5 holdout on a scratch collection: who is held out (select.py), how
the holdout group is handed off (handoff.py), and that later selections leave
``rd::holdout`` cards out."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401
import pytest
from anki.cards import Card, CardId
from anki.collection import Collection
from anki.consts import (
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SUSPENDED,
)
from anki.decks import DeckId
from anki_fixtures import add_bqe_model, add_bqe_note, add_note, cards_by_ord, deck

from recalldrill.anki_io.handoff import (
    TAG_DRILLED,
    HandoffSettings,
    apply_handoff,
    describe,
    handoff_line,
    plan_handoff,
)
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.panel import holdout_refs
from recalldrill.anki_io.select import (
    Scope,
    Selection,
    SelectOptions,
    select_cards,
)
from recalldrill.holdout import TAG_HOLDOUT, is_holdout
from recalldrill.sources import SourceRef, source_to_json

SALT = "0123456789abcdef"
B = HandoffSettings(mode="B")
A = HandoffSettings(mode="A")


def basic(col: Collection, did: DeckId, front: str, tags: Sequence[str] = ()) -> Card:
    return add_note(col, "Basic", did, {"Front": front, "Back": f"ans {front}"}, tags).cards()[0]


def select(col: Collection, scope: Scope, **kw: Any) -> Selection:
    kw.setdefault("holdout_salt", SALT)
    return select_cards(col, scope, SelectOptions(**kw), MappingTable(col))


def suspended_deck(
    col: Collection, n: int, name: str = "Med Term::Ch 1"
) -> tuple[DeckId, list[Card]]:
    did = deck(col, name)
    cards = [basic(col, did, f"term {i}") for i in range(n)]
    col.sched.suspend_cards([c.id for c in cards])
    return did, cards


def tags_of(col: Collection, card: Card) -> set[str]:
    return {t.casefold() for t in col.get_note(card.nid).tags}


# ---------------------------------------------------------------------------
# Selection
# ---------------------------------------------------------------------------


def test_holdout_partitions_eligible_new_cards_by_the_hash(col: Collection) -> None:
    did, cards = suspended_deck(col, 40)
    sel = select(col, Scope(deck_id=did), holdout_pct=30)
    held = {c.snap.cid for c in sel.holdout}
    picked = {c.snap.cid for c in sel.picked}
    assert held == {c.id for c in cards if is_holdout(SALT, c.id, 30)}
    assert held and picked and held.isdisjoint(picked)
    assert held | picked == {c.id for c in cards}
    assert sel.eligible_counts["suspended_new"] == 40  # eligibility counts are unchanged
    assert sel.picked_counts["suspended_new"] == len(picked)
    # Stable: the same cards every time.
    again = select(col, Scope(deck_id=did), holdout_pct=30)
    assert {c.snap.cid for c in again.holdout} == held


def test_max_cards_counts_drill_cards_only(col: Collection) -> None:
    did, cards = suspended_deck(col, 40)
    sel = select(col, Scope(deck_id=did), holdout_pct=30, max_cards=6)
    assert len(sel.picked) == 6
    order = [int(c.id) for c in cards]  # new-queue order is creation order here
    last = order.index(sel.picked[-1].snap.cid)
    walked = order[: last + 1]
    assert [c.snap.cid for c in sel.picked] == [c for c in walked if not is_holdout(SALT, c, 30)]
    assert [c.snap.cid for c in sel.holdout] == [c for c in walked if is_holdout(SALT, c, 30)]


def test_no_holdout_for_searches_or_scheduled_cards(col: Collection) -> None:
    did, cards = suspended_deck(col, 30)
    assert select(col, Scope(search="deck:Med*"), holdout_pct=30).holdout == []
    assert select(col, Scope(deck_id=did), holdout_pct=0).holdout == []
    assert select(col, Scope(deck_id=did), holdout_pct=30, holdout_salt="").holdout == []
    # A review card in the hash's share is drilled, not held out.
    review = next(c for c in cards if is_holdout(SALT, c.id, 30))
    review.load()
    review.type, review.queue = CARD_TYPE_REV, QUEUE_TYPE_REV
    review.ivl, review.due = 5, col.sched.today + 3
    col.update_card(review)
    sel = select(col, Scope(deck_id=did), holdout_pct=30)
    assert review.id in {c.snap.cid for c in sel.picked}
    assert review.id not in {c.snap.cid for c in sel.holdout}


def test_drilled_notes_and_siblings_of_drill_cards_are_not_held_out(col: Collection) -> None:
    add_bqe_model(col)
    did = deck(col, "Med Term::Ch 2")
    # A two-card note: find one whose cards fall on both sides of the hash.
    for i in range(200):
        note = add_bqe_note(col, did, f"t{i}", f"m{i}")
        normal, reverse = cards_by_ord(note)
        if is_holdout(SALT, normal.id, 50) != is_holdout(SALT, reverse.id, 50):
            break
    else:
        pytest.fail("no split note")
    col.sched.suspend_cards([normal.id, reverse.id])
    scope = Scope(deck_id=did)
    sel = select(col, scope, holdout_pct=50, card_ords={})
    split = {normal.id, reverse.id}
    assert split & {c.snap.cid for c in sel.picked}
    assert not split & {c.snap.cid for c in sel.holdout}  # its sibling is drilled
    # A note already drilled (rd::drilled) is never a control.
    lone = next(
        c
        for c in (basic(col, did, f"lone {i}", [TAG_DRILLED]) for i in range(100))
        if is_holdout(SALT, c.id, 50)
    )
    sel = select(col, scope, holdout_pct=50)
    assert lone.id in {c.snap.cid for c in sel.picked}


def test_holdout_tag_is_left_out_by_default(col: Collection) -> None:
    did, cards = suspended_deck(col, 4)
    col.tags.bulk_add([cards[0].nid], TAG_HOLDOUT)
    sel = select(col, Scope(deck_id=did), exclude_holdout_tag=True)
    assert sel.holdout_tagged == 1 and cards[0].id not in {c.snap.cid for c in sel.picked}
    # Setting off: drillable again, and never held out twice.
    sel = select(col, Scope(deck_id=did), holdout_pct=50)
    assert sel.holdout_tagged == 0
    assert cards[0].id not in {c.snap.cid for c in sel.holdout}


# ---------------------------------------------------------------------------
# Handoff
# ---------------------------------------------------------------------------


def saved(drilled: Sequence[Card], holdout: Sequence[dict[str, Any]]) -> dict[str, Any]:
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for i, c in enumerate(drilled):
        items.append(
            {
                "id": i,
                "front": f"f{i}",
                "back": "b",
                "status": "mastered",
                "chunks": None,
                "finalDone": True,
                "misses": 0,
                "reveals": 0,
                "finalMisses": 0,
            }  # fmt: skip
        )
        sources.append(
            source_to_json(
                SourceRef(
                    cid=c.id,
                    nid=c.nid,
                    ord=c.ord,
                    did=c.did,
                    ntid=0,
                    card_class="suspended_new",
                    flags=0,
                    front_html="",
                    extra_html="",
                    answer_hash="",
                    has_audio=False,
                    answer_html="",
                    css="",
                    image_front=False,
                )  # fmt: skip
            )
        )
    return {
        "items": items,
        "addon": {
            "sessionId": "s1",
            "sources": sources,
            "scope": {"deckId": drilled[0].did, "search": None},
            "handoffPending": True,
            "holdout": list(holdout),
        },
    }


def split_selection(col: Collection, n: int = 30) -> tuple[DeckId, Selection]:
    """Suspended new cards, some held out, and three plain new cards behind them
    in the new queue (not picked: only suspended_new is on)."""
    did, _ = suspended_deck(col, n)
    for i in range(3):
        basic(col, did, f"other {i}")
    sel = select(col, Scope(deck_id=did), holdout_pct=30, enabled=frozenset({"suspended_new"}))
    assert sel.holdout and len(sel.picked) + len(sel.holdout) == n
    return did, sel


@pytest.mark.parametrize("settings", [pytest.param(B, id="B"), pytest.param(A, id="A")])
def test_holdout_group_is_unsuspended_queued_after_the_drilled_cards_and_buried(
    col: Collection, settings: HandoffSettings
) -> None:
    _, sel = split_selection(col)
    drilled = [col.get_card(CardId(c.snap.cid)) for c in sel.picked]
    refs = holdout_refs(sel)
    held = [r["cid"] for r in refs]
    assert {r["card_class"] for r in refs} == {"suspended_new"}
    plan = plan_handoff(col, saved(drilled, refs), settings)
    assert plan.holdout == tuple(held) and plan.holdout_skipped == ()
    assert plan.cards == len(drilled)  # holdout cards aren't "handed off drilled cards"
    assert set(held) <= set(plan.unsuspend) and set(held) <= set(plan.bury)
    assert plan.tag_add[TAG_HOLDOUT] == tuple(col.get_card(CardId(c)).nid for c in held)
    text = describe(plan, None, datetime(2026, 10, 3, 4))
    assert any(line.startswith(f"Holdout: {len(held)} card") for line in text.lines)
    apply_handoff(col, plan)

    n_front = len(drilled) if settings.mode == "B" else 0
    for pos, cid in enumerate(held):
        card = col.get_card(CardId(cid))
        assert (card.type, card.queue) == (CARD_TYPE_NEW, QUEUE_TYPE_MANUALLY_BURIED)
        assert card.due == n_front + pos  # right after the drilled cards
        assert TAG_HOLDOUT in tags_of(col, card) and TAG_DRILLED not in tags_of(col, card)
    for d in drilled:
        d.load()
        assert TAG_HOLDOUT not in tags_of(col, d)
    # Planning again plans nothing.
    assert not plan_handoff(col, saved(drilled, refs), settings).has_changes
    line = handoff_line(plan, None, 0)
    assert line["groups"]["holdout"] == held and line["groups"]["holdout_siblings"] == []


def test_holdout_siblings_follow_the_siblings_rule(col: Collection) -> None:
    add_bqe_model(col)
    did = deck(col, "Med Term::Ch 3")
    drilled_note = add_bqe_note(col, did, "drilled", "d")
    held_note = add_bqe_note(col, did, "held", "h")
    col.sched.suspend_cards(col.find_cards(f"did:{did}"))
    d_normal, d_reverse = cards_by_ord(drilled_note)
    h_normal, h_reverse = cards_by_ord(held_note)
    ref = {"cid": h_reverse.id, "nid": h_reverse.nid, "ord": 1, "did": did,
           "card_class": "suspended_new"}  # fmt: skip
    plan = plan_handoff(col, saved([d_reverse], [ref]), B)
    assert plan.siblings == (d_normal.id,)
    assert plan.holdout == (h_reverse.id,) and plan.holdout_siblings == (h_normal.id,)
    apply_handoff(col, plan)
    order = [d_reverse, d_normal, h_reverse, h_normal]
    for pos, c in enumerate(order):
        c.load()
        assert (c.type, c.queue, c.due) == (CARD_TYPE_NEW, QUEUE_TYPE_MANUALLY_BURIED, pos)
    # Siblings off: the holdout card alone.
    col.undo()
    plan = plan_handoff(col, saved([d_reverse], [ref]), HandoffSettings(siblings=False))
    assert plan.siblings == () and plan.holdout_siblings == ()


def test_holdout_cards_studied_since_or_gone_are_skipped(col: Collection) -> None:
    _, sel = split_selection(col)
    drilled = [col.get_card(CardId(c.snap.cid)) for c in sel.picked]
    refs = holdout_refs(sel)
    studied = col.get_card(CardId(refs[0]["cid"]))
    studied.type, studied.queue, studied.ivl = CARD_TYPE_REV, QUEUE_TYPE_REV, 3
    col.update_card(studied)
    refs = [*refs, {"cid": 999_999, "nid": 1, "ord": 0, "did": 1, "card_class": "new"}]
    plan = plan_handoff(col, saved(drilled, refs), B)
    assert studied.id not in plan.holdout and studied.id in plan.holdout_skipped
    assert 999_999 in plan.holdout_skipped


def test_after_the_handoff_the_control_stays_out_of_selections(col: Collection) -> None:
    did, sel = split_selection(col)
    drilled = [col.get_card(CardId(c.snap.cid)) for c in sel.picked]
    refs = holdout_refs(sel)
    apply_handoff(col, plan_handoff(col, saved(drilled, refs), B))
    held = {r["cid"] for r in refs}
    for c in held:
        assert col.get_card(CardId(c)).queue in (QUEUE_TYPE_MANUALLY_BURIED, QUEUE_TYPE_NEW)
    col.sched.unbury_deck(did)
    nxt = select(col, Scope(deck_id=did), holdout_pct=30, exclude_holdout_tag=True)
    picked = {c.snap.cid for c in nxt.picked} | {c.snap.cid for c in nxt.holdout}
    assert not held & picked
    assert nxt.holdout_tagged == len(held)
    assert all(col.get_card(CardId(c)).queue != QUEUE_TYPE_SUSPENDED for c in held)
