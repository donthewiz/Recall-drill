"""Hold back (v0.3), the third collection write, on scratch collections: planning
and apply/undo, rd::held added at hold-back and removed at handoff and release,
the waiting search covering held cards, and the panel's view of the setting."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import timedelta
from pathlib import Path
from typing import Any

import pytest
from anki.cards import Card
from anki.collection import Collection
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki_fixtures import add_bqe_model, add_bqe_note, add_note, deck

from recalldrill import deck_settings, history_store, pacing
from recalldrill.addon_config import DEFAULT_CONFIG
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.handoff import HandoffSettings, apply_handoff, plan_handoff
from recalldrill.anki_io.holdback import (
    HoldBackFailed,
    apply_hold_back,
    failure_text,
    held_cards,
    hold_back_state,
    plan_hold_back,
)
from recalldrill.anki_io.panel import options_for, read_panel
from recalldrill.anki_io.release import apply_release, plan_release
from recalldrill.anki_io.select import Scope
from recalldrill.anki_io.waiting import read_waiting, read_waiting_cards, waiting_search
from recalldrill.holdback import TAG_HELD, UNDO_LABEL
from recalldrill.measure import anki_day
from recalldrill.sources import SourceRef, source_to_json
from recalldrill.storage import Storage

DAY_MS = 86_400_000


def _storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def _basic(col: Collection, did: int, front: str, tags: tuple[str, ...] = ()) -> Card:
    note = add_note(col, "Basic", did, {"Front": front, "Back": f"{front} a"}, tags)  # type: ignore[arg-type]
    return note.cards()[0]


def _tags(col: Collection, card: Card) -> set[str]:
    return {t.casefold() for t in col.get_note(card.nid).tags}


def _scene(col: Collection, tmp_path: Path) -> dict[str, Card]:
    """Course::Bones and Course::Joints with one card of every state, plus a card
    outside the course."""
    st = _storage(tmp_path)
    bones = int(deck(col, "Course::Bones"))
    joints = int(deck(col, "Course::Joints"))
    other = int(deck(col, "Other"))
    c = {
        "new1": _basic(col, bones, "new1"),
        "new2": _basic(col, joints, "new2"),
        "tagged": _basic(col, joints, "tagged", ("rd::drill::A",)),
        "rated": _basic(col, bones, "rated"),
        "buried": _basic(col, bones, "buried"),
        "suspended": _basic(col, bones, "suspended"),
        "filtered": _basic(col, bones, "filtered"),
        "handed": _basic(col, joints, "handed"),
        "outside": _basic(col, other, "outside"),
    }
    # Introduced by Anki: a review card.
    rated = c["rated"]
    rated.type, rated.queue = CARD_TYPE_REV, QUEUE_TYPE_REV
    rated.ivl, rated.due = 5, 100
    col.update_card(c["rated"])
    col.sched.bury_cards([c["buried"].id], manual=True)  # type: ignore[list-item]
    col.sched.suspend_cards([c["suspended"].id])  # type: ignore[list-item]
    fid = col.decks.new_filtered("Cram")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [[f"cid:{c['filtered'].id}", 100, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    # A handoff sent "handed" to Anki a minute ago; nothing has rated it since.
    now = time.time()
    history_store.append_handoff(
        st,
        str(joints),
        {
            "type": "handoff",
            "sessionId": "s1",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(now - 60)),
            "groups": {"drilled_new": [c["handed"].id]},
            "cards": [{"cid": c["handed"].id, "nid": c["handed"].nid, "ord": 0}],
        },
    )
    for card in c.values():
        card.load()
    return c


def test_planning_suspends_only_new_unsuspended_unburied_undrilled_cards(
    col: Collection, tmp_path: Path
) -> None:
    c = _scene(col, tmp_path)
    st = _storage(tmp_path)
    course = int(deck(col, "Course"))
    plan = plan_hold_back(col, st, course)
    assert set(plan.suspend) == {c["new1"].id, c["new2"].id, c["tagged"].id}
    assert plan.handed_off == 1  # waiting for its first Anki rating
    assert plan.in_filtered == 1
    assert set(plan.tag_notes) == {c[k].nid for k in ("new1", "new2", "tagged")}
    assert plan.deck == "Course" and plan.has_changes
    # A subdeck is planned on its own: only its cards.
    joints = plan_hold_back(col, st, int(deck(col, "Course::Joints")))
    assert set(joints.suspend) == {c["new2"].id, c["tagged"].id}
    # Planning wrote nothing.
    for card in c.values():
        before = (card.queue, card.type)
        card.load()
        assert (card.queue, card.type) == before


def test_apply_tags_suspends_and_is_one_undo_step(col: Collection, tmp_path: Path) -> None:
    c = _scene(col, tmp_path)
    st = _storage(tmp_path)
    course = int(deck(col, "Course"))
    plan = plan_hold_back(col, st, course)
    positions = {k: c[k].due for k in ("new1", "new2", "tagged")}

    apply_hold_back(col, plan)

    for key in ("new1", "new2", "tagged"):
        c[key].load()
        assert c[key].queue == -1 and c[key].type == 0  # suspended, still new
        assert c[key].due == positions[key]  # queue position kept
        assert TAG_HELD in _tags(col, c[key])
    for key in ("rated", "buried", "suspended", "filtered", "handed", "outside"):
        before = (c[key].queue, c[key].type, c[key].odid)
        c[key].load()
        assert (c[key].queue, c[key].type, c[key].odid) == before
        assert TAG_HELD not in _tags(col, c[key])
    assert col.undo_status().undo == UNDO_LABEL
    # Planning again right after plans nothing.
    assert not plan_hold_back(col, st, course).has_changes
    assert sorted(held_cards(col, course)) == sorted(c[k].id for k in ("new1", "new2", "tagged"))

    col.undo()  # one step reverts the tags and the suspension
    for key in ("new1", "new2", "tagged"):
        c[key].load()
        assert c[key].queue == 0 and TAG_HELD not in _tags(col, c[key])


def test_a_failed_hold_back_is_rolled_back(
    col: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    c = _scene(col, tmp_path)
    plan = plan_hold_back(col, _storage(tmp_path), int(deck(col, "Course")))
    before = col.undo_status().undo

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(col.sched, "suspend_cards", boom)
    with pytest.raises(HoldBackFailed) as info:
        apply_hold_back(col, plan)
    assert info.value.rolled_back
    assert "nothing was changed" in failure_text(info.value)
    for key in ("new1", "new2", "tagged"):
        c[key].load()
        assert c[key].queue == 0 and TAG_HELD not in _tags(col, c[key])
    assert col.undo_status().undo == before


def test_the_setting_is_inherited_and_the_panel_reads_it(col: Collection, tmp_path: Path) -> None:
    c = _scene(col, tmp_path)
    st = _storage(tmp_path)
    course = int(deck(col, "Course"))
    joints = int(deck(col, "Course::Joints"))
    options = options_for(
        {}, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )

    def panel(did: int) -> Any:
        return read_panel(col, st, Scope(deck_id=did), options, {}, did, DEFAULT_CONFIG)

    off = panel(joints)
    assert (off.hold_back, off.hold_back_count, off.hold_back_from) == (False, 0, None)
    deck_settings.set_hold_back(st, course, True)
    assert hold_back_state(col, st, joints).on and hold_back_state(col, st, joints).did == course
    inherited = panel(joints)
    assert inherited.hold_back and inherited.hold_back_from == "Course"
    assert inherited.hold_back_count == 2  # new2 and tagged
    assert panel(course).hold_back_count == 3 and panel(course).hold_back_from is None
    # The subdeck opts out explicitly.
    deck_settings.set_hold_back(st, joints, False)
    assert not panel(joints).hold_back and panel(course).hold_back
    # Once held back, the button's N is 0.
    apply_hold_back(col, plan_hold_back(col, st, course))
    assert panel(course).hold_back_count == 0
    assert c["new1"].id in held_cards(col, course)


# -- rd::held leaves with the handoff and the release -------------------------------


def _bqe_session(col: Collection, did: int, n: int) -> tuple[list[Card], list[Card]]:
    add_bqe_model(col)
    fwd: list[Card] = []
    rev: list[Card] = []
    for i in range(n):
        note = add_bqe_note(col, did, f"term{i}", f"meaning {i}")  # type: ignore[arg-type]
        cards = sorted(note.cards(), key=lambda x: x.ord)
        fwd.append(cards[0])
        rev.append(cards[1])
    return fwd, rev


def _saved(cards: list[Card], holdout: list[Card] | None = None) -> dict[str, Any]:
    def ref(c: Card) -> dict[str, Any]:
        return source_to_json(
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
            )
        )

    items = [
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
        }
        for i, _ in enumerate(cards)
    ]
    return {
        "items": items,
        "addon": {
            "sessionId": "s1",
            "sources": [ref(c) for c in cards],
            "scope": {"deckId": None, "search": "x"},
            "handoffPending": True,
            "holdout": [{"cid": h.id, "nid": h.nid, "ord": h.ord} for h in holdout or []],
        },
    }


def test_the_handoff_removes_rd_held_from_drilled_and_holdout_notes(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Lab"))
    fwd, rev = _bqe_session(col, lab, 4)
    drilled, held_out = fwd[:2], fwd[2:3]
    untouched = fwd[3]
    apply_hold_back(col, plan_hold_back(col, st, lab))
    assert len(held_cards(col, lab)) == 8
    for card in (*fwd, *rev):
        assert TAG_HELD in _tags(col, card)

    plan = plan_handoff(col, _saved(drilled, held_out), HandoffSettings(mode="B"))
    assert set(plan.tag_remove[TAG_HELD]) == {c.nid for c in (*drilled, *held_out)}
    assert plan.tags_removed == 3  # rd::held on the two drilled notes and the holdout note
    apply_handoff(col, plan)
    for card in (*drilled, *held_out):
        assert TAG_HELD not in _tags(col, card)
    for card in (*rev[:3],):
        card.load()
        assert card.queue != -1  # the siblings went with them
    assert TAG_HELD in _tags(col, untouched)  # the undrilled note stays held
    card = untouched
    card.load()
    assert card.queue == -1
    col.undo()
    assert TAG_HELD in _tags(col, drilled[0])  # the same undo step puts the tag back


def test_a_note_keeps_rd_held_while_a_card_of_it_stays_held(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Lab"))
    fwd, rev = _bqe_session(col, lab, 1)
    apply_hold_back(col, plan_hold_back(col, st, lab))
    plan = plan_handoff(col, _saved(fwd), HandoffSettings(mode="B", siblings=False))
    assert plan.siblings == () and TAG_HELD not in plan.tag_remove  # the Reverse stays held
    apply_handoff(col, plan)
    assert TAG_HELD in _tags(col, fwd[0])
    rev[0].load()
    assert rev[0].queue == -1


def test_the_release_removes_rd_held(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Lab"))
    fwd, rev = _bqe_session(col, lab, 3)
    apply_hold_back(col, plan_hold_back(col, st, lab))
    cids = held_cards(col, lab)
    assert len(cids) == 6
    plan = plan_release(col, lab, [c.id for c in fwd[:2]])
    assert set(plan.untag_held) == {c.nid for c in fwd[:2]} and plan.has_changes
    apply_release(col, plan)
    for card in fwd[:2]:
        card.load()
        assert card.queue == 0 and TAG_HELD not in _tags(col, card)
    assert TAG_HELD in _tags(col, fwd[2])
    assert sorted(held_cards(col, lab)) == sorted([fwd[2].id, rev[2].id])
    line = __import__("recalldrill.anki_io.release", fromlist=["history_line"]).history_line(
        plan, 0
    )
    assert line["tags"]["removedByTag"] == {TAG_HELD: 2}


# -- the waiting search ------------------------------------------------------------------


def test_the_waiting_search_covers_held_cards_and_never_the_drilled_tags(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    did = int(deck(col, "Lab 2::Bones"))
    cids = {}
    for tag in ("rd::drill", "rd::held", "rd::drilled", "rd::undrilled", "rd::heldx", ""):
        cids[tag] = _basic(col, did, f"q {tag or 'none'}", (tag,) if tag else ()).id
    col.sched.suspend_cards(list(cids.values()))  # type: ignore[arg-type]
    assert waiting_search(col) == "(tag:rd::drill OR tag:rd::held) is:new is:suspended"
    assert waiting_search(col, did).endswith("(tag:rd::drill OR tag:rd::held) is:new is:suspended")
    found = {int(c) for c in col.find_cards(waiting_search(col))}
    assert found == {cids["rd::drill"], cids["rd::held"]}
    assert {c.cid for c in read_waiting_cards(col, st)} == found
    assert {c.cid for c in read_waiting_cards(col, st, did)} == found


def test_held_cards_count_as_waiting_and_stale(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Lab"))
    _bqe_session(col, lab, 3)
    apply_hold_back(col, plan_hold_back(col, st, lab))
    now = time.time() * 1000
    (row,) = read_waiting(col, st, DEFAULT_CONFIG, now_ms=now)
    assert (row.deck, row.waiting, row.stale) == ("Lab", 6, 0)
    (later,) = read_waiting(col, st, DEFAULT_CONFIG, now_ms=now + 8 * DAY_MS)
    assert later.stale == 6  # the stale rule treats them like skill drill cards
    short = replace(DEFAULT_CONFIG, stale_drill_days=3)
    assert read_waiting(col, st, short, now_ms=now + 4 * DAY_MS)[0].stale == 6
    # A passed pacing target makes them stale at once.
    today = anki_day(now, col.get_preferences().scheduling.rollover)
    pacing.save(st, lab, pacing.PacingSettings(target_date=today - timedelta(days=1)))
    assert read_waiting(col, st, DEFAULT_CONFIG, now_ms=now)[0].stale == 6
