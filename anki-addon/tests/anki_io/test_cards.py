"""anki_io/cards.py: snapshots and classification (every branch)."""

from __future__ import annotations

from dataclasses import replace

import pytest
from anki.collection import Collection
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki.scheduler.v3 import CardAnswer
from anki.scheduler.v3 import Scheduler as V3Scheduler
from anki_fixtures import add_note, cards_by_ord, deck

from recalldrill.anki_io.cards import (
    CARD_CLASSES,
    DEFAULT_ENABLED,
    CardClass,
    CardSnapshot,
    classify,
    read_snapshots,
)

BASE = CardSnapshot(
    cid=1, nid=1, did=1, odid=0, ord=0, ntid=1, type=0, queue=0, ivl=0, due=1,
    lapses=0, reps=0, factor=0, flags=0, tags=(), fsrs_d=None, fsrs_s=None,
)  # fmt: skip


def snap(**kw: object) -> CardSnapshot:
    return replace(BASE, **kw)  # type: ignore[arg-type]


REVIEW = {"type": 2, "queue": 2, "ivl": 30, "reps": 5}


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        ({"odid": 5}, "in_filtered_deck"),
        ({"odid": 5, "flags": 1, "queue": -1}, "in_filtered_deck"),
        ({"queue": -2}, "buried"),
        ({"queue": -3, "flags": 1}, "buried"),
        ({"flags": 1}, "flagged"),
        ({**REVIEW, "ivl": 400, "flags": 1}, "flagged"),  # red-flagged mature card
        ({"flags": 1, "tags": ("leech",), "queue": -1}, "flagged"),
        ({**REVIEW, "tags": ("leech",)}, "leech"),
        ({**REVIEW, "tags": ("Leech",)}, "leech"),
        ({**REVIEW, "queue": -1, "lapses": 8, "tags": ("leech",)}, "leech"),  # suspended leech
        ({"queue": -1}, "suspended_new"),
        ({**REVIEW, "queue": -1}, "suspended_review"),
        ({"type": 1, "queue": -1}, "suspended_review"),
        ({**REVIEW, "lapses": 1}, "lapsed"),
        ({"type": 3, "queue": 1, "lapses": 2}, "lapsed"),
        ({"type": 1, "queue": 1}, "learning"),
        ({"type": 1, "queue": 3}, "learning"),
        ({"type": 3, "queue": 1, "lapses": 0}, "learning"),
        ({}, "new"),
        ({"flags": 2}, "new"),  # orange isn't the repair flag
        ({**REVIEW, "ivl": 20}, "young"),
        ({**REVIEW, "ivl": 21}, "mature"),
        ({**REVIEW, "ivl": 0}, "young"),
    ],
)
def test_classify(kw: dict[str, object], expected: CardClass) -> None:
    assert classify(snap(**kw)) == expected


def test_classify_young_interval_and_flag_colour_are_settings() -> None:
    assert classify(snap(**REVIEW), young_ivl=60) == "young"  # ivl 30
    assert classify(snap(flags=2), flag=2) == "flagged"
    assert classify(snap(flags=1), flag=2) == "new"
    assert classify(snap(flags=1), flag=0) == "new"  # 0: no flag class


STABLE = {**REVIEW, "ivl": 60, "fsrs_d": 4.0, "fsrs_s": 45.0}


@pytest.mark.parametrize(
    ("kw", "expected"),
    [
        (STABLE, "stable"),
        ({**STABLE, "fsrs_s": 30.0, "fsrs_d": 5.0}, "stable"),  # both bounds inclusive
        ({**STABLE, "fsrs_s": 29.9}, "mature"),  # not stable enough
        ({**STABLE, "fsrs_d": 5.1}, "mature"),  # too hard
        ({**STABLE, "fsrs_d": None, "fsrs_s": None}, "mature"),  # no FSRS: never stable
        ({**STABLE, "tags": ("leech",)}, "leech"),  # leech comes first
        ({**STABLE, "flags": 1}, "flagged"),
        ({**STABLE, "ivl": 10}, "stable"),  # a young card FSRS calls stable
        ({**STABLE, "lapses": 2}, "stable"),  # before lapsed
        ({**STABLE, "queue": -1}, "stable"),  # before suspended_review
    ],
)
def test_classify_stable(kw: dict[str, object], expected: CardClass) -> None:
    assert classify(snap(**kw)) == expected


def test_stable_thresholds_are_settings() -> None:
    s = snap(**STABLE)
    assert classify(s, skip_min_stability=50) == "mature"
    assert classify(s, skip_max_difficulty=3) == "mature"
    assert classify(s, skip_min_stability=45, skip_max_difficulty=4) == "stable"


def test_every_class_is_reachable_and_defaults() -> None:
    assert set(CARD_CLASSES) == {
        "in_filtered_deck", "buried", "flagged", "leech", "stable", "suspended_new",
        "suspended_review", "lapsed", "learning", "new", "young", "mature",
    }  # fmt: skip
    assert CARD_CLASSES.index("stable") == CARD_CLASSES.index("leech") + 1
    assert DEFAULT_ENABLED == {"flagged", "leech", "suspended_new", "lapsed", "new", "young"}


def test_read_snapshots_from_a_collection(col: Collection) -> None:
    did = deck(col, "X")
    note = add_note(col, "Basic (and reversed card)", did, {"Front": "q", "Back": "a"}, ["Tag1"])
    c0, c1 = cards_by_ord(note)
    col.set_user_flag_for_cards(1, [c1.id])
    col.sched.suspend_cards([c0.id])

    (s0, s1) = read_snapshots(col, [c0.id, c1.id])
    assert (s0.cid, s0.nid, s0.did, s0.odid, s0.ord, s0.ntid) == (
        c0.id,
        note.id,
        did,
        0,
        0,
        note.mid,
    )
    assert (s0.type, s0.queue, s0.lapses, s0.reps, s0.flags) == (0, -1, 0, 0, 0)
    assert s0.tags == ("Tag1",)
    assert (s0.fsrs_d, s0.fsrs_s) == (None, None)
    assert classify(s0) == "suspended_new"
    assert (s1.ord, s1.flags) == (1, 1)
    assert classify(s1) == "flagged"


def test_snapshot_reads_fsrs_memory_and_review_state(col: Collection) -> None:
    did = deck(col, "X")
    add_note(col, "Basic", did, {"Front": "q", "Back": "a"})
    col.decks.select(did)
    sched = col.sched
    assert isinstance(sched, V3Scheduler)
    top = sched.get_queued_cards(fetch_limit=1).cards[0]
    card = col.get_card(top.card.id)  # type: ignore[arg-type]
    card.start_timer()
    sched.answer_card(sched.build_answer(card=card, states=top.states, rating=CardAnswer.EASY))
    (s,) = read_snapshots(col, [card.id])
    assert s.fsrs_d is not None and 1.0 <= s.fsrs_d <= 10.0
    assert s.fsrs_s is not None and s.fsrs_s > 0
    assert (s.type, s.queue) == (CARD_TYPE_REV, QUEUE_TYPE_REV)
    assert classify(s) == "young"


def test_snapshot_in_filtered_deck_keeps_home_deck(col: Collection) -> None:
    home = deck(col, "X")
    note = add_note(col, "Basic", home, {"Front": "q", "Back": "a"})
    fid = col.decks.new_filtered("F")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [['deck:"X"', 100, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    (s,) = read_snapshots(col, [note.cards()[0].id])
    assert (s.did, s.odid, s.home_did) == (fid, home, home)
    assert s.new_position == s.odue
    assert classify(s) == "in_filtered_deck"
