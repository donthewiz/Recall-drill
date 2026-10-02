"""anki_io/handoff.py: plan, apply (one undo step), forecast, on a scratch
collection with FSRS on (conftest's ``col``). Never a real profile.

The A/B outcomes are the Phase 0 facts (``test_api_facts.py``,
docs/DECISIONS.md "Handoff: A vs B").
"""

from __future__ import annotations

import time
from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime
from pathlib import Path
from typing import Any

# anki.collection must load before anki.cards (circular import). A plain
# `import` always sorts above the `from` imports, so isort keeps this order.
import anki.collection  # noqa: F401
import pytest
from anki.cards import Card, CardId
from anki.collection import Collection
from anki.consts import (
    CARD_TYPE_LRN,
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_DAY_LEARN_RELEARN,
    QUEUE_TYPE_LRN,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SUSPENDED,
)
from anki.decks import DeckId
from anki.notes import Note
from anki.scheduler.v3 import Scheduler as V3Scheduler
from anki_fixtures import (
    AMC,
    AMC_TAGS,
    add_amc_models,
    add_bqe_model,
    add_bqe_note,
    add_note,
    cards_by_ord,
    deck,
)

from recalldrill import history_store, sessions
from recalldrill.addon_config import DEFAULT_CONFIG, AddonConfig
from recalldrill.anki_io.build import build_session
from recalldrill.anki_io.handoff import (
    HARD_SEARCH,
    TAG_DRILLED,
    TAG_FINAL_MISS,
    TAG_HARD,
    TAG_LONG,
    UNDO_LABEL,
    HandoffFailed,
    HandoffPlan,
    HandoffSettings,
    Reposition,
    apply_handoff,
    describe,
    failure_text,
    forecast,
    format_when,
    handoff_line,
    next_day_start,
    plan_handoff,
    spill,
    top_deck_for,
)
from recalldrill.anki_io.notetypes import MappingTable
from recalldrill.anki_io.select import Scope, SelectOptions, options_to_json, select_cards
from recalldrill.controller import ControllerSettings
from recalldrill.engine.session import select_trial
from recalldrill.sources import SourceRef, source_to_json
from recalldrill.storage import Storage

B = HandoffSettings(mode="B")
A = HandoffSettings(mode="A")
MODES = [pytest.param(A, id="A"), pytest.param(B, id="B")]

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def v3(col: Collection) -> V3Scheduler:
    assert isinstance(col.sched, V3Scheduler)
    return col.sched


def basic(col: Collection, did: DeckId, front: str, tags: Sequence[str] = ()) -> Card:
    return add_note(col, "Basic", did, {"Front": front, "Back": "b"}, tags).cards()[0]


def ids(cards: Iterable[Card]) -> list[CardId]:
    return [c.id for c in cards]


def set_rollover(col: Collection, hour: int) -> None:
    prefs = col.get_preferences()
    prefs.scheduling.rollover = hour
    col.set_preferences(prefs)


def rollover_far_away(col: Collection) -> None:
    """Keeps learning steps intraday (see test_api_facts._rollover_far_away)."""
    set_rollover(col, (time.localtime().tm_hour + 12) % 24)


def answer(col: Collection, card: Card, ease: int) -> Card:
    card.start_timer()  # build_answer reads time_taken()
    v3(col).answerCard(card, ease)  # type: ignore[arg-type]
    card.load()
    return card


def review_card(col: Collection, did: DeckId, front: str, due_in: int) -> Card:
    """A review card with an FSRS memory state, due ``due_in`` days from today."""
    card = answer(col, basic(col, did, front), 4)  # Easy graduates a new card
    assert card.type == CARD_TYPE_REV and card.memory_state is not None
    card.due = col.sched.today + due_in
    col.update_card(card)
    card.load()
    return card


def schedule(card: Card) -> tuple[Any, ...]:
    """Everything a handoff must never change on a scheduled card."""
    card.load()
    mem = card.memory_state
    return (
        card.type,
        card.due,
        card.ivl,
        card.factor,
        card.left,
        card.reps,
        card.lapses,
        None if mem is None else (mem.stability, mem.difficulty),
    )


def tags_of(col: Collection, card: Card) -> set[str]:
    return {t.casefold() for t in col.get_note(card.nid).tags}


def revlog(col: Collection, cid: int) -> list[tuple[int, ...]]:
    assert col.db is not None
    rows = col.db.all("select ease, ivl, lastIvl, factor, type from revlog where cid=?", cid)
    return [tuple(r) for r in rows]


def make_saved(
    cards: Sequence[Card],
    struggle: Mapping[int, tuple[int, int, int]] | None = None,
    *,
    chunked: Iterable[int] = (),
    complete: bool = True,
    session_id: str = "s1",
    scope_deck: int | None = None,
) -> dict[str, Any]:
    """A finished session's save over ``cards``, in this (drill) order.
    ``struggle``: cid -> (misses, reveals, finalMisses)."""
    struggle = struggle or {}
    long = set(chunked)
    items: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    for i, c in enumerate(cards):
        m, r, f = struggle.get(c.id, (0, 0, 0))
        items.append(
            {
                "id": i,
                "front": f"front {i}",
                "back": "b",
                "status": "mastered",
                "chunks": ["one two", "three four"] if c.id in long else None,
                "finalDone": complete,
                "misses": m,
                "reveals": r,
                "finalMisses": f,
            }
        )
        sources.append(
            source_to_json(
                SourceRef(
                    cid=c.id,
                    nid=c.nid,
                    ord=c.ord,
                    did=c.did,
                    ntid=0,
                    card_class="new",
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
        )
    return {
        "items": items,
        "addon": {
            "sessionId": session_id,
            "sources": sources,
            "scope": {"deckId": scope_deck, "search": None if scope_deck else "x"},
            "handoffPending": True,
        },
    }


def collection_state(col: Collection) -> tuple[Any, ...]:
    """Every card's schedule and position, every note's tags, the revlog size."""
    assert col.db is not None
    cards = col.db.all(
        "select id, type, queue, due, ivl, odue, odid, flags, left from cards order by id"
    )
    notes = sorted((n, tuple(sorted(col.get_note(n).tags))) for n in col.find_notes(""))
    return (tuple(map(tuple, cards)), tuple(notes), col.db.scalar("select count() from revlog"))


# ---------------------------------------------------------------------------
# A and B on suspended new cards (the Phase 0 facts)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("settings", MODES)
def test_suspended_new_cards(col: Collection, settings: HandoffSettings) -> None:
    did = deck(col, "X")
    others = [basic(col, did, f"other {i}") for i in range(3)]
    made = [basic(col, did, f"drilled {i}") for i in range(3)]
    col.sched.suspend_cards(ids(made))
    drilled = made[::-1]  # drill order isn't creation order
    plan = plan_handoff(col, make_saved(drilled), settings)
    assert plan.drilled_new == tuple(ids(drilled))
    assert plan.drilled_scheduled == plan.siblings == plan.holdout == plan.missing == ()
    assert plan.unsuspend == tuple(ids(drilled))
    today = col.sched.today

    apply_handoff(col, plan)

    for pos, c in enumerate(drilled):
        c.load()
        assert c.memory_state is None
        if settings.mode == "B":
            assert (c.type, c.queue, c.ivl) == (CARD_TYPE_NEW, QUEUE_TYPE_MANUALLY_BURIED, 0)
            assert c.due == pos
            assert revlog(col, c.id) == []
        else:
            assert (c.type, c.queue, c.due, c.ivl) == (CARD_TYPE_REV, QUEUE_TYPE_REV, today + 1, 0)
            # One manual row: ease 0, ivl 0, lastIvl 0, factor 2500, type 4.
            assert revlog(col, c.id) == [(0, 0, 0, 2500, 4)]
    for o in others:
        o.load()
        assert o.queue == QUEUE_TYPE_NEW
        if settings.mode == "B":
            assert o.due >= len(drilled)  # shifted behind the drilled cards
    assert col.find_cards("is:suspended") == []


# ---------------------------------------------------------------------------
# Scheduled cards keep their schedule
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("settings", MODES)
def test_suspended_review_leech_is_unsuspended_and_tagged_schedule_unchanged(
    col: Collection, settings: HandoffSettings
) -> None:
    did = deck(col, "X")
    leech = review_card(col, did, "leech", due_in=5)
    note = col.get_note(leech.nid)
    note.add_tag("leech")
    col.update_note(note)
    col.sched.suspend_cards([leech.id])
    before = schedule(leech)

    plan = plan_handoff(col, make_saved([leech]), settings)
    assert plan.drilled_scheduled == (leech.id,) and plan.drilled_new == ()
    assert plan.unsuspend == (leech.id,) and plan.bury == plan.set_due == plan.reposition == ()
    apply_handoff(col, plan)

    assert schedule(leech) == before
    assert leech.queue == QUEUE_TYPE_REV
    assert {"leech", TAG_DRILLED} <= tags_of(col, leech)


@pytest.mark.parametrize("due_in", [0, -3], ids=["due today", "overdue"])
@pytest.mark.parametrize("clear", [True, False], ids=["clear flag", "keep flag"])
def test_red_flagged_review_card_due_today_is_buried(
    col: Collection, due_in: int, clear: bool
) -> None:
    did = deck(col, "X")
    card = review_card(col, did, "repair", due_in=due_in)
    col.set_user_flag_for_cards(1, [card.id])
    before = schedule(card)

    plan = plan_handoff(col, make_saved([card]), HandoffSettings(clear_flag=clear))
    assert plan.bury == (card.id,) and plan.unsuspend == ()
    assert plan.clear_flags == ((card.id,) if clear else ())
    apply_handoff(col, plan)

    assert schedule(card) == before
    assert card.queue == QUEUE_TYPE_MANUALLY_BURIED
    assert card.user_flag() == (0 if clear else 1)


def test_review_card_due_later_is_left_alone(col: Collection) -> None:
    did = deck(col, "X")
    card = review_card(col, did, "later", due_in=2)
    before = schedule(card)
    plan = plan_handoff(col, make_saved([card]), B)
    assert plan.schedule_actions == 0
    apply_handoff(col, plan)
    assert schedule(card) == before and card.queue == QUEUE_TYPE_REV


@pytest.mark.parametrize("settings", MODES)
def test_learning_card_schedule_unchanged(col: Collection, settings: HandoffSettings) -> None:
    rollover_far_away(col)
    did = deck(col, "X")
    card = answer(col, basic(col, did, "learning"), 3)
    assert card.type == CARD_TYPE_LRN
    before = schedule(card)

    plan = plan_handoff(col, make_saved([card]), settings)
    assert plan.drilled_scheduled == (card.id,)
    assert plan.set_due == plan.reposition == ()
    apply_handoff(col, plan)

    # Due later today: buried until tomorrow, schedule untouched.
    assert schedule(card) == before
    assert card.queue == QUEUE_TYPE_MANUALLY_BURIED


@pytest.mark.parametrize("settings", MODES)
def test_card_answered_since_selection_is_scheduled_not_repositioned(
    col: Collection, settings: HandoffSettings
) -> None:
    rollover_far_away(col)
    did = deck(col, "X")
    new = basic(col, did, "was new")
    saved = make_saved([new])  # selected (and drilled) while new
    answer(col, new, 3)  # then studied once on the phone: now type 1
    before = schedule(new)

    plan = plan_handoff(col, saved, settings)
    assert plan.drilled_new == () and plan.drilled_scheduled == (new.id,)
    assert plan.set_due == plan.reposition == ()
    apply_handoff(col, plan)
    assert schedule(new) == before


def test_missing_card_is_skipped_and_listed(col: Collection) -> None:
    did = deck(col, "X")
    gone, kept = basic(col, did, "gone"), basic(col, did, "kept")
    col.sched.suspend_cards([gone.id, kept.id])
    saved = make_saved([gone, kept])
    col.remove_notes([gone.nid])

    plan = plan_handoff(col, saved, B)
    assert plan.missing == (gone.id,)
    assert plan.drilled_new == (kept.id,) and plan.cards == 1
    assert [d.cid for d in plan.drilled] == [kept.id]
    apply_handoff(col, plan)
    kept.load()
    assert kept.queue == QUEUE_TYPE_MANUALLY_BURIED


def test_only_a_complete_session_is_handed_off(col: Collection) -> None:
    did = deck(col, "X")
    card = basic(col, did, "x")
    with pytest.raises(ValueError, match="isn't complete"):
        plan_handoff(col, make_saved([card], complete=False), B)


# ---------------------------------------------------------------------------
# anki-cards decks
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("settings", MODES)
def test_anki_cards_unsuspended_new_cloze_cards(col: Collection, settings: HandoffSettings) -> None:
    add_amc_models(col)
    did = deck(col, "Psychology Ch7")
    notes = [
        add_note(
            col,
            AMC,
            did,
            {"Text": f"Term {i} is {{{{c1::answer {i}}}}}.", "Extra": "<i>why</i>"},
            AMC_TAGS,
        )
        for i in range(3)
    ]
    cards = [n.cards()[0] for n in notes]
    assert all(c.queue == QUEUE_TYPE_NEW for c in cards)  # not suspended
    today = col.sched.today

    plan = plan_handoff(col, make_saved(cards), settings)
    assert plan.drilled_new == tuple(ids(cards)) and plan.unsuspend == ()
    apply_handoff(col, plan)

    for pos, c in enumerate(cards):
        c.load()
        if settings.mode == "B":
            assert (c.type, c.queue, c.due) == (CARD_TYPE_NEW, QUEUE_TYPE_MANUALLY_BURIED, pos)
        else:
            assert (c.type, c.queue, c.due) == (CARD_TYPE_REV, QUEUE_TYPE_REV, today + 1)
        # rd::drill::*, Part::* and Layer::* untouched; rd::drilled added.
        assert tags_of(col, c) == {t.casefold() for t in AMC_TAGS} | {TAG_DRILLED}


# ---------------------------------------------------------------------------
# Siblings
# ---------------------------------------------------------------------------


def _bqe(col: Collection, n: int = 3) -> tuple[DeckId, list[Note]]:
    add_bqe_model(col)
    did = deck(col, "Medical Terminology::3 - Skeletal System")
    notes = [add_bqe_note(col, did, f"term{i}", f"meaning {i}") for i in range(n)]
    col.sched.suspend_cards(col.find_cards(f"did:{did}"))
    return did, notes


@pytest.mark.parametrize("settings", MODES)
def test_siblings_follow_the_drilled_cards(col: Collection, settings: HandoffSettings) -> None:
    did, notes = _bqe(col)
    other = basic(col, did, "unrelated new card")  # not suspended, already queued
    reverse = [cards_by_ord(n)[1] for n in notes]
    normal = [cards_by_ord(n)[0] for n in notes]

    plan = plan_handoff(col, make_saved(reverse), settings)
    assert plan.siblings == tuple(ids(normal))
    apply_handoff(col, plan)

    if settings.mode == "B":
        expect = reverse + normal  # drilled first, then siblings
    else:
        expect = normal  # the drilled cards are reviews now
    for pos, c in enumerate(expect):
        c.load()
        assert (c.type, c.queue, c.due) == (CARD_TYPE_NEW, QUEUE_TYPE_MANUALLY_BURIED, pos)
    other.load()
    assert other.due >= len(expect) and other.queue == QUEUE_TYPE_NEW
    # Positions are per note, so the siblings take a second call.
    starts = [r.start for r in plan.reposition]
    assert starts == ([0, 3] if settings.mode == "B" else [0])


def test_positions_are_per_note(col: Collection) -> None:
    """Both cards of a note drilled: they share the note's position."""
    _did, notes = _bqe(col)
    both = cards_by_ord(notes[0])[::-1]  # Reverse then Normal of note 0
    rev1 = cards_by_ord(notes[1])[1]
    plan = plan_handoff(col, make_saved([*both, rev1]), B)
    assert plan.siblings == (cards_by_ord(notes[1])[0].id,)
    assert plan.reposition == (
        Reposition((both[0].id, both[1].id, rev1.id), 0),
        Reposition(plan.siblings, 2),
    )
    apply_handoff(col, plan)
    assert [c.load() or c.due for c in [*both, rev1]] == [0, 0, 1]
    assert col.get_card(CardId(plan.siblings[0])).due == 2
    again = plan_handoff(col, make_saved([*both, rev1]), B)
    assert again.reposition == ()


def test_siblings_off_or_not_suspended_are_left_alone(col: Collection) -> None:
    _did, notes = _bqe(col)
    reverse = [cards_by_ord(n)[1] for n in notes]
    normal = [cards_by_ord(n)[0] for n in notes]
    col.sched.unsuspend_cards([normal[0].id])  # this one's already in the queue

    plan = plan_handoff(col, make_saved(reverse), HandoffSettings(siblings=False))
    assert plan.siblings == ()
    assert plan.reposition == (Reposition(tuple(ids(reverse)), 0),)
    apply_handoff(col, plan)
    # Not handed off: still suspended (or queued), never buried. The reposition
    # shifts them behind the drilled cards, like every other new card.
    assert [c.load() or c.queue for c in normal] == [QUEUE_TYPE_NEW] + [QUEUE_TYPE_SUSPENDED] * 2
    assert all(c.due >= len(reverse) for c in normal)

    plan = plan_handoff(col, make_saved(reverse, session_id="s2"), B)
    assert plan.siblings == tuple(ids(normal[1:]))


# ---------------------------------------------------------------------------
# Tags
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("struggle", "hard"),
    [((1, 1, 0), False), ((1, 1, 1), True), ((0, 3, 0), True)],
    ids=["2: not hard", "3 with a final miss: hard", "3 reveals: hard"],
)
def test_hard_threshold(col: Collection, struggle: tuple[int, int, int], hard: bool) -> None:
    did = deck(col, "X")
    card = basic(col, did, "x")
    plan = plan_handoff(col, make_saved([card], {card.id: struggle}), B)
    assert (card.id in plan.hard) is hard
    apply_handoff(col, plan)
    tags = tags_of(col, card)
    assert (TAG_HARD in tags) is hard
    assert (TAG_FINAL_MISS in tags) is (struggle[2] > 0)
    assert TAG_DRILLED in tags


def test_struggle_tags_are_replaced_not_accumulated(col: Collection) -> None:
    did = deck(col, "X")
    card = basic(col, did, "x", tags=["rd::hard", "RD::Final-Miss", "rd::drilled", "keep"])
    other = basic(col, did, "y", tags=["rd::hard"])  # not in this session: untouched
    plan = plan_handoff(col, make_saved([card]), B)
    assert dict(plan.tag_remove) == {TAG_HARD: (card.nid,), TAG_FINAL_MISS: (card.nid,)}
    assert dict(plan.tag_add) == {}
    assert (plan.tags_added, plan.tags_removed) == (0, 2)
    apply_handoff(col, plan)
    assert tags_of(col, card) == {"rd::drilled", "keep"}
    assert tags_of(col, other) == {"rd::hard"}


def test_cloze_note_with_one_hard_card_keeps_rd_hard(col: Collection) -> None:
    did = deck(col, "X")
    note = add_note(
        col, "Cloze", did, {"Text": "{{c1::alpha}} and {{c2::beta}}"}, ["rd::hard"]
    )
    c1, c2 = cards_by_ord(note)
    plan = plan_handoff(col, make_saved([c1, c2], {c1.id: (3, 0, 0)}), B)
    assert plan.hard == frozenset({c1.id})
    assert TAG_HARD not in plan.tag_remove and TAG_HARD not in plan.tag_add
    apply_handoff(col, plan)
    assert TAG_HARD in tags_of(col, c1)


@pytest.mark.parametrize("tag_long", [True, False])
def test_long_tag_is_a_setting(col: Collection, tag_long: bool) -> None:
    did = deck(col, "X")
    long, short = basic(col, did, "long"), basic(col, did, "short")
    plan = plan_handoff(
        col, make_saved([long, short], chunked=[long.id]), HandoffSettings(tag_long=tag_long)
    )
    apply_handoff(col, plan)
    assert (TAG_LONG in tags_of(col, long)) is tag_long
    assert TAG_LONG not in tags_of(col, short)


# ---------------------------------------------------------------------------
# One undo step, idempotent, rollback
# ---------------------------------------------------------------------------


def _mixed(col: Collection) -> list[Card]:
    """Suspended new cards with siblings, a red-flagged review due today, a
    suspended leech, a learning card, and stale tags."""
    rollover_far_away(col)
    _did, notes = _bqe(col)
    did = deck(col, "Medical Terminology::4 - Muscles")
    for i in range(2):
        basic(col, did, f"queued {i}")  # new cards the reposition shifts
    flagged = review_card(col, did, "flagged", due_in=0)
    col.set_user_flag_for_cards(1, [flagged.id])
    leech = review_card(col, did, "leech", due_in=4)
    col.sched.suspend_cards([leech.id])
    learning = answer(col, basic(col, did, "learning", tags=["rd::hard"]), 3)
    return [cards_by_ord(n)[1] for n in notes] + [flagged, leech, learning]


@pytest.mark.parametrize("settings", MODES)
def test_one_undo_restores_everything(col: Collection, settings: HandoffSettings) -> None:
    drilled = _mixed(col)
    saved = make_saved(drilled, {drilled[0].id: (3, 0, 1)})
    last = col.undo_status().undo
    before = collection_state(col)

    plan = plan_handoff(col, saved, settings)
    assert plan.siblings and plan.bury and plan.unsuspend and plan.clear_flags
    assert plan.tag_add and plan.tag_remove
    apply_handoff(col, plan)
    assert collection_state(col) != before
    assert col.undo_status().undo == UNDO_LABEL

    result = col.undo()
    assert result.operation == UNDO_LABEL
    assert collection_state(col) == before
    assert col.undo_status().undo == last  # the step before, not a fragment


@pytest.mark.parametrize("settings", MODES)
def test_planning_again_after_a_handoff_plans_nothing(
    col: Collection, settings: HandoffSettings
) -> None:
    drilled = _mixed(col)
    saved = make_saved(drilled, {drilled[0].id: (3, 0, 1)})
    apply_handoff(col, plan_handoff(col, saved, settings))

    again = plan_handoff(col, saved, settings)
    assert again.schedule_actions == 0
    assert (again.unsuspend, again.set_due, again.reposition, again.bury) == ((), (), (), ())
    assert (again.tags_added, again.tags_removed, again.clear_flags) == (0, 0, ())
    assert not again.has_changes


def test_a_failure_partway_is_rolled_back(col: Collection, monkeypatch: pytest.MonkeyPatch) -> None:
    drilled = _mixed(col)
    plan = plan_handoff(col, make_saved(drilled, {drilled[0].id: (3, 0, 1)}), B)
    last = col.undo_status().undo
    before = collection_state(col)

    def boom(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("disk full")

    # Tags, flags and unsuspend have run when the reposition fails.
    monkeypatch.setattr(col.sched, "reposition_new_cards", boom)
    with pytest.raises(HandoffFailed) as info:
        apply_handoff(col, plan)
    assert info.value.rolled_back and isinstance(info.value.cause, RuntimeError)
    assert collection_state(col) == before
    assert col.undo_status().undo == last
    assert "nothing changed in Anki" in failure_text(info.value)
    assert "disk full" in failure_text(info.value)


def test_failure_texts() -> None:
    partial = failure_text(HandoffFailed(RuntimeError("x"), rolled_back=False))
    assert '"Recall Drill handoff" reverts what it did' in partial
    assert "still waiting for its handoff" in failure_text(RuntimeError("y"))


# ---------------------------------------------------------------------------
# Forecast
# ---------------------------------------------------------------------------


def test_next_day_start_and_wording() -> None:
    # Drilling at 1 AM, before a 4 AM rollover: the same calendar morning.
    early = next_day_start(datetime(2026, 10, 2, 1, 0), 4)
    late = next_day_start(datetime(2026, 10, 2, 5, 0), 4)
    assert early == datetime(2026, 10, 2, 4, 0)
    assert late == datetime(2026, 10, 3, 4, 0)
    assert format_when(early) == "Fri Oct 2, 4:00 AM"
    assert format_when(late) == "Sat Oct 3, 4:00 AM"
    assert format_when(datetime(2026, 12, 31, 0, 5)) == "Thu Dec 31, 12:05 AM"
    assert format_when(datetime(2026, 1, 1, 13, 0)) == "Thu Jan 1, 1:00 PM"
    assert next_day_start(datetime(2026, 10, 2, 4, 0), 4) == datetime(2026, 10, 3, 4, 0)


def test_next_day_start_matches_anki(col: Collection) -> None:
    rollover = col.get_preferences().scheduling.rollover
    assert next_day_start(datetime.now(), rollover) == datetime.fromtimestamp(
        col.sched.day_cutoff
    )


def test_spill() -> None:
    assert spill(6, 4) == 2
    assert spill(4, 4) == 0
    assert spill(3, 20) == 0
    assert spill(5, 0) == 5


def _set_limits(col: Collection, did: DeckId, new: int, rev: int) -> None:
    conf = col.decks.config_dict_for_deck_id(did)
    conf["new"]["perDay"] = new
    conf["rev"]["perDay"] = rev
    col.decks.update_config(conf)


def _due(col: Collection, did: DeckId, name: str, days: int) -> Card:
    card = basic(col, did, name)
    card.type, card.queue, card.ivl, card.due = CARD_TYPE_REV, QUEUE_TYPE_REV, 5, (
        col.sched.today + days
    )
    col.update_card(card)
    return card


def _forecast_fixture(col: Collection) -> tuple[DeckId, list[Card], Card]:
    """Medical Terminology: 3 suspended new Reverse cards (+3 siblings) and a
    flagged review due today in the drill; reviews due on days 1-7; another
    deck's reviews for the collection count."""
    set_rollover(col, 4)
    _did, notes = _bqe(col)
    top = deck(col, "Medical Terminology")
    sub = deck(col, "Medical Terminology::2 - Body")
    for d, n in [(1, 4), (2, 2), (3, 1), (5, 3), (7, 1), (9, 5)]:
        for i in range(n):
            _due(col, sub, f"due {d}.{i}", d)
    day_learn = basic(col, sub, "day learn")
    day_learn.type, day_learn.queue = CARD_TYPE_LRN, QUEUE_TYPE_DAY_LEARN_RELEARN
    day_learn.due = col.sched.today + 1
    col.update_card(day_learn)
    learning = basic(col, sub, "learning today")  # intraday, due before the day ends
    learning.type, learning.queue = CARD_TYPE_LRN, QUEUE_TYPE_LRN
    learning.due = col.sched.day_cutoff - 60
    col.update_card(learning)
    flagged = _due(col, sub, "flagged, due today", 0)
    other = deck(col, "Psychology")
    for i in range(2):
        _due(col, other, f"psych {i}", 1)
    _set_limits(col, top, new=4, rev=200)
    drilled = [cards_by_ord(n)[1] for n in notes] + [flagged]
    return top, drilled, flagged


@pytest.mark.parametrize("settings", MODES)
def test_forecast_counts(col: Collection, settings: HandoffSettings) -> None:
    top, drilled, flagged = _forecast_fixture(col)
    plan = plan_handoff(col, make_saved(drilled), settings)
    assert plan.buried_scheduled == (flagged.id,)
    assert top_deck_for(col, plan) == top

    fc = forecast(col, plan, top, now=datetime(2026, 10, 2, 5, 0))
    # Reviews tomorrow: 4 due on day 1 + the day-learning card + the learning
    # card due today + the flagged card (buried today, due tomorrow); under A
    # also the 3 drilled new cards.
    added = 1 + (3 if settings.mode == "A" else 0)
    assert fc.reviews_added == added
    assert fc.reviews == 4 + 1 + 1 + added
    # prop:due=1..7: 4 + 1 (day learning) + 2 + 1 + 3 + 1 = 12.
    assert fc.avg_reviews_7d == pytest.approx(12 / 7)
    # New cards joining the front: B's 3 drilled + 3 siblings; A's 3 siblings.
    assert fc.new_cards == (6 if settings.mode == "B" else 3)
    assert fc.new_limit == 4 and fc.review_limit == 200
    assert fc.new_spill == (2 if settings.mode == "B" else 0)
    # The whole collection: this deck plus Psychology's 2.
    assert fc.collection_reviews == fc.reviews + 2
    assert fc.available_from == datetime(2026, 10, 3, 4, 0)
    assert fc.deck_name == "Medical Terminology"

    warn = " ".join(fc.warnings)
    assert ("spill to the following day" in warn) is (settings.mode == "B")
    assert "more than 1.5×" in warn  # 7 or 10 vs an average of 1.7
    assert "review limit" not in warn


def test_forecast_limits_and_deck_overrides(col: Collection) -> None:
    top, drilled, _flagged = _forecast_fixture(col)
    _set_limits(col, top, new=20, rev=3)
    plan = plan_handoff(col, make_saved(drilled), B)
    fc = forecast(col, plan, top, now=datetime(2026, 10, 2, 1, 0))
    assert fc.available_from == datetime(2026, 10, 2, 4, 0)
    assert fc.new_spill == 0
    assert "over the deck's review limit of 3" in " ".join(fc.warnings)

    deck_dict = col.decks.get(top)
    assert deck_dict is not None
    deck_dict["newLimit"] = 5  # deck options' "This deck" override
    col.decks.save(deck_dict)
    fc = forecast(col, plan, top)
    assert (fc.new_limit, fc.new_spill) == (5, 1)


def test_no_warning_on_an_ordinary_day(col: Collection) -> None:
    did = deck(col, "Steady")
    for d in range(1, 8):
        for i in range(10):
            _due(col, did, f"d{d}.{i}", d)
    card = basic(col, did, "new")
    col.sched.suspend_cards([card.id])
    plan = plan_handoff(col, make_saved([card]), B)
    fc = forecast(col, plan, int(did))
    assert (fc.reviews, fc.avg_reviews_7d, fc.new_cards) == (10, 10.0, 1)
    assert fc.warnings == ()


# ---------------------------------------------------------------------------
# The dialog text and the history line
# ---------------------------------------------------------------------------


def _dialog(col: Collection, settings: HandoffSettings) -> tuple[HandoffPlan, str]:
    top, drilled, _flagged = _forecast_fixture(col)
    struggle: dict[int, tuple[int, int, int]] = {drilled[0].id: (2, 1, 1)}
    plan = plan_handoff(col, make_saved(drilled, struggle), settings)
    fc = forecast(col, plan, top, now=datetime(2026, 10, 2, 5, 0))
    return plan, describe(plan, fc, fc.available_from).plain()


def test_dialog_text_b(col: Collection) -> None:
    _plan, text = _dialog(col, B)
    assert text.splitlines()[0] == (
        "Hand off 4 cards: tag, unsuspend, stay new, front of the queue, "
        "available from Sat Oct 3, 4:00 AM."
    )
    assert "1 card already scheduled in Anki keeps its schedule." in text
    assert "1 scheduled card due today is buried until Sat Oct 3, 4:00 AM." in text
    assert (
        "Siblings: 3 (suspended new cards of the same notes): unsuspended, queued right "
        "after the drilled cards, available from Sat Oct 3, 4:00 AM." in text
    )
    assert "Tags: +6 / −0 (rd::drilled +4, rd::hard +1, rd::final-miss +1)." in text
    assert "Tomorrow in Medical Terminology (from Sat Oct 3, 4:00 AM):" in text
    assert "• New cards: 6 from this handoff join the front of the new queue (new/day 4)." in text
    assert "⚠ 6 new cards tomorrow, over the deck's new/day limit of 4: 2 spill" in text


def test_dialog_text_a(col: Collection) -> None:
    _plan, text = _dialog(col, A)
    assert text.splitlines()[0] == (
        "Hand off 4 cards: tag, unsuspend, become review cards due from "
        "Sat Oct 3, 4:00 AM (no learning steps)."
    )
    assert "queued at the front of the new queue" in text
    assert "• Reviews: 10 due, 4 from this handoff (review limit 200;" in text


def test_dialog_text_when_every_card_is_scheduled(col: Collection) -> None:
    did = deck(col, "X")
    card = review_card(col, did, "r", due_in=3)
    plan = plan_handoff(col, make_saved([card]), B)
    text = describe(plan, None, datetime(2026, 10, 3, 4, 0))
    assert text.headline == "Hand off 1 card: tag, unsuspend; they keep their schedule."
    assert text.forecast == () and text.warnings == ()
    assert "Siblings: 0." in text.lines


def test_handoff_line(col: Collection) -> None:
    plan, _text = _dialog(col, B)
    fc = forecast(col, plan, int(top_deck_for(col, plan) or 0))
    line = handoff_line(plan, fc, 1_790_000_000_000)
    assert line["type"] == "handoff" and line["sessionId"] == "s1" and line["mode"] == "B"
    assert line["timestamp"].endswith("Z")
    assert line["groups"]["drilled_new"] == list(plan.drilled_new)
    assert line["groups"]["siblings"] == list(plan.siblings)
    assert line["groups"]["holdout"] == [] and line["groups"]["missing"] == []
    assert line["tags"] == {
        "added": 6,
        "removed": 0,
        "byTag": {
            "rd::drilled": {"added": 4, "removed": 0},
            "rd::hard": {"added": 1, "removed": 0},
            "rd::final-miss": {"added": 1, "removed": 0},
        },
    }
    first = line["cards"][0]
    assert first["struggle"] == 4 and first["hard"] is True and first["finalMisses"] == 1
    assert [c["hard"] for c in line["cards"][1:]] == [False, False, False]
    assert line["forecast"]["newCards"] == 6 and line["forecast"]["newSpill"] == 2
    assert line["hardThreshold"] == 3


def test_settings_from_config() -> None:
    assert HandoffSettings.from_config(DEFAULT_CONFIG) == HandoffSettings()
    cfg = AddonConfig(handoff_mode="A", handoff_siblings=False, hard_threshold=5)
    assert HandoffSettings.from_config(cfg) == HandoffSettings(
        mode="A", siblings=False, hard_threshold=5
    )


# ---------------------------------------------------------------------------
# End to end: a real finished session's save
# ---------------------------------------------------------------------------


def test_a_real_finished_session(col: Collection, tmp_path: Path) -> None:
    did, notes = _bqe(col)
    table = MappingTable(col)
    scope = Scope(deck_id=int(did))
    options = SelectOptions(card_ords={notes[0].mid: frozenset({1})})  # Reverse only
    sel = select_cards(col, scope, options, table)
    res = build_session(col, sel, None, table, {})
    st = Storage(tmp_path / "user_files", "User 1")
    key = sessions.deck_key(int(did))
    ctrl, _store = sessions.start_session(
        st,
        key=key,
        deck_items=res.deck_items,
        sources=res.sources,
        config={
            "encodeReps": 1,
            "chunkDifficulty": 100,
            "stemTolerance": True,
            "ladderMode": "cumulative",
            "strictPunctuation": False,
            "batchSize": 0,
        },
        scope=sessions.scope_json(deck_id=int(did)),
        select_options=options_to_json(options),
        deck_settings={},
        hints=False,
        settings=ControllerSettings(),
        now_ms=lambda: 1_790_000_000_000,
    )
    ctrl.start()
    missed = False
    for _ in range(500):
        if ctrl.finished:
            break
        if ctrl.state["phase"] == "batch-done":
            ctrl.next_batch()
        elif ctrl.view().buttons.continue_:
            ctrl.continue_()
        else:
            trial = select_trial(ctrl.state)
            assert trial is not None
            typed = trial["target"]
            if ctrl.view().label == "Final check" and not missed:
                typed, missed = "nope", True
            ctrl.submit(typed)
            if ctrl.processing:
                ctrl.dwell_elapsed()
    assert ctrl.finished == "complete"
    saved = sessions.load(st, key)
    assert saved is not None and sessions.save_status(saved) == "handoff"

    plan = plan_handoff(col, saved, B)
    assert plan.drilled_new == tuple(s.cid for s in res.sources)
    assert len(plan.siblings) == 3
    assert plan.tag_add[TAG_FINAL_MISS] and len(plan.tag_add[TAG_DRILLED]) == 3
    apply_handoff(col, plan)
    sessions.complete_handoff(st, key, saved, handoff_line(plan, None, 1_790_000_100_000))

    assert sessions.load(st, key) is None
    lines = history_store.read_all(st, str(did))
    assert [x["type"] for x in lines] == ["session", "handoff"]
    assert len(col.find_notes("tag:rd::drilled")) == 3
    assert len(col.find_cards("tag:rd::drilled is:buried")) == 6
    assert col.find_cards("is:suspended") == []
    # The "my rd::hard cards" search is an exact tag.
    assert HARD_SEARCH == "tag:rd::hard"
