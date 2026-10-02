"""Phase 3b: what the drill window needs from the controller, and its HTML.

The Qt window only renders; the decisions it relies on are tested here:
audio and flash effects, the answer side of image cards, the hint, and the
HTML ``drill_view`` builds from a view.
"""

from __future__ import annotations

from html import escape

from controller_support import LONG, SHORT, make, source

from recalldrill.card_html import answer_side, display_extra, display_front, same_content
from recalldrill.controller import (
    ControllerSettings,
    Flash,
    PlayQuestionAudio,
    StartDwell,
    StopAudio,
)
from recalldrill.drill_view import (
    EDITING_NOTICE,
    batch_done_html,
    diff_html,
    done_html,
    render,
    render_call,
    shell_body,
)
from recalldrill.engine.session import select_trial
from recalldrill.engine.types import DeckItem

IMG_FRONT = '<div class="hdr">Bone</div><img src="osteon.png"><div class="ob a"></div>'
IMG_ANSWER = (
    '<div class="hdr">Bone</div><img src="osteon.png"><div class="ob"></div><p>Osteon</p>'
    "<hr id=answer><div class='extra'>The unit of compact bone.</div>"
)


def _identity(html: str) -> str:
    return html


# -- flash -----------------------------------------------------------------


def test_flash_green_on_correct_red_on_wrong_and_override() -> None:
    h = make()
    assert h.ctrl.submit("cardi")[0] == Flash(True)
    h.ctrl.dwell_elapsed()
    wrong = h.ctrl.submit("nope")
    assert wrong[0] == Flash(False)
    assert h.ctrl.override()[0] == Flash(True)


def test_no_flash_on_a_presentation_beat() -> None:
    h = make(LONG, chunkDifficulty=35)
    assert h.ctrl.view().cue.kind == "present"
    assert not any(isinstance(e, Flash) for e in h.ctrl.submit(""))


def test_a_revealed_answer_flashes_red() -> None:
    h = make()
    h.ctrl.reveal()
    assert h.ctrl.submit("cardi")[0] == Flash(False)


# -- audio -----------------------------------------------------------------


def _card_of(h: object) -> int:
    trial = select_trial(getattr(h, "ctrl").state)  # noqa: B009
    assert trial is not None
    return trial["itemId"]


def test_stop_audio_only_when_another_card_comes_up() -> None:
    h = make(encodeReps=1)
    h.do(h.ctrl.start())
    first = _card_of(h)
    out = h.submit()  # correct, dwell, next trial
    assert _card_of(h) != first
    assert StopAudio() in out
    # The same card again (one card, two reps): nothing stops.
    h2 = make(SHORT[:1], encodeReps=2)
    h2.do(h2.ctrl.start())
    out2 = h2.submit()
    assert _card_of(h2) == 0 and StopAudio() not in out2


def test_question_audio_autoplay_is_off_by_default() -> None:
    h = make(encodeReps=1)
    assert not any(isinstance(e, PlayQuestionAudio) for e in h.ctrl.start() + h.submit())


def test_question_audio_autoplay_plays_once_per_card() -> None:
    settings = ControllerSettings(deck_name="T", autoplay_question_audio=True)
    one = make(SHORT[:1], encodeReps=2, settings=settings)
    assert PlayQuestionAudio(1000) in one.ctrl.start()
    out = one.submit()  # streak 1 of 2: the same card
    assert _card_of(one) == 0
    assert not any(isinstance(e, PlayQuestionAudio) for e in out)
    h = make(encodeReps=1, settings=settings)
    h.ctrl.start()
    out = h.submit()  # the next card comes up
    plays = [e for e in out if isinstance(e, PlayQuestionAudio)]
    assert len(plays) == 1 and plays[0].cid == 1000 + _card_of(h) != 1000


def test_replay_side_follows_the_feedback() -> None:
    h = make()
    assert h.ctrl.view().audio_side == "q"
    h.ctrl.submit("nope")  # feedback on a full-answer trial
    assert h.ctrl.view().audio_side == "a"


def test_replay_side_stays_on_the_question_for_a_chunk() -> None:
    h = make(LONG, chunkDifficulty=35)
    h.submit()  # presentation beat
    h.ctrl.submit("zzz")  # a chunk, not the full back
    assert h.ctrl.view().audio_side == "q"


# -- display fields ----------------------------------------------------------


def test_view_carries_hint_and_card_ord() -> None:
    h = make(sources=[source(0, hint=" (-a___)", ord=1), source(1), source(2)])
    v = h.ctrl.view()
    assert v.hint == " (-a___)" and v.card_ord == 1


def test_image_card_feedback_shows_the_answer_side() -> None:
    srcs = [
        source(0, front_html=IMG_FRONT, answer_html=IMG_ANSWER, image_front=True),
        source(1),
        source(2),
    ]
    h = make(sources=srcs)
    assert h.ctrl.view().answer_html is None  # not before answering
    out = h.ctrl.submit("cardi")
    assert any(isinstance(e, StartDwell) for e in out)
    shown = h.ctrl.view().answer_html
    assert shown is not None and "<p>Osteon</p>" in shown and "compact bone" not in shown


def test_text_card_feedback_has_no_answer_side() -> None:
    h = make()
    h.ctrl.submit("nope")
    assert h.ctrl.view().answer_html is None


def test_image_card_chunk_feedback_has_no_answer_side() -> None:
    srcs = [source(0, front_html=IMG_FRONT, answer_html=IMG_ANSWER, image_front=True)]
    h = make(LONG, sources=srcs, chunkDifficulty=35)
    h.submit()  # presentation beat
    h.ctrl.submit("zzz")
    assert h.ctrl.view().answer_html is None


# -- card_html ---------------------------------------------------------------


def test_display_front_drops_type_box_and_appends_hint() -> None:
    front = "pain<br>[[type:FrontText]][anki:play:q:0]"
    out = display_front(front, " (-a___)")
    assert "[[type:" not in out and "[anki:play:q:0]" in out
    assert out.endswith('<span class="rd-hint"> (-a___)</span>')
    assert display_front("a<b>", " (x<y)").endswith("(x&lt;y)</span>")
    assert display_front("pain", "") == "pain"


def test_display_extra_drops_sound_references() -> None:
    assert display_extra("<i>see</i> [sound:x.mp3]") == "<i>see</i> "


def test_answer_side_lookalike_shows_the_part_before_the_rule() -> None:
    assert answer_side(IMG_FRONT, IMG_ANSWER) == IMG_ANSWER.split("<hr id=answer>")[0]


def test_answer_side_frontside_template_shows_the_back() -> None:
    front = '<img src="a.png"> What is this?'
    answer = '<img src="a.png"> What is this?\n\n<hr id=answer>\n\nFemur'
    assert answer_side(front, answer).strip() == "Femur"
    # FrontSide renders with the answer side's play markers.
    assert same_content(front + "[anki:play:q:0]", front + "[anki:play:a:0]")


def test_answer_side_without_a_rule_or_with_nothing_before_it() -> None:
    assert answer_side("q", "just the answer") == "just the answer"
    assert answer_side("q", "<hr id=answer>Back") == "Back"


# -- drill_view ----------------------------------------------------------------


def test_diff_colors_mark_missed_words_only() -> None:
    html = diff_html([{"word": "osseous", "matched": True}, {"word": "tis<sue", "matched": False}])
    assert '<span class="rd-w">osseous</span>' in html
    assert '<span class="rd-w rd-miss">tis&lt;sue</span>' in html


def test_card_render_uses_card_css_body_class_and_prepare() -> None:
    srcs = [source(0, css=".card{color:red}", hint=" (h)"), source(1), source(2)]
    h = make(sources=srcs)
    h.ctrl.submit("nope")
    seen: list[str] = []

    def prepare(html: str) -> str:
        seen.append(html)
        return html

    p = render(h.ctrl.view(), prepare, "card card1 nightMode")
    assert p["css"] == ".card{color:red}" and p["bodyClass"] == "card card1 nightMode"
    assert "<b>front 0</b>" in p["html"] and "(h)" in p["html"]
    assert 'class="rd-fb rd-fb-danger"' in p["html"] and "rd-miss" in p["html"]
    assert seen and seen[0].startswith("<b>front 0</b>")
    assert render_call(p).startswith("rdRender({")


def test_card_render_shows_cue_extra_answer_side_and_editing() -> None:
    srcs = [
        source(0, front_html=IMG_FRONT, answer_html=IMG_ANSWER, image_front=True),
        source(1, extra_html="<i>as in cardiology</i> [sound:c.mp3]"),
        source(2),
    ]
    h = make(SHORT, sources=srcs)
    first = render(h.ctrl.view(), _identity, "card card1")["html"]
    assert "rd-blind" in first or "rd-cue" in first
    h.ctrl.submit("cardi")
    html = render(h.ctrl.view(), _identity, "card card1")["html"]
    assert 'class="rd-answer"' in html and "<p>Osteon</p>" in html
    assert h.ctrl.begin_edit() is None  # mid-dwell: no editing
    h.ctrl.dwell_elapsed()
    assert h.ctrl.begin_edit() is not None
    assert escape(EDITING_NOTICE) in render(h.ctrl.view(), _identity, "card card1")["html"]


def test_extra_html_is_shown_with_its_formatting() -> None:
    deck: list[DeckItem] = [{"front": "heart", "back": "cardi", "extra": "as in cardiology"}]
    h = make(deck, sources=[source(0, extra_html="<i>as in cardiology</i> [sound:c.mp3]")])
    h.ctrl.submit("cardi")
    html = render(h.ctrl.view(), _identity, "card card1")["html"]
    assert '<span class="rd-extra-label">Extra</span><i>as in cardiology</i>' in html
    assert "[sound:" not in html


def test_batch_and_done_screens() -> None:
    h = make(batchSize=3, encodeReps=1)
    h.run_until(lambda c: c.finished is not None)
    summary = h.ctrl.done_summary()
    html = done_html(summary)
    assert summary.title in html and "Accuracy" in html
    p = render(h.ctrl.view(), _identity, "nightMode", summary)
    assert p["css"] == "" and p["html"] == html

    h2 = make(SHORT + [{"front": "lung", "back": "pneum"}], batchSize=3, encodeReps=1)
    h2.run_until(lambda c: c.state["phase"] == "batch-done")
    v = h2.ctrl.view()
    assert v.batch_done is not None
    assert "Batch 1 of 2 complete!" in batch_done_html(v.batch_done)
    assert render(v, _identity, "")["html"] == batch_done_html(v.batch_done)


def test_done_screen_lists_final_misses() -> None:
    h = make(encodeReps=1)
    h.run_until(lambda c: c.state["phase"] == "final" and not c.view().buttons.continue_)
    h.ctrl.submit("nope")
    h.ctrl.continue_()
    h.run_until(lambda c: c.finished is not None)
    html = done_html(h.ctrl.done_summary())
    assert "Missed in final check" in html and "Where you struggled" in html


def test_shell_has_the_render_and_flash_functions() -> None:
    body = shell_body(400)
    assert "function rdRender(p)" in body and "function rdFlash(ok)" in body
    assert "}, 400);" in body and "rd-card-css" in body
