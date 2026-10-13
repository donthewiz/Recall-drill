"""Waiting drill cards and sending them to Anki undrilled (2026-10-12), on
scratch collections."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

import pytest
from anki.collection import Collection
from anki.notes import Note
from anki_fixtures import add_bqe_model, add_bqe_note, add_note, deck

from recalldrill import history_store, pacing
from recalldrill.addon_config import DEFAULT_CONFIG
from recalldrill.anki_io import release as release_mod
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.panel import PanelData, options_for, read_panel
from recalldrill.anki_io.release import ReleaseFailed, apply_release, history_line, plan_release
from recalldrill.anki_io.select import Scope
from recalldrill.anki_io.waiting import read_waiting, read_waiting_cards, waiting_search
from recalldrill.measure import anki_day
from recalldrill.storage import Storage
from recalldrill.waiting import (
    TAG_UNDRILLED,
    UNDO_LABEL,
    WaitingCard,
    WaitingRow,
    release_choices,
    waiting_rows,
)

DAY_MS = 86_400_000


def _storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def _basic(col: Collection, did: int, front: str, tags: tuple[str, ...]) -> Note:
    fields = {"Front": front, "Back": f"{front} answer"}
    return add_note(col, "Basic", did, fields, tags)  # type: ignore[arg-type]


def _waiting_deck(col: Collection) -> tuple[int, dict[str, int]]:
    did = int(deck(col, "Lab 2::Bones"))
    cids: dict[str, int] = {}
    for tag in ("rd::drill", "rd::drill::A", "rd::drilled", "rd::undrilled", "Layer::1", ""):
        note = _basic(col, did, f"q {tag or 'none'}", (tag,) if tag else ())
        cids[tag] = int(note.card_ids()[0])
    col.sched.suspend_cards(list(cids.values()))  # type: ignore[arg-type]
    return did, cids


def test_the_search_is_exact(col: Collection, tmp_path: Path) -> None:
    did, cids = _waiting_deck(col)
    search = waiting_search(col)
    assert search.startswith("tag:rd::drill ") and "is:new" in search and "is:suspended" in search
    found = {int(c) for c in col.find_cards(waiting_search(col))}
    assert found == {cids["rd::drill"], cids["rd::drill::A"]}  # not rd::drilled / rd::undrilled
    # The wildcard the add-on never uses would match both other rd:: tags.
    wide = {int(c) for c in col.find_cards("tag:rd::* is:new is:suspended")}
    assert {cids["rd::drilled"], cids["rd::undrilled"]} <= wide
    cards = read_waiting_cards(col, _storage(tmp_path))
    assert {c.cid for c in cards} == found and {c.did for c in cards} == {did}


def test_unsuspended_or_studied_cards_are_not_waiting(col: Collection, tmp_path: Path) -> None:
    did, cids = _waiting_deck(col)
    col.sched.unsuspend_cards([cids["rd::drill"]])  # type: ignore[list-item]
    found = {c.cid for c in read_waiting_cards(col, _storage(tmp_path))}
    assert found == {cids["rd::drill::A"]}


def test_waiting_and_stale_counts(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    did, _ = _waiting_deck(col)
    other = int(deck(col, "Psych::Ch6"))
    _basic(col, other, "psych", ("rd::drill::B",))
    col.sched.suspend_cards(col.find_cards('deck:"Psych"'))
    now = time.time() * 1000
    (bones, psych) = sorted(read_waiting(col, st, DEFAULT_CONFIG, now_ms=now), key=lambda r: r.deck)
    assert (bones.deck, bones.waiting, bones.stale) == ("Lab 2::Bones", 2, 0)
    assert (psych.deck, psych.waiting, psych.stale) == ("Psych::Ch6", 1, 0)
    rollover = col.get_preferences().scheduling.rollover
    nid = col.get_card(bones.cids[0]).nid  # type: ignore[arg-type]
    assert bones.oldest == anki_day(int(nid), rollover)  # the note id's day
    # 8 days later: past stale_drill_days (7).
    later = read_waiting(col, st, DEFAULT_CONFIG, now_ms=now + 8 * DAY_MS)
    assert [r.stale for r in later] == [2, 1]
    # 7 days later is not yet stale; a 3-day setting makes it so.
    week = read_waiting(col, st, DEFAULT_CONFIG, now_ms=now + 7 * DAY_MS)
    assert [r.stale for r in week] == [0, 0]
    short = replace(DEFAULT_CONFIG, stale_drill_days=3)
    assert [r.stale for r in read_waiting(col, st, short, now_ms=now + 4 * DAY_MS)] == [2, 1]
    # One deck only (with its subdecks).
    (only,) = read_waiting(col, st, DEFAULT_CONFIG, deck_id=int(deck(col, "Lab 2")), now_ms=now)
    assert only.did == did


def test_pacing_makes_fresh_cards_stale(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    _waiting_deck(col)
    parent = int(deck(col, "Lab 2"))
    now = time.time() * 1000
    today = anki_day(now, col.get_preferences().scheduling.rollover)
    # A target on the parent deck, already passed.
    pacing.save(st, parent, pacing.PacingSettings(target_date=today - timedelta(days=1)))
    (row,) = read_waiting(col, st, DEFAULT_CONFIG, now_ms=now)
    assert row.stale == 2 and row.target == today - timedelta(days=1)
    # A target today, finishing a day before: no drill days left.
    pacing.save(st, parent, pacing.PacingSettings(target_date=today))
    assert read_waiting(col, st, DEFAULT_CONFIG, now_ms=now)[0].stale == 2
    # Far ahead with every weekday a drill day: not stale.
    far = pacing.PacingSettings(
        target_date=today + timedelta(days=30), drill_weekdays=frozenset(range(7))
    )
    pacing.save(st, parent, far)
    assert read_waiting(col, st, DEFAULT_CONFIG, now_ms=now)[0].stale == 0


def _two_decks(col: Collection) -> tuple[int, list[int], list[int]]:
    """BQE notes (two cards each) tagged rd::drill, Forward cards in "Lab", their
    Reverse cards moved to "Elsewhere"; all suspended new."""
    add_bqe_model(col)
    lab = int(deck(col, "Lab"))
    elsewhere = int(deck(col, "Elsewhere"))
    fwd: list[int] = []
    rev: list[int] = []
    for i in range(3):
        note = add_bqe_note(col, lab, f"term{i}", f"meaning {i}")  # type: ignore[arg-type]
        note.add_tag("rd::drill::A")
        col.update_note(note)
        cards = sorted(note.cards(), key=lambda c: c.ord)
        fwd.append(int(cards[0].id))
        rev.append(int(cards[1].id))
    col.set_deck(rev, elsewhere)  # type: ignore[arg-type]
    col.sched.suspend_cards(fwd + rev)  # type: ignore[operator]
    return lab, fwd, rev


def test_release_plan_and_apply(col: Collection, tmp_path: Path) -> None:
    lab, fwd, rev = _two_decks(col)
    dues = {c: col.get_card(c).due for c in fwd + rev}  # type: ignore[arg-type]
    plan = plan_release(col, lab, fwd[:2])
    assert plan.released == tuple(fwd[:2]) and plan.siblings == tuple(rev[:2])
    assert len(plan.tag_notes) == 2 and plan.skipped == ()
    assert plan.new_per_day == 20 and plan.days == 1
    text = release_mod.describe(plan)
    assert "2 drill cards" in text and "2 siblings" in text and "about 1 day" in text

    apply_release(col, plan)
    for c in fwd[:2] + rev[:2]:
        card = col.get_card(c)  # type: ignore[arg-type]
        assert card.type == 0 and card.queue == 0  # new, unsuspended, not buried
        assert card.due == dues[c]  # its new-queue position kept
        assert card.note().has_tag(TAG_UNDRILLED)
    assert col.get_card(fwd[2]).queue == -1  # type: ignore[arg-type]
    assert col.undo_status().undo == UNDO_LABEL
    # Planning again right after plans nothing.
    again = plan_release(col, lab, fwd[:2])
    assert not again.has_changes and again.skipped == tuple(fwd[:2])

    # One undo restores everything.
    col.undo()
    for c in fwd[:2] + rev[:2]:
        card = col.get_card(c)  # type: ignore[arg-type]
        assert card.queue == -1 and not card.note().has_tag(TAG_UNDRILLED)


def test_release_rolls_back_on_failure(
    col: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    lab, fwd, _ = _two_decks(col)
    plan = plan_release(col, lab, fwd)
    before = col.undo_status().undo

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("disk full")

    monkeypatch.setattr(col.sched, "unsuspend_cards", boom)
    with pytest.raises(ReleaseFailed) as info:
        apply_release(col, plan)
    assert info.value.rolled_back
    assert "nothing was changed" in release_mod.failure_text(info.value)
    for c in fwd:
        card = col.get_card(c)  # type: ignore[arg-type]
        assert card.queue == -1 and not card.note().has_tag(TAG_UNDRILLED)
    assert col.undo_status().undo == before


def _panel(col: Collection, st: Storage, did: int) -> PanelData:
    options = options_for(
        {}, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )
    return read_panel(col, st, Scope(deck_id=did), options, {}, did, DEFAULT_CONFIG)


def test_history_line_and_selection_wait_for_a_rating(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab, fwd, rev = _two_decks(col)
    plan = plan_release(col, lab, fwd)
    apply_release(col, plan)
    at = int(time.time() * 1000)
    line = history_line(plan, at)
    history_store.append_release(st, str(lab), line)
    (stored,) = history_store.read_all(st, str(lab))
    assert stored["type"] == "release" and stored["deckId"] == lab
    assert stored["scope"] == "all"  # plan_release's default
    assert stored["groups"] == {"released": fwd, "released_siblings": rev}
    assert stored["tags"] == {"added": 3, "byTag": {TAG_UNDRILLED: 3}}
    assert set(history_store.handed_off_at(st)) == set(fwd + rev)

    # Selection and pacing leave them out until Anki rates them.
    p = _panel(col, st, lab)
    assert p.selection.handed_off == 3 and not p.selection.picked
    assert p.selection.pace_remaining == 0
    db = col.db
    assert db is not None
    db.execute(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
        "values (?, ?, 0, 3, 1, 0, 2500, 6000, 0)",
        at + 1000,
        fwd[0],
    )
    p = _panel(col, st, lab)
    assert p.selection.handed_off == 2 and fwd[0] in {c.snap.cid for c in p.selection.picked}
    # And they are no longer waiting drill cards.
    assert read_waiting(col, st, DEFAULT_CONFIG) == []


def test_panel_amber_line_for_stale_waiting_cards(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab, _, _ = _two_decks(col)
    parent_target = anki_day(time.time() * 1000, col.get_preferences().scheduling.rollover)
    assert _panel(col, st, lab).waiting_line is None
    pacing.save(st, lab, pacing.PacingSettings(target_date=parent_target - timedelta(days=2)))
    line = _panel(col, st, lab).waiting_line
    assert line is not None and line.startswith("3 drill cards have waited too long")


def _row_with_two_stale(fwd: list[int], lab: int) -> WaitingRow:
    """A "Lab" row whose first two Forward cards were added 20 days ago and the
    third yesterday."""
    today = date(2026, 10, 13)
    added = [today - timedelta(days=20), today - timedelta(days=20), today - timedelta(days=1)]
    cards = [WaitingCard(c, 1000 + i, lab, added[i]) for i, c in enumerate(fwd)]
    (row,) = waiting_rows(cards, today, 7, lambda _d: None, lambda _d: "Lab")
    return row


def test_release_plan_for_each_choice_and_siblings_follow(col: Collection) -> None:
    lab, fwd, rev = _two_decks(col)
    row = _row_with_two_stale(fwd, lab)
    stale, everything = release_choices(row)
    sp = plan_release(col, lab, stale.cids, stale.scope)
    assert sp.scope == "stale" and sp.released == tuple(fwd[:2])
    assert sp.siblings == tuple(rev[:2])  # the released cards' notes' siblings
    assert fwd[2] not in sp.unsuspend and rev[2] not in sp.unsuspend
    assert "2 stale drill cards" in release_mod.describe(sp)
    ap = plan_release(col, lab, everything.cids, everything.scope)
    assert ap.scope == "all" and ap.released == tuple(fwd) and ap.siblings == tuple(rev)
    assert "3 drill cards" in release_mod.describe(ap)
    both = release_mod.describe_choices([sp, ap])
    assert "Stale only: 2 cards and 2 siblings" in both
    assert "All waiting: 3 cards and 3 siblings" in both

    # Sending the stale choice leaves the fresh card's note waiting.
    apply_release(col, sp)
    assert all(col.get_card(c).queue == 0 for c in fwd[:2] + rev[:2])  # type: ignore[arg-type]
    assert col.get_card(fwd[2]).queue == -1  # type: ignore[arg-type]
    assert col.get_card(rev[2]).queue == -1  # type: ignore[arg-type]


def test_the_history_line_records_the_scope(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab, fwd, _rev = _two_decks(col)
    row = _row_with_two_stale(fwd, lab)
    stale, everything = release_choices(row)
    sp = plan_release(col, lab, stale.cids, stale.scope)
    assert history_line(sp, 0)["scope"] == "stale"
    all_plan = plan_release(col, lab, everything.cids, everything.scope)
    assert history_line(all_plan, 0)["scope"] == "all"
    history_store.append_release(st, str(lab), history_line(sp, 0))
    (stored,) = history_store.read_all(st, str(lab))
    assert stored["scope"] == "stale" and stored["groups"]["released"] == fwd[:2]
    # Selection treats a stale release like any other: the cards wait for a rating.
    assert set(history_store.handed_off_at(st)) == set(fwd[:2] + _rev[:2])


def test_nothing_stale_offers_only_all_waiting(col: Collection) -> None:
    lab, fwd, _rev = _two_decks(col)
    today = date(2026, 10, 13)
    cards = [WaitingCard(c, 1000 + i, lab, today) for i, c in enumerate(fwd)]
    (row,) = waiting_rows(cards, today, 7, lambda _d: None, lambda _d: "Lab")
    (only,) = release_choices(row)
    assert only.scope == "all" and only.cids == tuple(fwd)
