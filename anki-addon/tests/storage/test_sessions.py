"""sessions.py: keys, the save's addon block, resume, completion, drill-again."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import pytest
from controller_support import SHORT, Clock, config, source

from recalldrill import history_store, sessions
from recalldrill.controller import ControllerSettings, DrillController, SessionComplete
from recalldrill.engine.session import select_trial
from recalldrill.sessions import (
    SessionStore,
    again_key,
    deck_key,
    history_key,
    open_saved,
    save_status,
    scope_json,
    scope_key,
    search_key,
    start_drill_again,
    start_session,
)
from recalldrill.storage import Storage

OPTIONS = {"enabled": ["new"], "card_ords": {}, "max_cards": None, "order": "priority_first"}
DECK_SETTINGS = {"strictPunctuation": True}


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return Storage(tmp_path / "user_files", "User 1")


def _start(st: Storage, deck: Any = SHORT, **cfg: Any) -> tuple[DrillController, SessionStore]:
    return start_session(
        st,
        key=deck_key(42),
        deck_items=deck,
        sources=[source(i) for i in range(len(deck))],
        config=config(**cfg),
        scope=scope_json(deck_id=42),
        select_options=OPTIONS,
        deck_settings=DECK_SETTINGS,
        hints=True,
        settings=ControllerSettings(deck_name="Med Term"),
        now_ms=Clock(),
    )


def _answer_correctly(ctrl: DrillController) -> list[Any]:
    effects: list[Any] = []
    if ctrl.state["phase"] == "batch-done":
        return ctrl.next_batch()
    if ctrl.view().buttons.continue_:
        return ctrl.continue_()
    trial = select_trial(ctrl.state)
    assert trial is not None
    effects += ctrl.submit(trial["target"])
    if ctrl.processing:
        effects += ctrl.dwell_elapsed()
    return effects


def _finish(ctrl: DrillController) -> list[Any]:
    effects: list[Any] = []
    for _ in range(500):
        if ctrl.finished:
            return effects
        effects += _answer_correctly(ctrl)
    raise AssertionError("didn't finish")


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def test_keys() -> None:
    assert deck_key(1234) == "deck-1234"
    q = 'deck:"Med Term" tag:rd::drill'
    assert search_key(q) == "search-" + hashlib.sha1(q.encode()).hexdigest()[:12]
    assert again_key("deck-1") == "again-deck-1"
    assert scope_key(scope_json(deck_id=7)) == "deck-7"
    assert scope_key(scope_json(search=q)) == search_key(q)
    assert history_key(scope_json(deck_id=7)) == "7"
    assert history_key(scope_json(search=q)) == search_key(q)
    for bad in ({}, {"deck_id": 1, "search": "x"}):
        with pytest.raises(ValueError):
            scope_json(**bad)


# ---------------------------------------------------------------------------
# The save
# ---------------------------------------------------------------------------


def test_start_writes_the_save_with_the_addon_block(st: Storage) -> None:
    ctrl, store = _start(st)
    assert not st.exists("sessions/deck-42.json")
    ctrl.start()
    saved = sessions.load(st, "deck-42")
    assert saved is not None
    assert saved["deckName"] == "Med Term" and saved["phase"] == "encode"
    addon = saved["addon"]
    assert len(addon["sessionId"]) == 32 and int(addon["sessionId"], 16) >= 0
    assert addon["sessionId"] == store.meta.session_id
    assert addon["startedAt"] == saved["stats"]["startTime"]
    assert addon["scope"] == {"deckId": 42, "search": None}
    assert addon["selectOptions"] == OPTIONS and addon["deckSettings"] == DECK_SETTINGS
    assert addon["hints"] is True and addon["drillAgainOf"] is None
    assert addon["handoffPending"] is False and addon["historyWritten"] is False
    assert addon["collisions"] == 0
    assert [s["cid"] for s in addon["sources"]] == [1000, 1001, 1002]
    assert sessions.list_keys(st) == ["deck-42"]
    assert save_status(saved) == "resume"


def test_every_answer_is_saved_and_resumes(st: Storage) -> None:
    ctrl, _ = _start(st)
    ctrl.start()
    for typed in ("cardi", "nope"):
        stamp = sessions.load(st, "deck-42")["timestamp"]  # type: ignore[index]
        ctrl.submit(typed)
        if ctrl.processing:
            ctrl.dwell_elapsed()
        saved = sessions.load(st, "deck-42")
        assert saved is not None and saved["timestamp"] > stamp
    ctrl.continue_()
    view = ctrl.view()
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["stats"]["misses"] == 1
    again, store = open_saved(st, "deck-42", saved, ctrl.settings, Clock())
    assert again.view() == view
    assert store.meta.session_id == saved["addon"]["sessionId"]


def test_resume_keeps_the_collision_tally(st: Storage) -> None:
    first, store = _start(st, [{"front": "vessel", "back": "artery"}])
    ctrl = DrillController(
        first.state,
        [source(0, colliding_answers=("arteries",))],
        first.settings,
        store.persist,
        Clock(),
    )
    ctrl.submit("arteries")
    ctrl.submit("artery")
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["addon"]["collisions"] == 1
    again, _ = open_saved(st, "deck-42", saved, ctrl.settings, Clock())
    assert again.collisions == 1
    assert again.sources[0].colliding_answers == ("arteries",)


def test_load_rejects_what_isnt_a_session(st: Storage) -> None:
    assert sessions.load(st, "deck-1") is None
    st.write_json("sessions/deck-1.json", {"items": []})
    assert sessions.load(st, "deck-1") is None
    st.write_json("sessions/deck-1.json", [1, 2])
    assert sessions.load(st, "deck-1") is None


# ---------------------------------------------------------------------------
# Stop and completion
# ---------------------------------------------------------------------------


def test_stop_keeps_the_save_and_records_the_estimate_once_a_batch_is_done(st: Storage) -> None:
    ctrl, _ = _start(st, SHORT + [{"front": "lung", "back": "pneum"}], encodeReps=1, batchSize=2)
    ctrl.start()
    ctrl.save_and_stop()  # no batch done yet: nothing measured
    assert history_store.get_cold_start_history(st, "deck-42") is None
    assert sessions.load(st, "deck-42") is not None
    ctrl, _ = _start(st, SHORT + [{"front": "lung", "back": "pneum"}], encodeReps=1, batchSize=2)
    while ctrl.state["phase"] != "batch-done":
        _answer_correctly(ctrl)
    ctrl.save_and_stop()
    est = history_store.get_cold_start_history(st, "deck-42")
    assert est is not None and est["multiplier"] == 1 and est["deckShape"] == "full"
    assert est["measuredAt"].endswith("Z")
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["phase"] == "batch-done"
    assert history_store.read_all(st, "42") == []


def test_completion_writes_history_once_and_waits_for_the_handoff(st: Storage) -> None:
    ctrl, store = _start(st, SHORT[:2], encodeReps=1)
    ctrl.start()
    effects = _finish(ctrl)
    assert effects.count(SessionComplete()) == 1
    (line,) = history_store.read_all(st, "42")
    assert line["type"] == "session" and line["sessionId"] == store.meta.session_id
    assert line["finishedAt"].endswith("Z") and line["startedAt"].endswith("Z")
    assert line["stats"]["attempts"] > 0
    assert [c["front"] for c in line["cards"]] == ["heart", "liver"]
    per_card = {"d": None, "s": None, "encodeReps": 1, "minWordsToChunk": 8, "adjust": 0}
    shares = [a.pop("activeMs") for a in line["anki"]]
    assert line["anki"] == [
        {"cid": 1000, "nid": 2000, "ord": 0, "did": 1, "card_class": "new", **per_card},
        {"cid": 1001, "nid": 2001, "ord": 0, "did": 1, "card_class": "new", **per_card},
    ]
    # Active time: every gap between actions (the clock ticks 1 s per read).
    assert all(ms > 0 for ms in shares) and line["activeMs"] >= sum(shares)
    assert line["activeMs"] == ctrl.active_ms
    assert line["encode"] == {
        "encodeReps": 1,
        "chunkDifficulty": 100,
        "MIN_WORDS_TO_CHUNK": 8,
        "ladderMode": "cumulative",
        "batchSize": 0,
        "strictPunctuation": False,
        "stemTolerance": True,
        "hints": True,
    }
    assert line["scope"] == {"deckId": 42, "search": None}
    assert line["collisions"] == 0 and line["holdout"] == []
    saved = sessions.load(st, "deck-42")
    assert saved is not None
    assert saved["addon"]["historyWritten"] is True and saved["addon"]["handoffPending"] is True
    assert save_status(saved) == "handoff"
    with pytest.raises(ValueError, match="handoff"):
        open_saved(st, "deck-42", saved, ctrl.settings, Clock())
    assert history_store.get_cold_start_history(st, "deck-42") is not None
    # A second finish (e.g. a crash before historyWritten was saved) adds nothing.
    store.meta.history_written = False
    store.finish(ctrl, True)
    assert len(history_store.read_all(st, "42")) == 1
    # "Don't hand off" deletes the save.
    assert sessions.discard(st, "deck-42") and sessions.load(st, "deck-42") is None


def test_a_handoff_line_keeps_the_session_line(st: Storage) -> None:
    ctrl, store = _start(st, SHORT[:1], encodeReps=1)
    _finish(ctrl)
    st.append_jsonl(
        history_store.history_name("42"), {"type": "handoff", "sessionId": store.meta.session_id}
    )
    assert [x["type"] for x in history_store.read_all(st, "42")] == ["session", "handoff"]
    assert [x["type"] for x in history_store.read_recent(st, "42", 5)] == ["session"]
    assert history_store.read_recent(st, "42", 0) == []


def test_complete_handoff_writes_the_line_then_deletes_the_save(st: Storage) -> None:
    ctrl, store = _start(st, SHORT[:1], encodeReps=1)
    _finish(ctrl)
    saved = sessions.load(st, "deck-42")
    assert saved is not None
    line = {"type": "handoff", "sessionId": store.meta.session_id, "mode": "B"}
    sessions.complete_handoff(st, "deck-42", saved, line)
    assert sessions.load(st, "deck-42") is None
    assert history_store.read_all(st, "42")[-1] == line


def test_complete_handoff_deletes_the_save_even_if_the_line_fails(
    st: Storage, monkeypatch: pytest.MonkeyPatch
) -> None:
    ctrl, store = _start(st, SHORT[:1], encodeReps=1)
    _finish(ctrl)
    saved = sessions.load(st, "deck-42")
    assert saved is not None

    def fail(*_args: object) -> None:
        raise OSError("disk full")

    monkeypatch.setattr(st, "append_jsonl", fail)
    with pytest.raises(OSError, match="disk full"):
        sessions.complete_handoff(st, "deck-42", saved, {"type": "handoff"})
    assert sessions.load(st, "deck-42") is None


def test_decline_handoff(st: Storage) -> None:
    ctrl, store = _start(st, SHORT[:1], encodeReps=1)
    _finish(ctrl)
    saved = sessions.load(st, "deck-42")
    assert saved is not None
    sessions.decline_handoff(st, "deck-42", saved, 1_790_000_000_000)
    assert sessions.load(st, "deck-42") is None
    session_line, declined = history_store.read_all(st, "42")
    assert session_line["type"] == "session"
    assert declined["type"] == "handoff" and declined["declined"] is True
    assert declined["sessionId"] == store.meta.session_id


# ---------------------------------------------------------------------------
# Drill again
# ---------------------------------------------------------------------------


def test_drill_again_is_session_only(st: Storage) -> None:
    ctrl, store = _start(st, SHORT, encodeReps=1)
    while not (ctrl.state["phase"] == "final" and not ctrl.view().buttons.continue_):
        _answer_correctly(ctrl)
    ctrl.submit("nope")  # one miss in the Final check
    _finish(ctrl)
    assert ctrl.done_summary().drill_again
    again, again_store = start_drill_again(
        st,
        ctrl,
        store,
        ControllerSettings(deck_name="Med Term (missed cards)", source_deck_editable=False),
        Clock(),
    )
    assert again_store.meta.key == "again-deck-42"
    assert again_store.meta.drill_again_of == "deck-42"
    assert again_store.meta.session_id != store.meta.session_id
    assert len(again.state["items"]) == 1
    again.start()
    saved = sessions.load(st, "again-deck-42")
    assert saved is not None and saved["sourceDeckEditable"] is False
    assert saved["addon"]["drillAgainOf"] == "deck-42"
    _finish(again)
    assert sessions.load(st, "again-deck-42") is None  # deleted on completion
    assert len(history_store.read_all(st, "42")) == 1  # only the parent's
    assert sessions.load(st, "deck-42") is not None  # the parent waits for its handoff


def test_drill_again_needs_final_misses(st: Storage) -> None:
    ctrl, store = _start(st, SHORT[:1], encodeReps=1)
    _finish(ctrl)
    with pytest.raises(ValueError, match="no Final-check misses"):
        start_drill_again(st, ctrl, store, ControllerSettings(), Clock())


# ---------------------------------------------------------------------------
# Phase 5: holdout and the chunking threshold
# ---------------------------------------------------------------------------

HELD = [{"cid": 9001, "nid": 9101, "ord": 0, "did": 1, "card_class": "suspended_new"}]


def test_holdout_is_recorded_in_the_save_and_the_history_line(st: Storage) -> None:
    ctrl, store = start_session(
        st,
        key=deck_key(42),
        deck_items=SHORT[:2],
        sources=[source(i) for i in range(2)],
        config=config(encodeReps=1),
        scope=scope_json(deck_id=42),
        select_options=OPTIONS,
        deck_settings=DECK_SETTINGS,
        hints=True,
        settings=ControllerSettings(deck_name="Med Term"),
        now_ms=Clock(),
        holdout=HELD,
    )
    ctrl.start()
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["addon"]["holdout"] == HELD
    # It survives a resume.
    _, resumed = open_saved(st, "deck-42", saved, ctrl.settings, Clock())
    assert resumed.meta.holdout == HELD
    _finish(ctrl)
    (line,) = history_store.read_all(st, "42")
    assert line["holdout"] == HELD


def test_min_words_to_chunk_goes_into_the_session_and_survives_resume(st: Storage) -> None:
    long = [{"front": "long", "back": "alpha beta gamma delta epsilon"}, *SHORT[:1]]
    ctrl, _ = _start(st, long, minWordsToChunk=3, chunkDifficulty=35)
    assert ctrl.state["config"].get("minWordsToChunk") == 3
    assert ctrl.state["items"][0]["chunks"] is not None  # 5 words > 3
    ctrl.start()
    saved = sessions.load(st, "deck-42")
    assert saved is not None and saved["minWordsToChunk"] == 3
    resumed, _ = open_saved(st, "deck-42", saved, ctrl.settings, Clock())
    assert resumed.state["config"].get("minWordsToChunk") == 3
    # Without it (an older save, or the parity harness): the key stays absent.
    plain, _ = _start(st, long, chunkDifficulty=35)
    assert "minWordsToChunk" not in plain.state["config"]
    assert plain.state["items"][0]["chunks"] is None  # 5 words <= 8
    del saved["minWordsToChunk"]
    old, _ = open_saved(st, "deck-42", saved, ctrl.settings, Clock())
    assert "minWordsToChunk" not in old.state["config"]


def test_history_line_records_the_session_threshold(st: Storage) -> None:
    ctrl, _ = _start(st, SHORT[:2], encodeReps=1, minWordsToChunk=5)
    ctrl.start()
    _finish(ctrl)
    (line,) = history_store.read_all(st, "42")
    assert line["encode"]["MIN_WORDS_TO_CHUNK"] == 5


def test_drill_again_keeps_the_threshold(st: Storage) -> None:
    ctrl, store = _start(st, SHORT, encodeReps=1, minWordsToChunk=4)
    while not (ctrl.state["phase"] == "final" and not ctrl.view().buttons.continue_):
        _answer_correctly(ctrl)
    ctrl.submit("nope")  # one miss in the Final check
    _finish(ctrl)
    again, _ = start_drill_again(st, ctrl, store, ctrl.settings, Clock())
    assert again.state["config"].get("minWordsToChunk") == 4


def test_overrides_survive_save_resume_and_drill_again(st: Storage) -> None:
    """Phase 6: per-card overrides are stored on the items, so the save, a
    resume and a drill-again of the same cards keep them."""
    overrides: list[Any] = [{"encodeRepsOverride": 3, "minWordsToChunkOverride": 4}, {}, {}]
    ctrl, store = start_session(
        st,
        key=deck_key(42),
        deck_items=SHORT,
        sources=[source(i) for i in range(len(SHORT))],
        config=config(encodeReps=1),
        scope=scope_json(deck_id=42),
        select_options=OPTIONS,
        deck_settings=DECK_SETTINGS,
        hints=True,
        settings=ControllerSettings(deck_name="Med Term"),
        now_ms=Clock(),
        overrides=overrides,
    )
    ctrl.start()
    _answer_correctly(ctrl)
    saved = sessions.load(st, "deck-42")
    assert saved is not None
    assert saved["items"][0].get("encodeRepsOverride") == 3
    assert "encodeRepsOverride" not in saved["items"][1]
    resumed, _ = open_saved(st, "deck-42", saved, ControllerSettings(), Clock())
    first = resumed.state["items"][0]
    assert (first.get("encodeRepsOverride"), first.get("minWordsToChunkOverride")) == (3, 4)

    # Miss card 0 (and only card 0) in the Final check, then drill it again.
    for _ in range(200):
        if ctrl.state["phase"] == "final" and not ctrl.view().buttons.continue_:
            trial = select_trial(ctrl.state)
            assert trial is not None
            if trial["itemId"] == 0:
                break
        _answer_correctly(ctrl)
    ctrl.submit("nope")
    _finish(ctrl)
    again, _ = start_drill_again(st, ctrl, store, ctrl.settings, Clock())
    (item,) = again.state["items"]
    assert (item.get("encodeRepsOverride"), item.get("minWordsToChunkOverride")) == (3, 4)
