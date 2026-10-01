"""Risk 1: compare the two handoff options against the real Anki scheduler.

A: suspended new cards -> one undo step (tag, unsuspend, set_due_date "1").
B: suspended new cards -> unsuspend, reposition to the front, bury (manual).

Prints a report; asserts nothing. Runs on a throwaway collection in a temp
dir, never on a real profile:

    anki-addon\\.venv\\Scripts\\python anki-addon/tools/fsrs_handoff_experiment.py
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from collections.abc import Sequence

# anki.collection must load before anki.cards (circular import). A plain
# `import` always sorts above the `from` imports, so isort keeps this order.
import anki.collection
import anki.lang

anki.lang.set_lang("en_US")

from anki.buildinfo import version as anki_version  # noqa: E402
from anki.cards import Card, CardId  # noqa: E402
from anki.collection import Collection  # noqa: E402
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV  # noqa: E402
from anki.dbproxy import DBProxy  # noqa: E402
from anki.decks import DeckId  # noqa: E402
from anki.scheduler.v3 import CardAnswer  # noqa: E402
from anki.scheduler.v3 import Scheduler as V3Scheduler  # noqa: E402

DAY_MS = 86_400_000
CARDS_PER_ARM = 40
ARMS = ("A", "B", "C", "D")
REVLOG_COLS = "id,cid,ease,ivl,lastIvl,factor,time,type"
REVLOG_TYPES = {0: "learn", 1: "review", 2: "relearn", 3: "filtered", 4: "manual", 5: "rescheduled"}


def v3(col: Collection) -> V3Scheduler:
    """col.sched is typed V3Scheduler | DummyScheduler; narrow it."""
    assert isinstance(col.sched, V3Scheduler)
    return col.sched


def db(col: Collection) -> DBProxy:
    """col.db is typed DBProxy | None (None once closed); narrow it."""
    assert col.db is not None
    return col.db


def new_collection(directory: str) -> Collection:
    col = Collection(os.path.join(directory, "experiment.anki2"))
    col.set_config("fsrs", True)
    return col


def add_suspended_new(col: Collection, did: DeckId, n: int, tag: str) -> list[CardId]:
    basic = col.models.by_name("Basic")
    assert basic is not None
    cids: list[CardId] = []
    for i in range(n):
        note = col.new_note(basic)
        note["Front"] = f"{tag} front {i}"
        note["Back"] = f"{tag} back {i}"
        note.add_tag(tag)
        col.add_note(note, did)
        cids.extend(c.id for c in note.cards())
    col.sched.suspend_cards(cids)
    return cids


def describe(col: Collection, cid: CardId, label: str) -> None:
    card = col.get_card(cid)
    mem = card.memory_state
    mem_s = "None" if mem is None else f"S={mem.stability:.3f} D={mem.difficulty:.3f}"
    print(
        f"  {label}: type={card.type} queue={card.queue} ivl={card.ivl} "
        f"due={card.due} (today={col.sched.today}) memory_state={mem_s}"
    )
    rows = db(col).all(f"select {REVLOG_COLS} from revlog where cid=? order by id", cid)
    if not rows:
        print("    revlog: (none)")
    for row in rows:
        fields = dict(zip(REVLOG_COLS.split(","), row, strict=True))
        print(f"    revlog: {fields} [{REVLOG_TYPES.get(row[7], '?')}]")


def answer_top_card(col: Collection, did: DeckId, expect: CardId) -> None:
    """Answer Good on the top queued card, through the real v3 scheduler."""
    col.decks.select(did)
    queued = v3(col).get_queued_cards(fetch_limit=1)
    if not queued.cards:
        print("    !! nothing queued")
        return
    top = queued.cards[0]
    card = col.get_card(CardId(top.card.id))
    if card.id != expect:
        print(f"    !! top queued card {card.id} is not the handed-off card {expect}")
    card.start_timer()
    answer = v3(col).build_answer(card=card, states=top.states, rating=CardAnswer.GOOD)
    v3(col).answer_card(answer)


# ---------------------------------------------------------------------------
# Part 1: the handoff itself, and the first real review
# ---------------------------------------------------------------------------


def handoff_a(col: Collection, cids: Sequence[CardId]) -> None:
    nids = list({col.get_card(c).nid for c in cids})
    pos = col.add_custom_undo_entry("Recall Drill handoff")
    col.tags.bulk_add(nids, "rd::drilled")
    col.sched.unsuspend_cards(cids)
    col.sched.set_due_date(cids, "1")
    col.merge_undo_entries(pos)


def handoff_b(col: Collection, cids: Sequence[CardId]) -> None:
    col.sched.unsuspend_cards(cids)
    col.sched.reposition_new_cards(
        cids, starting_from=0, step_size=1, randomize=False, shift_existing=True
    )
    col.sched.bury_cards(cids, manual=True)


def part1(directory: str) -> None:
    print("=" * 78)
    print("PART 1: handoff day and first real review (one card per arm)")
    print("=" * 78)
    col = new_collection(directory)
    try:
        did_a = col.decks.id("Arm A")
        did_b = col.decks.id("Arm B")
        assert did_a is not None and did_b is not None
        # A few ordinary new cards in B's deck, so "front of the queue" means something.
        basic = col.models.by_name("Basic")
        assert basic is not None
        for i in range(3):
            n = col.new_note(basic)
            n["Front"], n["Back"] = f"other {i}", "x"
            col.add_note(n, did_b)

        (a,) = add_suspended_new(col, did_a, 1, "A")
        (b,) = add_suspended_new(col, did_b, 1, "B")

        print("\n[A] before handoff")
        describe(col, a, "A")
        handoff_a(col, [a])
        print("[A] right after handoff (tag + unsuspend + set_due_date '1', one undo step)")
        describe(col, a, "A")
        print(f"    undo label: {col.undo_status().undo!r}")

        print("\n[B] before handoff")
        describe(col, b, "B")
        handoff_b(col, [b])
        print("[B] right after handoff (unsuspend + reposition to front + bury manual)")
        describe(col, b, "B")
        positions = db(col).all(
            "select id, due from cards where did=? and type=0 order by due", did_b
        )
        print(f"    new-queue position (due) of B vs others: {positions}")

        # First real review: make it due today without writing revlog.
        card = col.get_card(a)
        card.due = col.sched.today
        col.update_card(card)
        print("\n[A] made due today via card.due + update_card (no revlog); answering Good")
        answer_top_card(col, did_a, a)
        describe(col, a, "A after first Good")

        col.sched.unbury_deck(did_b)
        print("\n[B] unbury_deck; answering Good on the top queued card")
        answer_top_card(col, did_b, b)
        describe(col, b, "B after first Good")
    finally:
        col.close()


# ---------------------------------------------------------------------------
# Part 2: does a manually buried card come back after day rollover?
# ---------------------------------------------------------------------------


def part2(directory: str) -> None:
    print("\n" + "=" * 78)
    print("PART 2: manual bury across a simulated day rollover")
    print("=" * 78)
    path = os.path.join(directory, "rollover.anki2")
    col = Collection(path)
    col.set_config("fsrs", True)
    did = col.decks.id("Bury")
    assert did is not None
    (cid,) = add_suspended_new(col, did, 1, "R")
    handoff_b(col, [cid])
    print(f"  after bury: queue={col.get_card(cid).queue} today={col.sched.today}")
    # Same trick as rslib's own unbury() test: move the creation stamp back
    # one day, so "today" advances by one and the rollover check fires.
    db(col).execute("update col set crt = crt - 86400")
    col.close()
    col = Collection(path)
    try:
        today = col.sched.today  # sched_timing_today -> unbury_if_day_rolled_over
        print(f"  after crt -= 1 day and reopen: today={today} queue={col.get_card(cid).queue}")
    finally:
        col.close()


# ---------------------------------------------------------------------------
# Part 3: FSRS optimizer inclusion
# ---------------------------------------------------------------------------


def insert_revlog(
    col: Collection,
    rid: int,
    cid: CardId,
    ease: int,
    ivl: int,
    last_ivl: int,
    factor: int,
    rtype: int,
) -> None:
    db(col).execute(
        "insert into revlog (id,cid,usn,ease,ivl,lastIvl,factor,time,type) "
        "values (?,?,?,?,?,?,?,?,?)",
        rid, cid, -1, ease, ivl, last_ivl, factor, 8000, rtype,
    )


def make_review_card(col: Collection, cid: CardId, ivl: int) -> None:
    card: Card = col.get_card(cid)
    card.type = CARD_TYPE_REV
    card.queue = QUEUE_TYPE_REV
    card.ivl = ivl
    card.due = col.sched.today + 1
    col.update_card(card, skip_undo_entry=True)


def backdated_set_due_date(col: Collection, cid: CardId, rid: int) -> None:
    """Write the manual row the way the handoff does (real set_due_date "1"),
    then move it back in time. Its shape is ease 0, ivl 0, factor 2500, type 4:
    factor != 0, so rslib's is_reset() does not treat it as a reset."""
    col.sched.set_due_date([cid], "1")
    db(col).execute("update revlog set id=? where cid=? and type=4", rid, cid)


def build_histories(col: Collection, did: DeckId, start_ms: int) -> None:
    """CARDS_PER_ARM cards per arm. Day 0 = 30 days ago.

    A: set_due_date row on day 0, reviews on days 1, 4, 10.
    B: two learning rows on day 0, reviews on days 1, 4, 10.
    C: set_due_date row on day 0, first rating logged as learning on day 1, reviews 4, 10.
    D (extra, isolates the cause): reviews on days 1, 4, 10 and nothing else.
    """
    day = lambda d, k=0: start_ms + d * DAY_MS + k * 1000  # noqa: E731
    seq = 0
    for arm in ARMS:
        cids = add_suspended_new(col, did, CARDS_PER_ARM, arm)
        col.sched.unsuspend_cards(cids)
        for i, cid in enumerate(cids):
            seq += 1
            off = seq * 10  # keeps revlog ids unique across cards
            # One Again in every 5th card at day 4, to give the optimizer something.
            ease4 = 1 if i % 5 == 0 else 3
            if arm == "A":
                backdated_set_due_date(col, cid, day(0, off))
                insert_revlog(col, day(1, off), cid, 3, 3, 1, 2500, 1)
            elif arm == "B":
                insert_revlog(col, day(0, off), cid, 3, -600, -60, 0, 0)
                insert_revlog(col, day(0, off + 1), cid, 3, 1, -600, 2500, 0)
                insert_revlog(col, day(1, off), cid, 3, 3, 1, 2500, 1)
            elif arm == "C":
                backdated_set_due_date(col, cid, day(0, off))
                insert_revlog(col, day(1, off), cid, 3, 3, 1, 2500, 0)
            else:
                insert_revlog(col, day(1, off), cid, 3, 3, 1, 2500, 1)
            insert_revlog(col, day(4, off), cid, ease4, 6, 3, 2500, 1)
            insert_revlog(col, day(10, off), cid, 3, 15, 6, 2500, 1)
            make_review_card(col, cid, 15)


def part3(directory: str) -> None:
    print("\n" + "=" * 78)
    print(f"PART 3: FSRS optimizer inclusion ({CARDS_PER_ARM} cards per arm)")
    print("=" * 78)
    for line in (build_histories.__doc__ or "").strip().splitlines()[2:]:
        print("  " + line.strip())
    col = Collection(os.path.join(directory, "optimizer.anki2"))
    col.set_config("fsrs", True)
    try:
        did = col.decks.id("Optimizer")
        assert did is not None
        start_ms = int(time.time() * 1000) - 30 * DAY_MS
        build_histories(col, did, start_ms)
        for arm in ARMS:
            resp = col._backend.compute_fsrs_params(
                search=f"tag:{arm}",
                current_params=[],
                ignore_revlogs_before_ms=0,
                num_of_relearning_steps=1,
                health_check=False,
            )
            print(f"  {arm}: fsrs_items={resp.fsrs_items}")
        resp = col._backend.compute_fsrs_params(
            search=" or ".join(f"tag:{a}" for a in ARMS),
            current_params=[],
            ignore_revlogs_before_ms=0,
            num_of_relearning_steps=1,
            health_check=False,
        )
        print(f"  all arms together: fsrs_items={resp.fsrs_items}")
    finally:
        col.close()


def main() -> int:
    print(f"anki {anki_version}, Python {sys.version.split()[0]}")
    with tempfile.TemporaryDirectory() as directory:
        part1(directory)
        part2(directory)
        part3(directory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
