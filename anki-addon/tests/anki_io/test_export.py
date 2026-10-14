"""The light outcomes export (v0.3) on a scratch collection with FSRS on: the memory
state read through Anki's API, the exam date's inheritance, the file."""

from __future__ import annotations

import csv
import io
import time
from datetime import timedelta
from pathlib import Path

import pytest
from anki.cards import Card
from anki.collection import Collection
from anki.scheduler.v3 import Scheduler as V3Scheduler
from anki_fixtures import add_note, deck

from recalldrill import history_store, pacing
from recalldrill.anki_io.export import export_outcomes, read_records
from recalldrill.measure import anki_day
from recalldrill.outcomes import LAST_RESORT_DECAY, OUTCOME_COLUMNS, retrievability
from recalldrill.storage import Storage

DAY = 86_400_000


def _storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def _basic(col: Collection, did: int, front: str) -> Card:
    return add_note(col, "Basic", did, {"Front": front, "Back": f"{front} a"}).cards()[0]  # type: ignore[arg-type]


def _reviewed(col: Collection, did: int, front: str) -> Card:
    """A card answered Easy once under FSRS: a review card with a memory state."""
    card = _basic(col, did, front)
    sched = col.sched
    assert isinstance(sched, V3Scheduler)
    card.start_timer()
    sched.answerCard(card, 4)  # type: ignore[arg-type]
    card.load()
    assert card.memory_state is not None
    return card


def _rate(col: Collection, cid: int, at_ms: int, ease: int, secs: float, type_: int = 1) -> None:
    assert col.db is not None
    col.db.execute(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
        "values (?, ?, -1, ?, 1, 0, 0, ?, ?)",
        at_ms,
        cid,
        ease,
        int(secs * 1000),
        type_,
    )


def _handoff(
    st: Storage, key: str, cards: list[Card], at_ms: float, holdout: list[Card] | None = None
) -> None:
    history_store.append_handoff(
        st,
        key,
        {
            "type": "handoff",
            "sessionId": "s1",
            "mode": "B",
            "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S.000Z", time.gmtime(at_ms / 1000)),
            "groups": {
                "drilled_new": [c.id for c in cards],
                "holdout": [c.id for c in holdout or []],
            },
            "cards": [{"cid": c.id, "nid": c.nid, "ord": c.ord} for c in cards],
        },
    )


def _session(st: Storage, key: str, cards: list[Card]) -> None:
    line = {
        "type": "session",
        "sessionId": "s1",
        "startedAt": "2026-10-13T10:00:00.000Z",
        "finishedAt": "2026-10-13T10:30:00.000Z",
        "encode": {"encodeReps": 3},
        "cards": [
            {"words": 4, "chunks": 2, "attempts": 7, "misses": 1, "reveals": 0, "finalMisses": 0}
            for _ in cards
        ],
        "anki": [
            {"cid": c.id, "nid": c.nid, "ord": 0, "encodeReps": 3, "adjust": 0, "activeMs": 9000}
            for c in cards
        ],
        "holdout": [],
    }
    history_store.append_session(st, key, line)


def test_the_export_reads_cost_memory_and_the_exam_date(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    course = int(deck(col, "Course"))
    bones = int(deck(col, "Course::Bones"))
    drilled = _reviewed(col, bones, "drilled")
    new_card = _basic(col, bones, "still new")
    held = _reviewed(col, bones, "holdout")
    now = int(time.time() * 1000)
    rollover = col.get_preferences().scheduling.rollover
    today = anki_day(now, rollover)
    t0 = now - 3 * DAY
    _handoff(st, str(bones), [drilled, new_card], t0, [held])
    _session(st, str(bones), [drilled, new_card])
    # Revlog: the drilled card's next-day Again, then a Good; the holdout card's intro.
    col.db.execute("delete from revlog")  # type: ignore[union-attr]
    _rate(col, drilled.id, t0 + DAY, 1, 4.5)
    _rate(col, drilled.id, t0 + 2 * DAY, 3, 3.0)
    _rate(col, held.id, t0 + 100, 3, 2.0, type_=0)
    # An exam on the parent deck, 20 days from now.
    exam = today + timedelta(days=20)
    pacing.save(st, course, pacing.PacingSettings(exam_date=exam))

    recs = read_records(col, st, now_ms=now)
    by_cid = {r.row.cid: r for r in recs}
    assert sorted(by_cid) == sorted([drilled.id, new_card.id, held.id])

    d = by_cid[drilled.id]
    assert d.cost is not None and (d.cost.anki_seconds, d.cost.again, d.cost.ratings) == (7.5, 1, 2)
    assert not d.cost.complete  # day 13 is still ahead
    assert d.row.active_ms == 9000 and d.row.words == 4 and d.row.chunks == 2
    assert d.exam == exam  # inherited from Course
    # R from the card's own stability and decay (else the preset's), t = last counted review
    # (t0 + 2 days) to the exam.
    card = col.get_card(drilled.id)
    assert card.memory_state is not None
    decay = card.decay if card.decay is not None else col.compute_memory_state(card.id).decay
    last = anki_day(t0 + 2 * DAY, rollover)
    expected = retrievability(card.memory_state.stability, (exam - last).days, decay or 0)
    assert d.recall == pytest.approx(expected or 0, abs=1e-9)
    assert d.recall is not None and 0 < d.recall < 1

    # A card still new: no memory state, no recall (never a guess).
    n = by_cid[new_card.id]
    assert n.recall is None and n.exam == exam
    # The holdout card is measured from its introduction.
    h = by_cid[held.id]
    assert h.row.group == "holdout" and h.row.outcome.t0_ms == t0 + 100
    assert h.cost is not None and (h.cost.anki_seconds, h.cost.ratings) == (2.0, 1)


def test_no_exam_date_or_a_past_one_gives_no_recall(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    did = int(deck(col, "Course::Bones"))
    card = _reviewed(col, did, "x")
    now = int(time.time() * 1000)
    _handoff(st, str(did), [card], now - DAY)
    col.db.execute("delete from revlog")  # type: ignore[union-attr]
    _rate(col, card.id, now - 100, 3, 1.0)
    (rec,) = read_records(col, st, now_ms=now)
    assert rec.exam is None and rec.recall is None
    today = anki_day(now, col.get_preferences().scheduling.rollover)
    pacing.save(st, did, pacing.PacingSettings(exam_date=today - timedelta(days=2)))
    (rec,) = read_records(col, st, now_ms=now)
    assert rec.exam == today - timedelta(days=2) and rec.recall is None  # exam already past


def test_the_preset_decay_and_the_last_resort(
    col: Collection, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    st = _storage(tmp_path)
    did = int(deck(col, "Course"))
    card = _reviewed(col, did, "x")
    now = int(time.time() * 1000)
    rollover = col.get_preferences().scheduling.rollover
    today = anki_day(now, rollover)
    _handoff(st, str(did), [card], now - DAY)
    col.db.execute("delete from revlog")  # type: ignore[union-attr]
    _rate(col, card.id, now - 100, 3, 1.0)
    pacing.save(st, did, pacing.PacingSettings(exam_date=today + timedelta(days=9)))
    stored = col.get_card(card.id)
    assert stored.memory_state is not None
    s = stored.memory_state.stability

    # The card has no decay of its own: the preset's is used (what compute_memory_state says).
    stored.decay = None
    col.update_card(stored)
    assert col.get_card(card.id).decay is None
    preset = col.compute_memory_state(card.id).decay
    assert preset is not None and preset == pytest.approx(0.1542, abs=1e-4)
    (rec,) = read_records(col, st, now_ms=now)
    assert rec.recall == pytest.approx(retrievability(s, 9, preset) or 0, abs=1e-9)

    # The card's own decay wins over the preset's.
    stored.decay = 0.3
    col.update_card(stored)
    (rec,) = read_records(col, st, now_ms=now)
    assert rec.recall == pytest.approx(retrievability(s, 9, 0.3) or 0, abs=1e-6)

    # If the preset's decay can't be read, 0.1542 is the last resort.
    stored.decay = None
    col.update_card(stored)

    def boom(*_a: object, **_k: object) -> None:
        raise RuntimeError("no params")

    monkeypatch.setattr(col, "compute_memory_state", boom)
    (rec,) = read_records(col, st, now_ms=now)
    assert rec.recall == pytest.approx(retrievability(s, 9, LAST_RESORT_DECAY) or 0, abs=1e-9)


def test_export_writes_the_file_atomically(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    did = int(deck(col, "Course"))
    a = _basic(col, did, "a")
    b = _basic(col, did, "b")
    now = int(time.time() * 1000)
    _handoff(st, str(did), [a], now - DAY, [b])
    result = export_outcomes(col, st, now_ms=now)
    expected = tmp_path / "user_files" / "profiles" / "User 1" / "exports" / "outcomes.csv"
    assert result.path == expected and result.folder == expected.parent and result.rows == 2
    text = expected.read_text(encoding="utf-8")
    assert text.splitlines()[0] == ",".join(OUTCOME_COLUMNS) and "\r" not in text
    rows = list(csv.DictReader(io.StringIO(text)))
    assert [(r["group"], r["cid"]) for r in rows] == [
        ("drilled", str(a.id)),
        ("holdout", str(b.id)),
    ]
    assert rows[0]["homeDeck"] == "Course" and rows[0]["complete"] == "0"
    assert sorted(p.name for p in expected.parent.iterdir()) == ["outcomes.csv"]
    # Run again: rewritten in place, same shape.
    again = export_outcomes(col, st, now_ms=now)
    assert again.rows == 2 and expected.read_text(encoding="utf-8") == text


def test_export_with_no_history_writes_just_the_header(col: Collection, tmp_path: Path) -> None:
    st = _storage(tmp_path)
    result = export_outcomes(col, st)
    assert result.rows == 0
    assert result.path.read_text(encoding="utf-8") == ",".join(OUTCOME_COLUMNS) + "\n"
