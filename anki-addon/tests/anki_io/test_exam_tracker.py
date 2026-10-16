"""The exam tracker's reader (v0.4 step 2, counted in cards) on real scratch collections.

Every expected figure is counted by hand in ``exam_scene.py``.
"""

from __future__ import annotations

from datetime import timedelta
from pathlib import Path

import pytest
from anki.collection import Collection
from anki_fixtures import add_note, deck
from exam_scene import EXPECTED, build, set_exam, storage

from recalldrill import pacing
from recalldrill.anki_io.exam_tracker import exam_scopes, read_trackers
from recalldrill.anki_io.sections import read_progress
from recalldrill.anki_io.workload import today_for
from recalldrill.exam_tracker import est_text


def test_every_figure_equals_the_hand_count(col: Collection, tmp_path: Path) -> None:
    s = build(col, storage(tmp_path))
    result = read_trackers(col, s.st)
    assert result.day == s.today
    assert set(result.numbers) == {s.lab2}  # Lab 1 and the chapters have no exam date
    n = result.numbers[s.lab2]
    assert n.exam_date == s.exam
    # Cards, each once: D1-D5 are drilled, so they are done and not New.
    assert (n.drill, n.new, n.reviews) == (40, 3, 9)
    assert n.cards_left == 52 == EXPECTED["cards_left"]
    assert n.days_left == 8
    assert n.done_today == 6
    assert n.needed == 8  # ceil((52 + 6) / 8)
    assert n.pace == pytest.approx(8 / 7)  # r7's first rating after its drill no longer counts
    assert n.status == "red"
    # Est.: 2 cards left today = 8 - 6; a drill card costs the drill plus its first day in
    # Anki (30 + 11.25 s): 2 x (40 x 41.25 + 3 x 11.25 + 9 x 10) / 52
    assert n.est_seconds == pytest.approx(2 * (40 * 41.25 + 3 * 11.25 + 9 * 10) / 52)
    assert est_text(n.est_seconds) == "Est. 1 min today"


def test_the_reader_counts_to_the_decks_finish_date(col: Collection, tmp_path: Path) -> None:
    """ "Finish 2 days before" (the setup panel's Pacing box) moves the countdown and the
    review window to exam - 2; the exam date itself is unchanged."""
    s = build(col, storage(tmp_path))
    exam = s.today + timedelta(days=8)
    pacing.save(s.st, s.lab2, pacing.PacingSettings(exam_date=exam, finish_days_before=2))
    n = read_trackers(col, s.st).numbers[s.lab2]
    assert n.exam_date == exam and n.finish_date == exam - timedelta(days=2)
    assert n.days_left == 7 and not n.finish_passed
    # r6 (due the day before the exam) now falls after the finish date: 8 reviews, not 9.
    assert (n.drill, n.new, n.reviews) == (40, 3, 8)
    assert n.needed == 9  # ceil((51 + 6) / 7)


def test_drill_to_go_agrees_with_the_sections_table(col: Collection, tmp_path: Path) -> None:
    s = build(col, storage(tmp_path))
    n = read_trackers(col, s.st).numbers[s.lab2]
    progress = read_progress(col, s.st, s.lab2)
    assert progress.by_layer  # the scene carries Layer::N tags
    held = sum(r.held for r in progress.rows)
    open_ = sum(r.open for r in progress.rows)
    to_go = sum(r.to_go for r in progress.rows)
    assert sum(r.cant_drill for r in progress.rows) == 1
    # Drill to go is the table's "held / waiting" column; the table's "to go" adds the
    # never-drilled unsuspended cards (U1, U2), which the tracker counts as New only.
    assert n.drill == held == 40
    assert to_go == held + open_ == n.drill + 2


def test_nested_exam_dates_split_the_scope(col: Collection, tmp_path: Path) -> None:
    s = build(col, storage(tmp_path))
    set_exam(s.st, s.ch10, s.today + timedelta(days=3))
    result = read_trackers(col, s.st)
    assert set(result.numbers) == {s.lab2, s.ch10}  # Ch 9 only inherits: no tracker
    parent, child = result.numbers[s.lab2], result.numbers[s.ch10]
    # Lab 2 without Ch 10: 20 held, the can't-drill card new, all 9 reviews, done today r1 r2 r3.
    assert (parent.drill, parent.new, parent.reviews, parent.done_today) == (20, 1, 9, 3)
    # Ch 10: 20 held; U1 U2 new (D1-D5 are drilled: done); no reviews; the 3 drills of today.
    assert (child.drill, child.new, child.reviews, child.done_today) == (20, 2, 0, 3)
    assert (child.days_left, child.needed) == (3, 9)  # ceil((22 + 3) / 3)
    # Lab 2 + Ch 10 add up to the one-exam deck's figures.
    assert parent.drill + child.drill == EXPECTED["drill"]
    assert parent.new + child.new == EXPECTED["new"]
    assert parent.done_today + child.done_today == EXPECTED["done_today"]


def test_a_deck_with_only_an_inherited_date_has_no_scope_of_its_own(
    col: Collection, tmp_path: Path
) -> None:
    s = build(col, storage(tmp_path))
    exams, scopes = exam_scopes(col, s.st, s.today)
    assert list(exams) == [s.lab2]
    assert sorted(scopes[s.lab2]) == sorted([s.lab2, s.ch9, s.ch10])


def test_renaming_the_exam_deck_or_its_parent_changes_nothing(
    col: Collection, tmp_path: Path
) -> None:
    s = build(col, storage(tmp_path))
    before = read_trackers(col, s.st).numbers
    col.decks.rename(col.decks.get(s.lab2), "Lab::Lab Two")  # type: ignore[arg-type]
    assert read_trackers(col, s.st).numbers == before
    col.decks.rename(col.decks.get(s.lab), "Renamed Course")  # type: ignore[arg-type]
    assert col.decks.name(s.lab2) == "Renamed Course::Lab Two"  # type: ignore[arg-type]
    after = read_trackers(col, s.st).numbers
    assert after == before and list(after) == [s.lab2]


def test_a_target_date_alone_is_not_an_exam(col: Collection, tmp_path: Path) -> None:
    s = build(col, storage(tmp_path))
    set_exam(s.st, s.lab2, None, target=s.today + timedelta(days=8))
    assert read_trackers(col, s.st).numbers == {}


def test_a_passed_exam_shows_nothing_and_today_is_the_exam_day(
    col: Collection, tmp_path: Path
) -> None:
    s = build(col, storage(tmp_path))
    set_exam(s.st, s.lab2, s.today - timedelta(days=1))
    assert read_trackers(col, s.st).numbers == {}
    set_exam(s.st, s.lab2, s.today)
    n = read_trackers(col, s.st).numbers[s.lab2]
    assert n.exam_today and n.status == "exam" and n.needed is None and n.est_seconds is None
    assert n.done_today == 6 and n.cards_left == n.drill + n.new + n.reviews
    # N = -1: only reviews already overdue before today (r9) and the buried ones overdue.
    assert n.reviews == 1


def test_a_young_scope_averages_over_the_days_since_it_began(
    col: Collection, tmp_path: Path
) -> None:
    s = build(col, storage(tmp_path))
    assert col.db is not None
    # Make the oldest note 3 days old: the pace window is 3 days (days -1, -2, -3).
    oldest = min(int(x) for x in col.db.list("select id from notes"))
    new_id = s.now_ms - 3 * 86_400_000
    col.db.execute("update notes set id = ? where id = ?", new_id, oldest)
    col.db.execute("update cards set nid = ? where nid = ?", new_id, oldest)
    n = read_trackers(col, s.st).numbers[s.lab2]
    # Days -1, -2 and -3 held 3 + 2 + 0 cards (the very first note is among the scope's).
    assert n.pace == pytest.approx(5 / 3)


def test_the_reader_writes_nothing(col: Collection, tmp_path: Path) -> None:
    s = build(col, storage(tmp_path))
    assert col.db is not None

    def snapshot() -> tuple[object, ...]:
        return (
            col.db.scalar("select mod from col"),  # type: ignore[union-attr]
            col.db.all("select * from cards order by id"),  # type: ignore[union-attr]
            col.db.all("select * from notes order by id"),  # type: ignore[union-attr]
            col.db.all("select * from revlog order by id"),  # type: ignore[union-attr]
            col.db.all("select * from graves"),  # type: ignore[union-attr]
        )

    files = sorted(p.read_bytes() for p in (tmp_path / "user_files").rglob("*") if p.is_file())
    before = snapshot()
    read_trackers(col, s.st)
    read_trackers(col, s.st)
    assert snapshot() == before
    assert (
        sorted(p.read_bytes() for p in (tmp_path / "user_files").rglob("*") if p.is_file()) == files
    )


def test_no_rates_means_no_estimate(col: Collection, tmp_path: Path) -> None:
    st = storage(tmp_path)
    did = int(deck(col, "Solo"))
    for i in range(3):
        add_note(col, "Basic", did, {"Front": f"a{i}", "Back": "b"}, ("rd::held",))  # type: ignore[arg-type]
    col.sched.suspend_cards(list(col.find_cards("deck:Solo")))
    today, _ = today_for(col)
    set_exam(st, did, today + timedelta(days=5))
    n = read_trackers(col, st).numbers[did]
    assert (n.drill, n.new, n.reviews) == (3, 0, 0)  # held cards count once, as drill
    assert n.est_seconds is None and est_text(n.est_seconds) == "Est. time: not enough history yet"


def test_a_large_scope_is_read_in_bounded_time(col: Collection, tmp_path: Path) -> None:
    """~8,000 cards (3,900 held and suspended, as in Medical Terminology), a revlog of
    ~20,000 rows, a session history: one read must stay a handful of queries, not a search
    or query per card. The limit is generous for CI but far below per-card work (8,000 searches
    take far longer)."""
    import time as clock

    from anki.collection import AddNoteRequest

    st = storage(tmp_path)
    did = int(deck(col, "Medical Terminology"))
    model = col.models.by_name("Basic")
    assert model is not None and col.db is not None
    requests = []
    for i in range(8000):
        note = col.new_note(model)
        note["Front"], note["Back"] = f"t{i}", f"m{i}"
        if i < 3900:
            note.add_tag("rd::held")
        requests.append(AddNoteRequest(note, did))  # type: ignore[arg-type]
    col.add_notes(requests)
    cids = [int(c) for c in col.find_cards("deck:Medical*")]
    assert len(cids) == 8000
    col.sched.suspend_cards(cids[:3900])  # type: ignore[arg-type]
    day_no = int(col.sched.today)
    reviews = cids[3900:7000]
    ids = ",".join(map(str, reviews))
    col.db.execute(
        f"update cards set type = 2, queue = 2, ivl = 10, due = {day_no} + id % 90"
        f" where id in ({ids})"
    )
    now = int(clock.time() * 1000)
    col.db.executemany(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
        "values (?, ?, -1, 3, 1, 0, 2500, 8000, 1)",
        [(now - 86_400_000 * (1 + i % 25) - i, reviews[i % len(reviews)]) for i in range(20_000)],
    )
    today, _ = today_for(col)
    set_exam(st, did, today + timedelta(days=54))

    started = clock.perf_counter()
    n = read_trackers(col, st).numbers[did]
    elapsed = clock.perf_counter() - started
    print(f"\nexam tracker reader, 8,000-card scope: {elapsed:.2f} s")
    assert (n.drill, n.new) == (3900, 1000)  # held once, as drill; the 1,000 unsuspended new
    assert n.reviews == sum(1 for c in reviews if c % 90 <= 53)  # due <= the day before the exam
    assert elapsed < 10  # measured ~0.3 s locally
