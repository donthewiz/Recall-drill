"""DrillController: SessionView's behavior, checked through view() and effects."""

from __future__ import annotations

import copy
from typing import Any

import pytest
from controller_support import LONG, SHORT, Harness, config, make, phase_state, source

from recalldrill import controller as controller_module
from recalldrill.controller import (
    COLLISION_MESSAGE,
    ClearInput,
    CollisionNotice,
    ControllerSettings,
    DrillController,
    Persisted,
    PersistFailed,
    PlayAnswerAudio,
    SessionComplete,
    SessionStopped,
    StartDwell,
)
from recalldrill.engine import rand
from recalldrill.engine.session import DWELL_MS, apply_answer, select_trial
from recalldrill.engine.types import DeckItem, SessionState
from recalldrill.sessions import new_session_state, resume

# ---------------------------------------------------------------------------
# Construction
# ---------------------------------------------------------------------------


def test_controller_rejects_no_items() -> None:
    # The engine's empty-deck path enters the Final check with no current card
    # and never completes (Phase 1b), so the controller refuses it up front.
    with pytest.raises(ValueError, match="at least one card"):
        make([])


def test_controller_needs_a_source_per_item() -> None:
    with pytest.raises(ValueError, match="sources"):
        make(SHORT, sources=[source(0)])


def test_start_persists_the_initial_state() -> None:
    h = make()
    assert h.ctrl.start() == [Persisted()]
    assert len(h.saves) == 1
    saved = h.saves[0]
    assert saved["phase"] == "encode" and saved["currentId"] == 0
    assert saved["deckName"] == "Test deck"
    assert saved["stats"]["startTime"] == 1_790_000_000_000
    assert [s["cid"] for s in saved["addon"]["sources"]] == [1000, 1001, 1002]
    assert saved["addon"]["collisions"] == 0


# ---------------------------------------------------------------------------
# The first trial and the view
# ---------------------------------------------------------------------------


def test_first_trial_view() -> None:
    v = make().ctrl.view()
    assert v.mode == "trial"
    assert (v.item_id, v.cid, v.prompt) == (0, 1000, "heart")
    assert v.front_html == "<b>front 0</b>" and v.css == ".card {}"
    assert v.label == "Full Recall" and v.detail == "Encoding • Full item"
    # C5: attempt 0 has a first-letter cue.
    assert v.cue.kind == "firstLetter" and v.sub_text == v.cue.text == v.placeholder
    assert v.cue_badge == "First-Letter Cue"
    assert v.check_label == "Check answer" and not v.input_read_only
    b = v.buttons
    assert (b.check, b.reveal, b.override, b.continue_, b.edit, b.next_batch, b.save) == (
        True,
        True,
        False,
        False,
        True,
        False,
        True,
    )
    assert v.stats.text == "Attempts: 0 • Misses: 0" and v.stats.accuracy_percent == 100
    assert (v.progress.total, v.progress.encoding, v.progress.new) == (3, 1, 2)
    assert v.batch_label == "" and not v.progress.is_batched
    assert [d.current for d in v.dots] == [True, False, False]
    assert v.dots[0].title == "heart: encoding"


def test_blind_trial_view() -> None:
    h = make()
    h.submit()  # attempt 0 right: the next rep of this card is blind
    h.run_until(lambda c: select_trial(c.state)["cue"]["kind"] == "none")  # type: ignore[index]
    v = h.ctrl.view()
    assert v.cue.kind == "none" and v.sub_text == ""
    assert v.placeholder == "Type the full answer from memory..."
    assert v.cue_badge == "Blind Recall"
    assert v.blind_hint.startswith("Type from pure active recall")


def test_presentation_beat_view_and_submit_ignores_typing() -> None:
    h = make(LONG, chunkDifficulty=35)
    v = h.ctrl.view()
    assert v.cue.kind == "present" and v.input_read_only
    assert v.placeholder == "Press Enter to continue" and v.check_label == "Continue"
    assert v.cue_badge == "Read & Continue" and v.sub_text == h.target()
    assert not v.buttons.reveal  # nothing to reveal: it's all shown
    assert h.ctrl.reveal() == [] and not h.ctrl.view().revealed
    out = h.ctrl.submit("anything at all")
    assert StartDwell(DWELL_MS["chunks-presented"]) in out
    assert h.ctrl.view().feedback is not None
    assert h.ctrl.view().feedback.verdict == "presented"  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Dwell, the busy guard
# ---------------------------------------------------------------------------


def test_correct_answer_dwells_with_its_key_then_commits() -> None:
    h = make()
    before = h.ctrl.state
    out = h.ctrl.submit("cardi")
    assert out == [Persisted(), StartDwell(DWELL_MS["full-streak-progress"])]
    # During the dwell the answered trial stays on screen.
    assert h.ctrl.state is before
    v = h.ctrl.view()
    assert v.mode == "feedback" and v.processing
    assert v.feedback is not None and v.feedback.type == "success"
    assert v.feedback.verdict == "exact"
    assert not any(
        (v.buttons.check, v.buttons.reveal, v.buttons.continue_, v.buttons.edit, v.buttons.save)
    )
    # The save already holds the advanced state.
    assert h.saves[-1]["stats"]["attempts"] == 1
    out = h.ctrl.dwell_elapsed()
    assert out == [ClearInput()]  # already saved: no second persist
    assert h.ctrl.state is not before and h.ctrl.state["stats"]["attempts"] == 1
    assert h.ctrl.view().mode == "trial" and not h.ctrl.processing
    assert h.ctrl.dwell_elapsed() == []


def test_reveal_dwell_uses_the_revealed_reset_key() -> None:
    h = make()
    h.ctrl.reveal()
    out = h.ctrl.submit("cardi")
    assert StartDwell(DWELL_MS["revealed-reset"]) in out


def test_chunk_advance_dwell_key() -> None:
    h = make(LONG, chunkDifficulty=35)
    h.submit()  # the presentation beat
    out = h.ctrl.submit(h.target())
    assert StartDwell(DWELL_MS["chunks-advance"]) in out


def test_double_submit_is_ignored_while_processing() -> None:
    h = make()
    first = h.ctrl.submit("cardi")
    assert first
    saves = len(h.saves)
    # B5: a fast second Enter during the dwell does nothing...
    assert h.ctrl.submit("cardi") == []
    # ...and neither does anything else.
    assert h.ctrl.reveal() == []
    assert h.ctrl.override() == []
    assert h.ctrl.continue_() == []
    assert h.ctrl.next_batch() == []
    assert h.ctrl.save_and_stop() == []
    assert h.ctrl.begin_edit() is None
    assert len(h.saves) == saves
    h.ctrl.dwell_elapsed()
    assert h.ctrl.state["stats"]["attempts"] == 1


def test_double_continue_applies_next_once(monkeypatch: pytest.MonkeyPatch) -> None:
    h = make(state=phase_state(SHORT, "cycle"))
    calls: list[SessionState] = []
    real = controller_module.apply_next

    def spy(state: SessionState) -> SessionState:
        calls.append(state)
        return real(state)

    monkeypatch.setattr(controller_module, "apply_next", spy)
    h.submit()  # cycle: manual advance
    assert h.ctrl.continue_()
    assert h.ctrl.continue_() == []
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# Wrong, override
# ---------------------------------------------------------------------------


def test_wrong_in_encode_waits_for_continue_without_apply_next(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(controller_module, "apply_next", lambda s: pytest.fail("applyNext"))
    h = make()
    out = h.ctrl.submit("nope")
    assert out == [Persisted()]  # no dwell: a wrong verdict is a manual advance
    v = h.ctrl.view()
    assert v.mode == "feedback" and v.feedback is not None
    assert v.feedback.type == "danger" and v.feedback.diff
    assert v.buttons.continue_ and v.buttons.override and not v.buttons.check
    assert h.ctrl.pre_wrong_state is not None
    state = h.ctrl.state
    assert h.ctrl.continue_() == [ClearInput()]
    assert h.ctrl.state is state  # same trial, streak reset
    assert h.ctrl.view().mode == "trial"


def test_wrong_then_override_counts_as_correct() -> None:
    h = make()
    pre = h.ctrl.state
    h.ctrl.submit("nope")
    assert h.ctrl.state["stats"]["misses"] == 1
    out = h.ctrl.override()
    assert out[0] == Persisted()
    assert StartDwell(DWELL_MS["full-streak-progress"]) in out
    h.do(h.ctrl.dwell_elapsed())
    # As if the pre-answer state had been answered correctly, minus the attempt.
    correct = apply_answer(pre, "cardi", revealed=False)["state"]
    assert h.ctrl.state["currentId"] == correct["currentId"]
    got = next(i for i in h.ctrl.state["items"] if i["id"] == 0)
    want = next(i for i in correct["items"] if i["id"] == 0)
    assert got["encodeStreak"] == want["encodeStreak"] == 1
    assert h.ctrl.state["stats"] == {**pre["stats"], "overrides": 1}
    assert h.ctrl.view().stats.text == "Attempts: 0 • Misses: 0 • Overrides: 1"
    # The dwell ends with Continue down (SessionView leaves it up: see the docstring).
    v = h.ctrl.view()
    assert v.mode == "trial" and v.buttons.check and not v.buttons.continue_


def test_override_is_unavailable_once_continue_is_pressed() -> None:
    h = make()
    h.ctrl.submit("nope")
    h.ctrl.continue_()
    assert not h.ctrl.view().buttons.override
    state = h.ctrl.state
    assert h.ctrl.override() == []
    assert h.ctrl.state is state and h.ctrl.pre_wrong_state is None


def test_override_is_only_offered_after_a_wrong_verdict() -> None:
    h = make()
    assert h.ctrl.override() == []
    h.ctrl.submit("the cardi")  # near (a stop word): not wrong
    assert h.ctrl.view().feedback.verdict == "near"  # type: ignore[union-attr]
    assert not h.ctrl.view().buttons.override


def test_override_in_the_cycle_waits_for_continue() -> None:
    h = make(state=phase_state(SHORT, "cycle"))
    h.ctrl.submit("nope")
    out = h.ctrl.override()
    assert out == [Persisted()]  # the cycle is always a manual advance
    v = h.ctrl.view()
    assert v.feedback is not None and v.feedback.verdict == "exact"
    assert v.buttons.continue_ and not v.buttons.override


# ---------------------------------------------------------------------------
# Reveal
# ---------------------------------------------------------------------------


def test_reveal_then_submit_is_revealed_not_a_miss() -> None:
    h = make()
    assert h.ctrl.reveal() == []
    v = h.ctrl.view()
    assert v.revealed and v.sub_text == "cardi" and v.placeholder == "cardi"
    assert v.cue_badge == "" and not v.buttons.reveal
    h.ctrl.submit("cardi")
    v = h.ctrl.view()
    assert v.feedback is not None and v.feedback.verdict == "revealed"
    assert h.saves[-1]["stats"]["misses"] == 0 and h.saves[-1]["stats"]["reveals"] == 1
    h.ctrl.dwell_elapsed()
    assert not h.ctrl.view().revealed  # consumed by that answer


def test_reveal_is_ignored_while_feedback_waits_for_continue() -> None:
    h = make()
    h.ctrl.submit("nope")
    assert not h.ctrl.view().buttons.reveal
    h.ctrl.reveal()
    assert not h.ctrl.view().revealed


def test_cycle_wrong_needs_continue_and_calls_apply_next(monkeypatch: pytest.MonkeyPatch) -> None:
    h = make(state=phase_state(SHORT, "cycle"))
    calls: list[SessionState] = []
    real = controller_module.apply_next
    monkeypatch.setattr(controller_module, "apply_next", lambda s: calls.append(s) or real(s))
    out = h.ctrl.submit("nope")
    assert not any(isinstance(e, StartDwell) for e in out)
    shown = h.ctrl.state
    assert h.ctrl.view().buttons.continue_
    h.ctrl.continue_()
    assert calls == [shown]
    assert h.ctrl.state["currentId"] != shown["currentId"]


def test_final_wrong_needs_continue_and_calls_apply_next(monkeypatch: pytest.MonkeyPatch) -> None:
    h = make(state=phase_state(SHORT, "cycle"))
    h.run_until(lambda c: c.state["phase"] == "final" and not c.view().buttons.continue_)
    assert h.ctrl.view().label == "Final check"
    calls: list[SessionState] = []
    real = controller_module.apply_next
    monkeypatch.setattr(controller_module, "apply_next", lambda s: calls.append(s) or real(s))
    out = h.ctrl.submit("nope")
    assert out == [Persisted()]
    h.ctrl.continue_()
    assert len(calls) == 1


# ---------------------------------------------------------------------------
# The Extra pause and audio
# ---------------------------------------------------------------------------

WITH_EXTRA: list[DeckItem] = [
    {"front": "heart", "back": "cardi", "extra": "as in cardiology"},
    SHORT[1],
]


def test_extra_pause_holds_the_advanced_state_until_continue() -> None:
    h = make(WITH_EXTRA, sources=[source(0, extra_html="as in <i>cardiology</i>"), source(1)])
    shown = h.ctrl.state
    out = h.ctrl.submit("cardi")
    assert out == [Persisted()]  # no dwell: the Extra holds it
    assert h.ctrl.state is shown
    held = h.ctrl.pending_advance_state
    assert held is not None and held["stats"]["attempts"] == 1
    assert h.saves[-1]["stats"]["attempts"] == 1
    v = h.ctrl.view()
    assert v.mode == "feedback" and v.extra == "as in cardiology"
    assert v.extra_html == "as in <i>cardiology</i>"
    assert v.buttons.continue_ and not v.buttons.edit and not v.buttons.check
    assert h.ctrl.begin_edit() is None
    out = h.ctrl.continue_()
    assert out == [ClearInput()]  # the held state was saved at submit
    assert h.ctrl.state is held and h.ctrl.pending_advance_state is None
    assert h.ctrl.view().extra is None


def test_extra_is_hidden_until_feedback() -> None:
    h = make(WITH_EXTRA)
    assert h.ctrl.view().extra is None


def test_image_only_extra_holds_the_pause_too() -> None:
    sources = [source(0, extra_html='<img src="heart.png">'), source(1), source(2)]
    h = make(SHORT, sources=sources)
    h.ctrl.submit("cardi")
    assert h.ctrl.pending_advance_state is not None
    v = h.ctrl.view()
    assert v.extra == "" and v.extra_html == '<img src="heart.png">'


def test_no_extra_pause_on_a_chunk() -> None:
    deck: list[DeckItem] = [{**LONG[0], "extra": "note"}]
    h = make(deck, chunkDifficulty=35)
    h.submit()  # presentation beat
    out = h.ctrl.submit(h.target())
    assert any(isinstance(e, StartDwell) for e in out)
    assert h.ctrl.view().extra is None and not h.ctrl.view().shows_full_back


def test_answer_audio_plays_when_feedback_shows_the_full_back() -> None:
    h = make(sources=[source(0, has_audio=True), source(1), source(2)])
    out = h.ctrl.submit("cardi")
    assert out == [Persisted(), PlayAnswerAudio(1000), StartDwell(500)]


def test_answer_audio_setting_off() -> None:
    settings = ControllerSettings(play_audio_on_feedback=False)
    h = make(sources=[source(0, has_audio=True), source(1), source(2)], settings=settings)
    assert not any(isinstance(e, PlayAnswerAudio) for e in h.ctrl.submit("cardi"))


def test_no_answer_audio_on_a_chunk_or_without_audio() -> None:
    h = make(LONG, chunkDifficulty=35, sources=[source(0, has_audio=True)])
    assert not any(isinstance(e, PlayAnswerAudio) for e in h.ctrl.submit(""))
    h = make()
    assert not any(isinstance(e, PlayAnswerAudio) for e in h.ctrl.submit("cardi"))


def test_answer_audio_plays_on_a_manual_cycle_verdict() -> None:
    h = make(
        state=phase_state(SHORT, "cycle"), sources=[source(i, has_audio=True) for i in range(3)]
    )
    cid = h.ctrl.view().cid
    assert PlayAnswerAudio(cid) in h.ctrl.submit("nope")  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# Editing
# ---------------------------------------------------------------------------


def test_edit_with_a_wrong_verdict_showing_updates_the_pre_wrong_state() -> None:
    h = make()
    h.ctrl.submit("nope")
    req = h.ctrl.begin_edit()
    assert req is not None and (req.cid, req.front, req.back) == (1000, "heart", "cardi")
    assert h.ctrl.view().editing and not h.ctrl.view().buttons.override
    assert h.ctrl.submit("cardi") == [] and h.ctrl.continue_() == []
    new_src = source(0, front_html="<b>the heart</b>")
    out = h.ctrl.apply_card_edit("the heart", "cardi", "", new_src)
    assert Persisted() in out
    pre = h.ctrl.pre_wrong_state
    assert pre is not None
    assert next(i for i in pre["items"] if i["id"] == 0)["front"] == "the heart"
    v = h.ctrl.view()
    assert not v.editing and v.buttons.override and v.feedback is not None
    assert not v.revealed  # feedback was showing: nothing newly seen
    assert h.saves[-1]["addon"]["sources"][0]["front_html"] == "<b>the heart</b>"
    # Count as correct now credits the edited card.
    h.ctrl.override()
    h.ctrl.dwell_elapsed()
    item = next(i for i in h.ctrl.state["items"] if i["id"] == 0)
    assert item["front"] == "the heart" and item["encodeStreak"] == 1


def test_edit_that_restarts_clears_the_pre_wrong_state() -> None:
    h = make()
    h.ctrl.submit("nope")
    h.ctrl.begin_edit()
    out = h.ctrl.apply_card_edit("heart", "cardio", "")
    assert ClearInput() in out and Persisted() in out
    assert h.ctrl.pre_wrong_state is None
    v = h.ctrl.view()
    assert v.mode == "trial" and v.feedback is None and not v.buttons.override
    assert not v.buttons.continue_ and v.buttons.check and not v.revealed


def test_edit_on_a_pending_attempt_reveals_it() -> None:
    # editRevealsOnClose: the editor showed the full answer.
    h = make()
    h.ctrl.begin_edit()
    h.ctrl.apply_card_edit("the heart", "cardi", "")
    assert h.ctrl.view().revealed
    h.ctrl.submit("cardi")
    assert h.ctrl.view().feedback.verdict == "revealed"  # type: ignore[union-attr]


def test_cancelled_edit_on_a_pending_attempt_reveals_it_too() -> None:
    h = make()
    h.ctrl.begin_edit()
    assert h.ctrl.cancel_edit() == []
    assert h.ctrl.view().revealed and not h.ctrl.view().editing
    assert h.ctrl.cancel_edit() == []


def test_restarting_edit_on_a_pending_attempt_does_not_reveal() -> None:
    h = make()
    h.ctrl.begin_edit()
    h.ctrl.apply_card_edit("heart", "cardio", "")
    assert not h.ctrl.view().revealed


def test_edit_with_an_empty_answer_is_a_cancel() -> None:
    h = make()
    h.ctrl.begin_edit()
    state = h.ctrl.state
    assert h.ctrl.apply_card_edit("heart", "  ", "") == []
    assert h.ctrl.state is state and not h.ctrl.view().editing


def test_apply_card_edit_needs_begin_edit() -> None:
    h = make()
    assert h.ctrl.apply_card_edit("x", "y", "") == []


def test_unchanged_edit_with_a_new_source_still_saves_it() -> None:
    h = make(state=phase_state(SHORT, "cycle"))
    h.ctrl.submit("nope")
    h.ctrl.begin_edit()
    trial = select_trial(h.ctrl.state)
    assert trial is not None
    item = next(i for i in h.ctrl.state["items"] if i["id"] == trial["itemId"])
    saves = len(h.saves)
    out = h.ctrl.apply_card_edit(item["front"], item["back"], "", source(trial["itemId"], css="x"))
    assert out == [Persisted()] or Persisted() in out
    assert len(h.saves) == saves + 1


def test_edit_is_disabled_in_the_final_check() -> None:
    h = make(state=phase_state(SHORT, "cycle"))
    h.run_until(lambda c: c.state["phase"] == "final" and not c.view().buttons.continue_)
    assert not h.ctrl.view().buttons.edit
    assert h.ctrl.begin_edit() is None


def test_edit_is_disabled_on_the_interstitial() -> None:
    h = make(SHORT + [{"front": "lung", "back": "pneum"}], encodeReps=1, batchSize=2)
    h.run_until(lambda c: c.state["phase"] == "batch-done")
    assert not h.ctrl.view().buttons.edit and h.ctrl.begin_edit() is None


# ---------------------------------------------------------------------------
# Persist and resume
# ---------------------------------------------------------------------------


def test_persist_after_every_answer_and_the_save_round_trips() -> None:
    h = make(SHORT + LONG, chunkDifficulty=35, encodeReps=2)
    answers = 0
    for typed in ["cardi", None, "nope", None, None, "hepat", None, None, None]:
        if h.ctrl.view().buttons.continue_:
            h.ctrl.continue_()
        saves = len(h.saves)
        h.submit(typed)
        answers += 1
        assert len(h.saves) == saves + 1, f"answer {answers}"
    if h.ctrl.view().buttons.continue_:
        h.ctrl.continue_()
    assert h.ctrl.state["phase"] == "encode"
    view = h.ctrl.view()
    saved = copy.deepcopy(h.saves[-1])
    assert saved["currentId"] == h.ctrl.state["currentId"]
    again = DrillController(
        resume(saved),
        h.ctrl.sources,
        ControllerSettings(deck_name="Test deck"),
        lambda d: None,
        lambda: 0,
    )
    assert again.view() == view


def test_a_failed_persist_is_reported_and_the_drill_goes_on() -> None:
    def broken(saved: dict[str, Any]) -> None:
        raise OSError("disk full")

    h = make(persist=broken)
    out = h.ctrl.submit("cardi")
    assert PersistFailed("disk full") in out
    assert StartDwell(500) in out
    h.ctrl.dwell_elapsed()
    assert h.ctrl.state["stats"]["attempts"] == 1


def test_saved_dict_is_the_app_shape() -> None:
    h = make()
    saved = h.ctrl.saved_dict()
    assert set(saved) == {
        "deckName",
        "phase",
        "queue",
        "stats",
        "items",
        "encodeReps",
        "chunkDifficulty",
        "stemTolerance",
        "ladderMode",
        "strictPunctuation",
        "cycleOrder",
        "batchIndex",
        "batchSize",
        "batchStartStats",
        "currentId",
        "sourceDeckEditable",
        "timestamp",
        "addon",
    }
    assert saved["sourceDeckEditable"] is True
    # The saved items are copies: later engine states can't change a save.
    saved["items"][0]["front"] = "changed"
    assert h.ctrl.state["items"][0]["front"] == "heart"


# ---------------------------------------------------------------------------
# Batches, stop, completion
# ---------------------------------------------------------------------------

FOUR = SHORT + [{"front": "lung", "back": "pneum"}]


def _to_batch_done() -> Harness:
    h = make(FOUR, encodeReps=1, batchSize=2)
    h.run_until(lambda c: c.state["phase"] == "batch-done")
    return h


def test_batch_done_view_then_next_batch() -> None:
    h = _to_batch_done()
    v = h.ctrl.view()
    assert v.mode == "batch_done" and v.detail == "Batch 1 of 2 complete"
    assert v.batch_done is not None
    assert (v.batch_done.batch_number, v.batch_done.total_batches) == (1, 2)
    assert v.batch_done.items_mastered == 2 and v.batch_done.batch_size == 2
    assert v.batch_done.accuracy_percent == 100
    assert v.batch_done.remaining is not None
    assert v.batch_done.remaining.startswith("Remaining time, recalibrated from this session: ")
    assert v.buttons.next_batch and v.buttons.save and not v.buttons.check
    assert v.progress.is_batched and v.progress.batch_number == 1
    out = h.ctrl.next_batch()
    assert Persisted() in out
    assert h.ctrl.state["phase"] == "encode" and h.ctrl.state["batchIndex"] == 1
    v = h.ctrl.view()
    assert v.mode == "trial" and v.batch_label == "Batch 2/2"
    assert h.ctrl.next_batch() == []


def test_save_and_stop_on_the_interstitial() -> None:
    h = _to_batch_done()
    out = h.ctrl.save_and_stop()
    assert out == [Persisted(), SessionStopped()]
    assert h.finishes == [False]
    assert h.saves[-1]["phase"] == "batch-done"
    assert h.ctrl.finished == "stopped" and h.ctrl.view().mode == "done"
    assert h.ctrl.next_batch() == [] and h.ctrl.save_and_stop() == []
    resumed = resume(h.saves[-1])
    assert resumed["phase"] == "batch-done" and resumed["batchIndex"] == 0
    done = h.ctrl.done_summary()
    assert not done.is_complete and done.title == "Session Saved"
    assert done.summary.startswith("2 of 4 items mastered so far (0 misses).")
    assert done.drill_again == ()


def test_end_session_mid_trial_saves_the_shown_state() -> None:
    h = make()
    h.submit("cardi")
    out = h.ctrl.save_and_stop()
    assert SessionStopped() in out and h.saves[-1]["stats"]["attempts"] == 1


def test_completion_emits_session_complete_once() -> None:
    h = make(SHORT[:2], encodeReps=1)
    h.run_until(lambda c: c.finished is not None)
    assert h.effects.count(SessionComplete()) == 1
    assert h.finishes == [True]
    assert h.ctrl.finished == "complete" and h.ctrl.view().mode == "done"
    assert h.saves[-1]["currentId"] == -1
    # Nothing more happens.
    assert h.ctrl.submit("x") == [] and h.ctrl.continue_() == [] and h.ctrl.start() == []
    done = h.ctrl.done_summary()
    assert done.is_complete and done.title == "Deck Mastered!"
    assert done.summary.startswith("Terrific work! All 2 items")
    assert done.accuracy_line == "0 misses • 0 reveals"


def test_resuming_a_completed_state_finishes_at_start() -> None:
    h = make(SHORT[:2], encodeReps=1)
    h.run_until(lambda c: c.finished is not None)
    again = make(state=resume(h.saves[-1]), sources=h.ctrl.sources)
    assert SessionComplete() in again.ctrl.start()
    assert again.finishes == [True]


# ---------------------------------------------------------------------------
# The other card's answer
# ---------------------------------------------------------------------------

ARTERY: list[DeckItem] = [
    {"front": "blood vessel (1 form)", "back": "artery"},
    {"front": "x", "back": "y"},
]


def _collision_harness(**kw: Any) -> Harness:
    sources = [source(0, colliding_answers=("arteries", "vein")), source(1)]
    return make(ARTERY, sources=sources, **kw)


def test_collision_catch_notice_and_no_trial() -> None:
    h = _collision_harness()
    state = h.ctrl.state
    saves = len(h.saves)
    out = h.ctrl.submit("Arteries")
    assert out == [CollisionNotice("arteries"), ClearInput()]
    assert out[0].message == COLLISION_MESSAGE  # type: ignore[union-attr]
    assert COLLISION_MESSAGE == (
        "That's the answer to another card with this prompt. This one wants a different form."
    )
    assert h.ctrl.state is state and len(h.saves) == saves
    assert h.ctrl.collisions == 1
    v = h.ctrl.view()
    assert v.notice == COLLISION_MESSAGE and v.mode == "trial" and v.feedback is None
    # The next real answer clears the notice and saves the tally.
    h.ctrl.submit("artery")
    assert h.ctrl.view().notice is None
    assert h.saves[-1]["addon"]["collisions"] == 1


def test_collision_catch_keeps_a_reveal() -> None:
    h = _collision_harness()
    h.ctrl.reveal()
    h.ctrl.submit("vein")
    assert h.ctrl.view().revealed


def test_collision_catch_ignores_the_cards_own_answer() -> None:
    sources = [source(0, colliding_answers=("artery!",)), source(1)]
    h = make(ARTERY, sources=sources)
    out = h.ctrl.submit("artery")
    assert not any(isinstance(e, CollisionNotice) for e in out)


def test_collision_catch_is_strict_when_the_deck_is() -> None:
    sources = [source(0, colliding_answers=("artery-a",)), source(1)]
    h = make(ARTERY, sources=sources, strictPunctuation=True)
    out = h.ctrl.submit("artery a")  # not exact under strict punctuation
    assert not any(isinstance(e, CollisionNotice) for e in out)


def test_collision_catch_setting_off() -> None:
    h = _collision_harness(settings=ControllerSettings(collision_catch=False))
    out = h.ctrl.submit("arteries")
    assert not any(isinstance(e, CollisionNotice) for e in out)
    assert h.ctrl.view().feedback is not None


def test_collision_catch_only_on_whole_answer_trials() -> None:
    sources = [source(0, colliding_answers=("too much",))]
    h = make(LONG, chunkDifficulty=35, sources=sources)
    h.submit()  # presentation beat
    out = h.ctrl.submit("too much")  # a chunk trial
    assert not any(isinstance(e, CollisionNotice) for e in out)


def test_collision_catch_in_cycle_and_final() -> None:
    state = phase_state(ARTERY, "cycle")
    sources = [source(0, colliding_answers=("arteries",)), source(1, colliding_answers=("z",))]
    h = make(state=state, sources=sources)
    other = "arteries" if h.ctrl.view().item_id == 0 else "z"
    assert isinstance(h.ctrl.submit(other)[0], CollisionNotice)
    h.run_until(lambda c: c.state["phase"] == "final" and not c.view().buttons.continue_)
    other = "arteries" if h.ctrl.view().item_id == 0 else "z"
    assert isinstance(h.ctrl.submit(other)[0], CollisionNotice)
    assert h.ctrl.collisions == 2


# ---------------------------------------------------------------------------
# The done screen
# ---------------------------------------------------------------------------


def test_done_summary_struggles_and_final_misses() -> None:
    with rand.seeded(7):
        h = make(SHORT, encodeReps=1)
        h.submit("nope")
        h.ctrl.continue_()
        h.ctrl.reveal()
        h.submit()
        h.run_until(lambda c: c.state["phase"] == "final" and not c.view().buttons.continue_)
        missed = h.ctrl.view().item_id
        h.ctrl.submit("nope")
        h.run_until(lambda c: c.finished is not None)
    done = h.ctrl.done_summary()
    assert done.is_complete
    assert [m.item_id for m in done.missed_in_final] == [missed]
    assert done.missed_in_final[0].final_misses == 1
    assert done.drill_again == (missed,)
    assert done.drill_again_label == "Drill this card again"
    first = done.hardest[0]
    assert first.item_id in (0, missed)
    assert "tries" in first.parts and first.cid == 1000 + first.item_id
    zero = next(c for c in done.hardest if c.item_id == 0)
    assert zero.parts.startswith("1 miss • 1 reveal")
    assert done.accuracy_line.startswith("2 misses • 1 reveal")
    assert done.accuracy_line.endswith("don’t count toward accuracy")
    deck, sources = h.ctrl.drill_again_input()
    assert [d["back"] for d in deck] == [SHORT[missed]["back"]]  # type: ignore[index]
    assert [s.cid for s in sources] == [1000 + missed]  # type: ignore[operator]


def test_done_summary_lists_near_and_overrides() -> None:
    h = make(SHORT[:1], encodeReps=1)
    h.ctrl.submit("the cardi")  # near
    h.ctrl.dwell_elapsed()
    h.ctrl.submit("nope")
    h.ctrl.override()
    h.ctrl.dwell_elapsed()
    line = h.ctrl.done_summary().accuracy_line
    assert "1 near" in line and "1 override" in line


def test_new_session_state_keeps_deck_order() -> None:
    c = config(batchSize=2)
    del c["cycleOrder"]
    s = new_session_state(SHORT, c, 5)
    assert [i["id"] for i in s["items"]] == [0, 1, 2]
    assert s["stats"].get("startTime") == 5 and s["config"].get("cycleOrder") == "shuffled"
