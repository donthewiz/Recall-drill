"""A Lab 2-shaped scratch deck for the exam tracker's reader tests, with every figure
counted by hand.

``Lab::Lab 2`` (exam in 8 days) with two chapter subdecks, ``Ch 9`` and ``Ch 10``, and a
sibling ``Lab::Lab 1`` with no exam date (its cards must never count). All times are
relative to the machine's clock through Anki's own day, so the scene is valid any day.

Cards (Lab 2's scope; ``Layer::N`` tags and ``rd::`` tags as the anki-cards skill writes them):

- 40 **held** cards: suspended new, 20 in Ch 9 (10 tagged ``rd::held``, 10 ``rd::drill::A1``,
  ``Layer::1``) and 20 in Ch 10 (``Layer::2``). The very first note made is among them and is
  back-dated 30 days.
- 1 **can't-drill** held card: an Image Occlusion note in Ch 9, ``rd::held``, suspended.
- 5 **drilled** new cards ``D1``-``D5`` in Ch 10, unsuspended (handoff B): ``D1``-``D3`` handed
  off today, ``D4`` and ``D5`` yesterday.
- 2 **open** new cards ``U1``, ``U2`` in Ch 10 (unsuspended, never drilled).
- Review cards (none in Ch 10), ``r1``-``r9`` and ``rb``, ``rs``, ``rl``, ``rx``:
  r1 r2 r3 r4 due today; r5 due in 3 days; r6 due in 7 (the day before the exam);
  r7 due in 10 and r8 due in 8 (after the window); r9 overdue by 3; ``rb`` buried, due in 2;
  ``rs`` suspended, due today; ``rl`` learning, due in 10 minutes; ``rx`` due in 20.
- Out of scope in ``Lab::Lab 1``: 5 held cards, 3 reviews due today, and 60 review ratings
  (the answer-time history).

Revlog (every row ``time`` 10,000 ms; days are Anki days, past ones at noon):

========  ===========================================================================
today     r1 learn; r2 learn twice; r3 review + relearn; r4 cram (type 3: not counted)
-1        r3 learn (its first counted rating)
-2        r5 learn; r6 review
-3        r5 manual (type 4: not counted)
-4        r6 learn
-5        r7 learn
-7        r8 learn
-8        r9 learn (outside the 7-day window)
========  ===========================================================================

History: 3 sessions with 30 s of active time per card (drill speed 30 s a card in ``Lab``);
a handoff today of D1-D3, one yesterday of D4-D5, and one 6 days ago of r7.

What the tracker must say (``EXPECTED``), in cards, each counted once:

- Drill to go = 40 (the held cards; the can't-drill one is its own bucket);
- New = 3 = the can't-drill held card + U1, U2 (D1-D5 are drilled: done, not New);
- Reviews = 9: r1-r4, r5, r6, r9, rb, rl (r7, r8, rx are later; rs is suspended);
- Cards left = 52; Days left = 8; Done today = 6 (3 drills D1-D3, 2 first ratings r1 r2,
  1 review r3);
- Needed = ceil((52 + 6) / 8) = 8;
- Pace = 8 / 7: day -1: 2 drills (D4 D5) + r3's first rating = 3; -2: r5 first rating + r6
  review = 2; -4: r6 first = 1; -5: r7's first rating, but r7 was drilled (day -6), so it
  is not counted again = 0; -6: r7 drill = 1; -7: r8 first = 1;
- Status red (8 > 1.25 x 8/7);
- Est.: 2 cards left today = 8 - 6; drill 30 s + a new card's first day 1.125 x 10 s (9 learn
  ratings over 8 cards), new 11.25 s, review 10 s:
  2 x (40 x 41.25 + 3 x 11.25 + 9 x 10) / 52 = 68.22 s.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from anki.cards import Card
from anki.collection import Collection
from anki_fixtures import add_io_note, add_note, deck

from recalldrill import history_store, pacing
from recalldrill.anki_io.workload import today_for
from recalldrill.storage import Storage

DAY_MS = 86_400_000
ROW_MS = 10_000


@dataclass
class ExamScene:
    col: Collection
    st: Storage
    today: date
    now_ms: int
    exam: date
    lab: int
    lab2: int
    ch9: int
    ch10: int
    lab1: int
    cards: dict[str, Card]


EXPECTED = {
    "drill": 40,
    "new": 3,
    "reviews": 9,
    "cards_left": 52,
    "days_left": 8,
    "done_today": 6,
    "needed": 8,
    "pace_total": 8,
    "pace_days": 7,
}


def storage(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def noon_ms(day: date) -> int:
    return int(datetime.combine(day, datetime.min.time()).replace(hour=12).timestamp() * 1000)


def iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def rate(col: Collection, cid: int, when_ms: int, ease: int, kind: int, ms: int = ROW_MS) -> None:
    """One revlog row (``kind``: 0 learn, 1 review, 2 relearn, 3 cram, 4 manual)."""
    assert col.db is not None
    col.db.execute(
        "insert into revlog (id, cid, usn, ease, ivl, lastIvl, factor, time, type) "
        "values (?, ?, -1, ?, 1, 0, 2500, ?, ?)",
        when_ms,
        cid,
        ease,
        ms,
        kind,
    )


def set_state(col: Collection, c: Card, due: int, queue: int = 2, type_: int = 2) -> None:
    c.type, c.queue, c.due, c.ivl, c.factor = type_, queue, due, 10, 2500  # type: ignore[assignment]
    col.update_card(c)


def note_card(col: Collection, did: int, front: str, tags: tuple[str, ...] = ()) -> Card:
    note = add_note(col, "Basic", did, {"Front": front, "Back": f"{front} a"}, tags)  # type: ignore[arg-type]
    return note.cards()[0]


def suspend(col: Collection, *cards: Card) -> None:
    col.sched.suspend_cards([c.id for c in cards])


def handoff(st: Storage, key: str, sid: str, at_ms: int, cards: list[Card]) -> None:
    history_store.append_handoff(
        st,
        key,
        {
            "type": "handoff",
            "sessionId": sid,
            "timestamp": iso(at_ms),
            "groups": {"drilled_new": [c.id for c in cards]},
            "cards": [{"cid": c.id, "nid": c.nid, "ord": 0} for c in cards],
        },
    )


def session(st: Storage, key: str, sid: str, at_ms: int, did: int, active_ms: int) -> None:
    history_store.append_session(
        st,
        key,
        {
            "type": "session",
            "sessionId": sid,
            "finishedAt": iso(at_ms),
            "activeMs": active_ms * 2,
            "anki": [{"cid": 1, "did": did, "activeMs": active_ms}] * 2,
            "cards": [{"chunks": 1}] * 2,
        },
    )


def set_exam(st: Storage, did: int, day: date | None, target: date | None = None) -> None:
    pacing.save(st, did, pacing.PacingSettings(target_date=target, exam_date=day))


def backdate_note(col: Collection, card: Card, ms: int) -> None:
    """Gives the card's note a creation time (its id) of ``ms``."""
    assert col.db is not None
    col.db.execute("update notes set id = ? where id = ?", ms, card.nid)
    col.db.execute("update cards set nid = ? where nid = ?", ms, card.nid)


def build(col: Collection, st: Storage, exam_in_days: int = 8) -> ExamScene:
    today, _rollover = today_for(col)
    now_ms = int(time.time() * 1000)
    lab = int(deck(col, "Lab"))
    lab2 = int(deck(col, "Lab::Lab 2"))
    ch9 = int(deck(col, "Lab::Lab 2::Ch 9"))
    ch10 = int(deck(col, "Lab::Lab 2::Ch 10"))
    lab1 = int(deck(col, "Lab::Lab 1"))
    cards: dict[str, Card] = {}
    day_no = int(col.sched.today)

    held: list[Card] = []
    for i in range(40):
        did, tags = (
            (ch9, ("Layer::1", "rd::held" if i < 10 else "rd::drill::A1"))
            if i < 20
            else (ch10, ("Layer::2", "rd::held"))
        )
        held.append(note_card(col, did, f"held{i}", tags))
    backdate_note(col, held[0], now_ms - 30 * DAY_MS)
    cant = add_io_note(col, ch9)  # type: ignore[arg-type]
    cant.add_tag("rd::held")
    cant.add_tag("Layer::1")
    col.update_note(cant)
    cards["cant"] = cant.cards()[0]
    suspend(col, *held, cards["cant"])

    for n in ("D1", "D2", "D3", "D4", "D5", "U1", "U2"):
        cards[n] = note_card(col, ch10, n, ("Layer::1",))

    where = {
        "r1": lab2, "r2": lab2, "r3": ch9, "r4": ch9, "r5": ch9, "r6": lab2, "r7": lab2,
        "r8": ch9, "r9": ch9, "rb": ch9, "rs": ch9, "rl": lab2, "rx": lab2,
    }  # fmt: skip
    for n, did in where.items():
        cards[n] = note_card(col, did, n)
    due = {
        "r1": 0, "r2": 0, "r3": 0, "r4": 0, "r5": 3, "r6": 7, "r7": 10, "r8": 8, "r9": -3,
        "rb": 2, "rs": 0, "rx": 20,
    }  # fmt: skip
    for n, d in due.items():
        set_state(col, cards[n], day_no + d)
    set_state(col, cards["rl"], int(time.time()) + 600, queue=1, type_=1)
    col.sched.bury_cards([cards["rb"].id])
    suspend(col, cards["rs"])

    for i in range(5):
        c = note_card(col, lab1, f"other held{i}", ("rd::held",))
        suspend(col, c)
    other = [note_card(col, lab1, f"other rev{i}") for i in range(3)]
    for c in other:
        set_state(col, c, day_no)
    filler = other[0]

    def at(k: int) -> int:
        return noon_ms(today - timedelta(days=k))

    t = now_ms  # today's rows: a few seconds before now
    rate(col, cards["r1"].id, t - 1000, 3, 0)
    rate(col, cards["r2"].id, t - 2000, 1, 0)
    rate(col, cards["r2"].id, t - 3000, 3, 0)
    rate(col, cards["r3"].id, t - 4000, 3, 1)
    rate(col, cards["r3"].id, t - 5000, 1, 2)
    rate(col, cards["r4"].id, t - 6000, 3, 3)
    rate(col, cards["r3"].id, at(1), 3, 0)
    rate(col, cards["r5"].id, at(2), 3, 0)
    rate(col, cards["r6"].id, at(2) + 1000, 3, 1)
    rate(col, cards["r5"].id, at(3), 0, 4)
    rate(col, cards["r6"].id, at(4), 3, 0)
    rate(col, cards["r7"].id, at(5), 3, 0)
    rate(col, cards["r8"].id, at(7), 3, 0)
    rate(col, cards["r9"].id, at(8), 3, 0)
    for i in range(60):
        rate(col, filler.id, at(10 + i % 15) + i * 1000, 3, 1)

    key = str(lab2)
    handoff(st, key, "h-today", now_ms - 60_000, [cards["D1"], cards["D2"], cards["D3"]])
    handoff(st, key, "h-yesterday", at(1), [cards["D4"], cards["D5"]])
    handoff(st, key, "h-old", at(6), [cards["r7"]])
    for i in range(3):
        session(st, key, f"s{i}", at(9 + i), ch9, 30_000)

    set_exam(st, lab2, today + timedelta(days=exam_in_days))
    return ExamScene(
        col,
        st,
        today,
        now_ms,
        today + timedelta(days=exam_in_days),
        lab,
        lab2,
        ch9,
        ch10,
        lab1,
        cards,
    )
