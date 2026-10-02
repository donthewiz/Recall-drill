"""Anki API facts the add-on relies on, as executable checks (spec §6).

Pinned to anki==26.8.1 (requirements-dev.txt). Each test builds what it
needs in a scratch collection (FSRS on) from conftest's `col` fixture. When
a fact differs from the spec, the test asserts what is actually true and
docs/DECISIONS.md says so.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from pathlib import Path

# anki.collection must load before anki.cards (circular import). A plain
# `import` always sorts above the `from` imports, so isort keeps this order.
import anki.collection  # noqa: F401
import pytest
from anki.cards import Card, CardId
from anki.collection import Collection, SearchNode
from anki.consts import (
    CARD_TYPE_NEW,
    CARD_TYPE_REV,
    QUEUE_TYPE_MANUALLY_BURIED,
    QUEUE_TYPE_NEW,
    QUEUE_TYPE_REV,
    QUEUE_TYPE_SUSPENDED,
)
from anki.dbproxy import DBProxy
from anki.decks import DeckId
from anki.models import StockNotetype
from anki.notes import Note
from anki.scheduler.v3 import CardAnswer
from anki.scheduler.v3 import Scheduler as V3Scheduler
from anki.sound import SoundOrVideoTag, TTSTag
from anki.template import TemplateRenderOutput
from anki.utils import strip_html
from anki_fixtures import needs_aqt

# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------


def v3(col: Collection) -> V3Scheduler:
    """col.sched is typed V3Scheduler | DummyScheduler; narrow it."""
    assert isinstance(col.sched, V3Scheduler)
    return col.sched


def db(col: Collection) -> DBProxy:
    """col.db is typed DBProxy | None (None once closed); narrow it."""
    assert col.db is not None
    return col.db


def deck(col: Collection, name: str) -> DeckId:
    did = col.decks.id(name)
    assert did is not None
    return did


def add_basic(
    col: Collection, did: DeckId, front: str = "front", back: str = "back", tags: Sequence[str] = ()
) -> Note:
    model = col.models.by_name("Basic")
    assert model is not None
    note = col.new_note(model)
    note["Front"] = front
    note["Back"] = back
    for t in tags:
        note.add_tag(t)
    col.add_note(note, did)
    return note


def first_card(note: Note) -> Card:
    return note.cards()[0]


def answer_good(col: Collection, did: DeckId) -> Card:
    """Answer Good on the top queued card through the real v3 scheduler."""
    col.decks.select(did)
    queued = v3(col).get_queued_cards(fetch_limit=1)
    assert queued.cards, "nothing queued"
    top = queued.cards[0]
    card = col.get_card(CardId(top.card.id))
    card.start_timer()  # build_answer reads time_taken(); unset timer crashes
    answer = v3(col).build_answer(card=card, states=top.states, rating=CardAnswer.GOOD)
    v3(col).answer_card(answer)
    card.load()
    return card


def revlog(col: Collection, cid: CardId) -> list[dict[str, int]]:
    cols = ["id", "cid", "ease", "ivl", "lastIvl", "factor", "time", "type"]
    rows = db(col).all(f"select {','.join(cols)} from revlog where cid=? order by id", cid)
    return [dict(zip(cols, r, strict=True)) for r in rows]


# ---------------------------------------------------------------------------
# Find
# ---------------------------------------------------------------------------


def test_find_deck_includes_subdecks(col: Collection) -> None:
    x, sub, other = deck(col, "X"), deck(col, "X::Sub"), deck(col, "Other")
    a, b = first_card(add_basic(col, x)), first_card(add_basic(col, sub))
    add_basic(col, other)
    assert sorted(col.find_cards('deck:"X"')) == sorted([a.id, b.id])


def test_find_deck_follows_cards_into_filtered_decks(col: Collection) -> None:
    """Recorded answer: YES. A card moved into a filtered deck keeps its home
    deck in odid, and deck:"X" still finds it."""
    x, sub = deck(col, "X"), deck(col, "X::Sub")
    first_card(add_basic(col, x))
    moved = first_card(add_basic(col, sub))
    fid = col.decks.new_filtered("Filtered")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [['deck:"X::Sub"', 100, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    moved.load()
    assert moved.did == fid and moved.odid == sub
    assert moved.id in col.find_cards('deck:"X"')
    assert moved.id in col.find_cards('deck:"X::Sub"')


def test_find_tag_state_and_props(col: Collection) -> None:
    did = deck(col, "X")
    tagged = first_card(add_basic(col, did, tags=["rd::drilled"]))
    new = first_card(add_basic(col, did))
    susp = first_card(add_basic(col, did))
    buried = first_card(add_basic(col, did))
    due1 = first_card(add_basic(col, did))
    lapsed = first_card(add_basic(col, did))

    col.sched.suspend_cards([susp.id])
    col.sched.bury_cards([buried.id], manual=True)
    col.sched.set_due_date([due1.id], "1")
    # A review card with one lapse and a long interval.
    lapsed.load()
    lapsed.type, lapsed.queue, lapsed.ivl, lapsed.due, lapsed.lapses = (
        CARD_TYPE_REV, QUEUE_TYPE_REV, 30, col.sched.today + 5, 1,
    )
    col.update_card(lapsed)

    assert col.find_cards("tag:rd::drilled") == [tagged.id]
    assert col.find_cards("tag:rd::*") == [tagged.id]
    assert set(col.find_cards("is:new")) == {tagged.id, new.id, susp.id, buried.id}
    assert col.find_cards("is:suspended") == [susp.id]
    assert col.find_cards("is:buried") == [buried.id]
    assert col.find_cards("prop:due=1") == [due1.id]
    assert col.find_cards("prop:lapses>0") == [lapsed.id]
    # ivl<21: due1 (ivl 0 after set_due_date). New cards have no ivl prop match
    # beyond 0 either, so restrict to review cards.
    assert set(col.find_cards("-is:new prop:ivl<21")) == {due1.id}


# ---------------------------------------------------------------------------
# Card state
# ---------------------------------------------------------------------------


def test_card_state_values(col: Collection) -> None:
    did = deck(col, "X")
    new, susp, buried = (first_card(add_basic(col, did)) for _ in range(3))
    col.sched.suspend_cards([susp.id])
    col.sched.bury_cards([buried.id], manual=True)
    for c in (new, susp, buried):
        c.load()
    assert (new.type, new.queue) == (CARD_TYPE_NEW, QUEUE_TYPE_NEW) == (0, 0)
    assert susp.queue == QUEUE_TYPE_SUSPENDED == -1
    assert buried.queue == QUEUE_TYPE_MANUALLY_BURIED == -3


# ---------------------------------------------------------------------------
# FSRS memory
# ---------------------------------------------------------------------------


def test_fsrs_memory_state_and_search_scale(col: Collection) -> None:
    did = deck(col, "X")
    card = first_card(add_basic(col, did))
    assert card.memory_state is None

    card = answer_good(col, did)
    mem = card.memory_state
    assert mem is not None
    assert mem.stability > 0
    # memory_state.difficulty is on FSRS's 1-10 scale...
    assert 1.0 <= mem.difficulty <= 10.0
    assert mem.difficulty > 1.0
    # ...but prop:d in search uses 0-1 ((D - 1) / 9).
    scaled = (mem.difficulty - 1) / 9
    assert col.find_cards(f"prop:d>{scaled - 0.01:.3f}") == [card.id]
    assert col.find_cards(f"prop:d<{scaled + 0.01:.3f}") == [card.id]
    assert col.find_cards("prop:d>1") == []


# ---------------------------------------------------------------------------
# Revlog
# ---------------------------------------------------------------------------


def _rollover_far_away(col: Collection) -> None:
    """Moves the day's rollover about 12 hours from now. Within 10 minutes of the
    cutoff, Anki logs a new card's 10-minute learning step as a 1-day interval
    (seen at 03:52 with the default 4 a.m. rollover), which isn't what the
    revlog test is about."""
    prefs = col.get_preferences()
    prefs.scheduling.rollover = (time.localtime().tm_hour + 12) % 24
    col.set_preferences(prefs)


def test_revlog_columns_and_codes(col: Collection) -> None:
    _rollover_far_away(col)
    did = deck(col, "X")
    add_basic(col, did)
    learn = answer_good(col, did)
    rows = revlog(col, learn.id)
    assert len(rows) == 1
    assert rows[0]["ease"] == 3  # Good; 1 = Again
    assert rows[0]["type"] == 0  # learn
    assert rows[0]["ivl"] < 0  # negative = seconds (learning step)

    manual = first_card(add_basic(col, did))
    col.sched.set_due_date([manual.id], "1")
    (row,) = revlog(col, manual.id)
    assert row["type"] == 4 and row["ease"] == 0  # manual, no rating

    # The answer-building enum is 0-based; revlog.ease is that value + 1.
    assert (CardAnswer.AGAIN, CardAnswer.HARD, CardAnswer.GOOD, CardAnswer.EASY) == (0, 1, 2, 3)
    # The table itself has exactly the columns the add-on reads (plus usn).
    names = [r[1] for r in db(col).all("pragma table_info(revlog)")]
    assert names == ["id", "cid", "usn", "ease", "ivl", "lastIvl", "factor", "time", "type"]


# ---------------------------------------------------------------------------
# Tags, unsuspend
# ---------------------------------------------------------------------------


def test_tags_bulk_add_remove_hierarchical(col: Collection) -> None:
    did = deck(col, "X")
    notes = [add_basic(col, did) for _ in range(2)]
    nids = [n.id for n in notes]
    col.tags.bulk_add(nids, "rd::drilled rd::batch::1")
    for n in notes:
        n.load()
        assert set(n.tags) == {"rd::drilled", "rd::batch::1"}
    assert "rd::batch::1" in col.tags.all()
    col.tags.bulk_remove(nids, "rd::batch::1")
    for n in notes:
        n.load()
        assert n.tags == ["rd::drilled"]


def test_unsuspend_cards(col: Collection) -> None:
    did = deck(col, "X")
    card = first_card(add_basic(col, did))
    col.sched.suspend_cards([card.id])
    col.sched.unsuspend_cards([card.id])
    card.load()
    assert card.queue == QUEUE_TYPE_NEW


# ---------------------------------------------------------------------------
# Set due date on a suspended new card
# ---------------------------------------------------------------------------


def test_set_due_date_on_suspended_new_card_also_unsuspends(col: Collection) -> None:
    """Recorded: set_due_date DOES unsuspend. The card becomes a review card
    (type 2, queue 2), ivl 0, due today+1, with one manual revlog row
    (ease 0, ivl 0, lastIvl 0, factor 2500, type 4). No memory state yet."""
    did = deck(col, "X")
    card = first_card(add_basic(col, did))
    col.sched.suspend_cards([card.id])
    col.sched.set_due_date([card.id], "1")
    card.load()
    assert (card.type, card.queue) == (CARD_TYPE_REV, QUEUE_TYPE_REV)
    assert card.ivl == 0
    assert card.due == col.sched.today + 1
    assert card.memory_state is None
    (row,) = revlog(col, card.id)
    assert {k: row[k] for k in ("ease", "ivl", "lastIvl", "factor", "time", "type")} == {
        "ease": 0, "ivl": 0, "lastIvl": 0, "factor": 2500, "time": 0, "type": 4,
    }


# ---------------------------------------------------------------------------
# Reposition + bury
# ---------------------------------------------------------------------------


def test_reposition_to_front_then_bury(col: Collection) -> None:
    did = deck(col, "X")
    others = [first_card(add_basic(col, did)) for _ in range(3)]
    target = first_card(add_basic(col, did))
    col.sched.reposition_new_cards(
        [target.id], starting_from=0, step_size=1, randomize=False, shift_existing=True
    )
    col.sched.bury_cards([target.id], manual=True)
    target.load()
    assert target.due == 0
    assert target.queue == QUEUE_TYPE_MANUALLY_BURIED
    for o in others:
        o.load()
        assert o.due > target.due
    assert revlog(col, target.id) == []  # neither step writes revlog
    assert col.find_cards("is:buried-manually") == [target.id]


# ---------------------------------------------------------------------------
# One undo step
# ---------------------------------------------------------------------------


def test_handoff_merges_into_one_undo_step(col: Collection) -> None:
    did = deck(col, "X")
    notes = [add_basic(col, did, tags=["keep"]) for _ in range(2)]
    cards = [first_card(n) for n in notes]
    cids = [c.id for c in cards]
    col.sched.suspend_cards(cids)
    before = [(c.type, c.queue, c.due) for c in (col.get_card(i) for i in cids)]

    pos = col.add_custom_undo_entry("Recall Drill handoff")
    col.tags.bulk_add([n.id for n in notes], "rd::drilled")
    col.sched.unsuspend_cards(cids)
    col.sched.set_due_date(cids, "1")
    col.merge_undo_entries(pos)
    assert col.undo_status().undo == "Recall Drill handoff"

    result = col.undo()
    assert result.operation == "Recall Drill handoff"
    after = [(c.type, c.queue, c.due) for c in (col.get_card(i) for i in cids)]
    assert after == before
    for n in notes:
        n.load()
        assert n.tags == ["keep"]
    for cid in cids:
        assert revlog(col, cid) == []
    # The step before it (the suspend) is next on the stack, not a fragment.
    assert col.undo_status().undo == "Suspend"


# ---------------------------------------------------------------------------
# Deck limits, rollover
# ---------------------------------------------------------------------------


def test_deck_config_limits(col: Collection) -> None:
    did = deck(col, "X")
    conf = col.decks.config_dict_for_deck_id(did)
    assert isinstance(conf["new"]["perDay"], int)
    assert isinstance(conf["rev"]["perDay"], int)
    # 0 = suspend, 1 = tag only (Anki's default)
    assert conf["lapse"]["leechAction"] in (0, 1)
    assert (conf["new"]["perDay"], conf["rev"]["perDay"], conf["lapse"]["leechAction"]) == (
        20, 200, 1,
    )


def test_rollover_and_today(col: Collection) -> None:
    rollover = col.get_preferences().scheduling.rollover
    assert 0 <= rollover <= 23
    assert isinstance(col.sched.today, int)
    assert col.sched.today >= 0


def test_manually_buried_card_returns_after_rollover(tmp_path: Path) -> None:
    """Simulates a day passing the way rslib's own unbury() test does: move the
    collection's creation stamp back a day. col.sched.today calls
    sched_timing_today, which runs unbury_if_day_rolled_over."""
    path = str(tmp_path / "rollover.anki2")
    col = Collection(path)
    try:
        did = deck(col, "X")
        card = first_card(add_basic(col, did))
        col.sched.bury_cards([card.id], manual=True)
        day0 = col.sched.today
        db(col).execute("update col set crt = crt - 86400")
    finally:
        col.close()
    col = Collection(path)
    try:
        assert col.sched.today == day0 + 1
        assert col.get_card(card.id).queue == QUEUE_TYPE_NEW
    finally:
        col.close()


# ---------------------------------------------------------------------------
# Cloze
# ---------------------------------------------------------------------------


def test_cloze_ord_and_backend_helpers(col: Collection) -> None:
    did = deck(col, "X")
    model = col.models.by_name("Cloze")
    assert model is not None
    note = col.new_note(model)
    note["Text"] = "{{c1::alpha::hint}} and {{c2::beta}} then {{c1::gamma}}"
    col.add_note(note, did)
    assert sorted(c.ord for c in note.cards()) == [0, 1]  # ord = cloze number - 1

    # ordinal is the CLOZE NUMBER (1-based), not card.ord.
    text = note["Text"]
    assert col._backend.extract_cloze_for_typing(text=text, ordinal=1) == "alpha, gamma"
    assert col._backend.extract_cloze_for_typing(text=text, ordinal=2) == "beta"
    # Unordered (came back [2, 1] here): callers must sort.
    assert sorted(col._backend.cloze_numbers_in_note(note._to_backend_note())) == [1, 2]


# ---------------------------------------------------------------------------
# HTML, audio
# ---------------------------------------------------------------------------


def test_strip_html_glues_block_words_and_keeps_sound() -> None:
    assert strip_html("a<br>b<div>c</div>") == "abc"
    assert strip_html("x [sound:a.mp3] <b>y</b>") == "x [sound:a.mp3] y"


def test_av_tags(col: Collection) -> None:
    did = deck(col, "X")
    card = first_card(add_basic(col, did, front="hi [sound:a.mp3]", back="{{tts en_US:Front}}"))
    q = card.question_av_tags()
    assert q == [SoundOrVideoTag(filename="a.mp3")]
    # Basic's answer template starts with {{FrontSide}}, but the front's audio is
    # not repeated in answer_av_tags.
    assert all(not isinstance(t, SoundOrVideoTag) for t in card.answer_av_tags())

    tts_model = col.models.by_name("Basic")
    assert tts_model is not None
    tmpl = tts_model["tmpls"][0]
    tmpl["afmt"] = "{{FrontSide}}<hr id=answer>{{tts en_US:Back}}"
    col.models.update_dict(tts_model)
    card = first_card(add_basic(col, did, front="q", back="spoken"))
    (tag,) = card.answer_av_tags()
    assert isinstance(tag, TTSTag)
    assert tag.field_text == "spoken"


# ---------------------------------------------------------------------------
# Note types
# ---------------------------------------------------------------------------


def test_note_type_detection(col: Collection) -> None:
    cloze = col.models.by_name("Cloze")
    io = col.models.by_name("Image Occlusion")
    basic = col.models.by_name("Basic")
    assert cloze is not None and io is not None and basic is not None

    assert cloze["type"] == 1
    assert basic["type"] == 0
    # Image Occlusion is ALSO type 1, so "cloze" = type 1 and not IO.
    assert io["type"] == 1

    # originalStockKind uses the OriginalStockKind enum, which is offset from Kind.
    ok = StockNotetype.OriginalStockKind
    assert ok.ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION == 6
    assert ok.ORIGINAL_STOCK_KIND_CLOZE == 5
    assert io.get("originalStockKind") == ok.ORIGINAL_STOCK_KIND_IMAGE_OCCLUSION
    assert cloze.get("originalStockKind") == ok.ORIGINAL_STOCK_KIND_CLOZE

    # The spec's StockNotetype.Kind.KIND_IMAGE_OCCLUSION is 5, which is CLOZE's
    # originalStockKind. Comparing against it would misclassify every cloze note.
    assert StockNotetype.Kind.KIND_IMAGE_OCCLUSION == 5
    assert cloze.get("originalStockKind") == StockNotetype.Kind.KIND_IMAGE_OCCLUSION


# ---------------------------------------------------------------------------
# Phase 2: reading cards into drill items
# ---------------------------------------------------------------------------


def test_render_output_question_text_swaps_media_for_placeholders(col: Collection) -> None:
    """The drill's front is card.render_output(reload=True).question_text. On a
    rendered side, [sound:] (and TTS) become [anki:play:q:N] and {{type:F}}
    becomes [[type:F]], so grading_text strips those too."""
    did = deck(col, "X")
    model = col.models.by_name("Basic (type in the answer)")
    assert model is not None
    note = col.new_note(model)
    note["Front"] = "q [sound:a.mp3]"
    note["Back"] = "ans"
    col.add_note(note, did)
    out = first_card(note).render_output(reload=True)
    assert isinstance(out, TemplateRenderOutput)
    assert out.question_text == "q [anki:play:q:0]\n\n[[type:Back]]"
    assert out.question_av_tags == [SoundOrVideoTag(filename="a.mp3")]


def test_rendered_cloze_question(col: Collection) -> None:
    did = deck(col, "X")
    model = col.models.by_name("Cloze")
    assert model is not None
    note = col.new_note(model)
    note["Text"] = "{{c1::outer {{c2::inner}} text}} and {{c3::x::hint}}"
    col.add_note(note, did)
    by_ord = {c.ord: c for c in note.cards()}
    q = {o: strip_html(c.render_output(reload=True).question_text) for o, c in by_ord.items()}
    # The active deletion shows [...] or its [hint]; other numbers show as text.
    assert q == {0: "[...] and x", 1: "outer [...] text and x", 2: "outer inner text and [hint]"}
    # Public wrapper of the backend call (cloze number = card.ord + 1); nesting
    # is flattened for typing.
    assert col.extract_cloze_for_typing(note["Text"], 1) == "outer inner text"
    assert col.extract_cloze_for_typing(note["Text"], 2) == "inner"
    assert col.extract_cloze_for_typing(note["Text"], 3) == "x"


def test_search_by_notetype_and_template(col: Collection) -> None:
    did = deck(col, "X")
    model = col.models.by_name("Basic (and reversed card)")
    assert model is not None
    note = col.new_note(model)
    note["Front"], note["Back"] = "f", "b"
    col.add_note(note, did)
    add_basic(col, did)
    c0, c1 = sorted(note.cards(), key=lambda c: c.ord)
    assert col.find_cards(f"mid:{model['id']} card:1") == [c0.id]
    assert col.find_cards(f"mid:{model['id']} card:2") == [c1.id]
    assert col.models.nids(model["id"]) == [note.id]


def test_search_node_escaping(col: Collection) -> None:
    assert col.build_search_string(SearchNode(deck='A_b*c "q"')) == '"deck:A\\_b\\*c \\"q\\""'
    assert col.build_search_string(SearchNode(tag="rd::drill::A_1")) == "tag:rd::drill::A\\_1"
    assert col.build_search_string("(a or b)", SearchNode(tag="t")) == "(a OR b) tag:t"


def test_user_flag_and_filtered_odue(col: Collection) -> None:
    did = deck(col, "X")
    card = first_card(add_basic(col, did))
    col.set_user_flag_for_cards(1, [card.id])
    card.load()
    assert card.user_flag() == 1
    assert col.find_cards("flag:1") == [card.id]
    due = card.due
    fid = col.decks.new_filtered("F")
    fdeck = col.decks.get(fid)
    assert fdeck is not None
    fdeck["terms"] = [['deck:"X"', 100, 0]]
    col.decks.save(fdeck)
    col.sched.rebuild_filtered_deck(fid)
    card.load()
    # A new card in a filtered deck keeps its queue position in odue.
    assert (card.odid, card.odue) == (did, due)


def test_current_deck_is_a_dict_with_an_id(col: Collection) -> None:
    did = deck(col, "X")
    col.decks.select(did)
    assert col.decks.current()["id"] == did


# ---------------------------------------------------------------------------
# GUI-side facts that can be checked headless
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "hook",
    [
        "deck_browser_will_show_options_menu",
        "overview_will_render_bottom",
        "profile_will_close",
        "webview_did_receive_js_message",
        "operation_did_execute",
    ],
)
@needs_aqt
def test_gui_hooks_exist(hook: str) -> None:
    import aqt.gui_hooks

    h = getattr(aqt.gui_hooks, hook)
    assert callable(h.append) and callable(h.remove)


@needs_aqt
def test_collection_op_api() -> None:
    from aqt.operations import CollectionOp

    for name in ("success", "failure", "run_in_background"):
        assert callable(getattr(CollectionOp, name))


@needs_aqt
def test_query_op_api() -> None:
    """The Phase 2 dev preview reads cards off the main thread with QueryOp."""
    import inspect

    from aqt.operations import QueryOp

    for name in ("with_progress", "failure", "run_in_background"):
        assert callable(getattr(QueryOp, name))
    assert list(inspect.signature(QueryOp.__init__).parameters)[1:] == ["parent", "op", "success"]
