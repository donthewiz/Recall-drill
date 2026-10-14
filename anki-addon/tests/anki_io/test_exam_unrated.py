"""Exam dates and the unrated-cards warning (v0.3), on scratch collections."""

from __future__ import annotations

import time
from dataclasses import replace
from datetime import date, timedelta
from pathlib import Path

from anki.collection import Collection
from anki_fixtures import add_note, deck

from recalldrill import history_store, pacing
from recalldrill.addon_config import DEFAULT_CONFIG
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.exam import deck_chain, exam_for_deck, inherited_exam
from recalldrill.anki_io.panel import options_for, read_panel
from recalldrill.anki_io.select import Scope
from recalldrill.anki_io.unrated import pending_cards, read_unrated
from recalldrill.measure import anki_day
from recalldrill.storage import Storage

HOUR = 3_600_000
DAY = 24 * HOUR


def _storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def _card(col: Collection, did: int, front: str) -> int:
    note = add_note(col, "Basic", did, {"Front": front, "Back": f"{front} a"})  # type: ignore[arg-type]
    return int(note.card_ids()[0])


def _rate(col: Collection, cid: int, at_ms: int, ease: int = 3, type_: int = 0) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
        "values (?, ?, -1, ?, 1, 0, 0, 5000, ?)",
        at_ms,
        cid,
        ease,
        type_,
    )


def _handoff(
    st: Storage, key: str, drilled: list[int], at_ms: float, holdout: list[int] | None = None
) -> None:
    line = {
        "type": "handoff",
        "sessionId": f"s{at_ms}",
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at_ms / 1000)),
        "groups": {"drilled_new": drilled, "holdout": holdout or []},
        "cards": [{"cid": c, "nid": 0, "ord": 0} for c in drilled],
    }
    history_store.append_handoff(st, key, line)


def test_exam_date_inherits_from_the_nearest_parent(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    course = int(deck(col, "Course"))
    lab = int(deck(col, "Course::Lab"))
    bones = int(deck(col, "Course::Lab::Bones"))
    other = int(deck(col, "Other"))
    assert deck_chain(col, bones) == [bones, lab, course]
    assert exam_for_deck(col, st, bones) is None

    pacing.save(st, course, pacing.PacingSettings(exam_date=date(2026, 12, 1)))
    e = exam_for_deck(col, st, bones)
    assert e is not None and (e.day, e.did) == (date(2026, 12, 1), course)
    pacing.save(st, lab, pacing.PacingSettings(exam_date=date(2026, 10, 30)))
    e = exam_for_deck(col, st, bones)
    assert e is not None and (e.day, e.did) == (date(2026, 10, 30), lab)
    pacing.save(st, bones, pacing.PacingSettings(exam_date=date(2026, 10, 23)))
    e = exam_for_deck(col, st, bones)
    assert e is not None and (e.day, e.did) == (date(2026, 10, 23), bones)
    # What the deck would inherit, ignoring its own date.
    inh = inherited_exam(col, st, bones)
    assert inh is not None and (inh.day, inh.did) == (date(2026, 10, 30), lab)
    # Clearing the deck's own date falls back to the parent's.
    pacing.save(st, bones, pacing.PacingSettings())
    e = exam_for_deck(col, st, bones)
    assert e is not None and e.did == lab
    assert exam_for_deck(col, st, other) is None


def test_the_panel_carries_the_exam_line(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab = int(deck(col, "Course::Lab"))
    bones = int(deck(col, "Course::Lab::Bones"))
    _card(col, bones, "q")
    rollover = col.get_preferences().scheduling.rollover
    today = anki_day(time.time() * 1000, rollover)
    options = options_for(
        {}, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )

    def panel() -> object:
        return read_panel(col, st, Scope(deck_id=bones), options, {}, bones, DEFAULT_CONFIG)

    assert panel().exam_line is None  # type: ignore[attr-defined]
    pacing.save(st, lab, pacing.PacingSettings(exam_date=today + timedelta(days=10)))
    data = panel()
    assert data.exam_line == (  # type: ignore[attr-defined]
        f"Exam: {pacing.short_date(today + timedelta(days=10))} (10 days), set on Course::Lab"
    )
    pacing.save(st, bones, pacing.PacingSettings(exam_date=today + timedelta(days=3)))
    data = panel()
    assert data.exam_line == f"Exam: {pacing.short_date(today + timedelta(days=3))} (3 days)"  # type: ignore[attr-defined]
    assert data.exam_own == today + timedelta(days=3)  # type: ignore[attr-defined]


def _setup_pending(col: Collection, st: Storage) -> tuple[int, dict[str, int], int]:
    """Drilled cards a, b (b rated since), a holdout card h, and c (suspended again)."""
    lab = int(deck(col, "Course::Lab"))
    cids = {n: _card(col, lab, n) for n in ("a", "b", "h", "c", "gone")}
    now = int(time.time() * 1000)
    t0 = now - HOUR
    _handoff(st, str(lab), [cids["a"], cids["b"], cids["c"], cids["gone"]], t0, [cids["h"]])
    _rate(col, cids["b"], t0 + 5 * 60_000)  # rated after the handoff: not waiting
    col.sched.suspend_cards([cids["c"]])  # type: ignore[list-item]
    col.remove_notes([col.get_card(cids["gone"]).nid])  # type: ignore[arg-type]
    return lab, cids, t0


def test_unrated_counts_drilled_and_holdout_cards_without_a_rating(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab, cids, t0 = _setup_pending(col, st)
    now = t0 + HOUR
    pending = pending_cards(col, st)
    assert [p.cid for p in pending] == sorted([cids["a"], cids["h"]])
    w = read_unrated(col, st, now_ms=now)
    assert w is not None and w.count == 2 and w.in_filtered == ()
    rollover = col.get_preferences().scheduling.rollover
    day0 = anki_day(t0, rollover)
    assert w.last_day == day0 + timedelta(days=2) and w.ends == day0 + timedelta(days=3)
    assert w.line().startswith("2 drilled cards are waiting for their first Anki rating.")
    # One deck only (with subdecks): another deck's scope sees nothing.
    other = int(deck(col, "Other"))
    assert read_unrated(col, st, other, now_ms=now) is None
    assert read_unrated(col, st, int(deck(col, "Course")), now_ms=now) is not None
    # A rating after the handoff (a set-due-date row, type 4, doesn't count).
    _rate(col, cids["a"], t0 + 10 * 60_000, type_=4)
    assert read_unrated(col, st, now_ms=now) is not None
    _rate(col, cids["a"], t0 + 20 * 60_000, type_=1)
    w = read_unrated(col, st, now_ms=now)
    assert w is not None and w.count == 1  # only the holdout card is left
    _rate(col, cids["h"], t0 + 30 * 60_000, type_=0)
    assert read_unrated(col, st, now_ms=now) is None  # at 0 the line is hidden


def test_unrated_is_hidden_after_the_deadline(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    _lab, _cids, t0 = _setup_pending(col, st)
    rollover = col.get_preferences().scheduling.rollover
    day0 = anki_day(t0, rollover)
    assert read_unrated(col, st, now_ms=t0 + 2 * DAY) is not None
    # Four days on, Anki day day(t0)+2 is over at the latest.
    assert read_unrated(col, st, now_ms=t0 + 4 * DAY) is None
    assert anki_day(t0 + 4 * DAY, rollover) > day0 + timedelta(days=2)


def test_unrated_notes_cards_in_a_filtered_deck(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    lab, cids, t0 = _setup_pending(col, st)
    col.sched.unsuspend_cards([cids["c"]])  # type: ignore[list-item]
    _rate(col, cids["c"], t0 + 60_000)
    fid = col.decks.new_filtered("Cram")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [[f"cid:{cids['a']}", 100, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    w = read_unrated(col, st, now_ms=t0 + HOUR)
    assert w is not None and w.count == 2 and w.in_filtered == (("Cram", 1),)
    assert w.line().endswith("(1 is in the filtered deck 'Cram')")


def test_the_panel_shows_the_warning_and_the_config_key_turns_it_off(
    col: Collection, tmp_path: Path
) -> None:
    st = _storage(tmp_path)
    lab, _cids, _t0 = _setup_pending(col, st)
    # The handoff happened an hour ago, so the window is open now.
    options = options_for(
        {}, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )
    data = read_panel(col, st, Scope(deck_id=lab), options, {}, lab, DEFAULT_CONFIG)
    assert data.unrated_line is not None
    assert data.unrated_line.startswith("2 drilled cards are waiting for their first Anki rating.")
    off = replace(DEFAULT_CONFIG, unrated_warning=False)
    assert read_panel(col, st, Scope(deck_id=lab), options, {}, lab, off).unrated_line is None
    # A search scope reads no deck, so it shows no line.
    search = read_panel(col, st, Scope(search="deck:Course"), options, {}, lab, DEFAULT_CONFIG)
    assert search.unrated_line is None
