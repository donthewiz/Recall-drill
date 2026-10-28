"""When the bar shows, on a stand-in reviewer: timer, Again count, dismiss, next card."""

from __future__ import annotations

from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

pytest.importorskip("aqt")

from card_triage import bar  # noqa: E402
from card_triage.config import Config  # noqa: E402
from card_triage.ui import entry  # noqa: E402
from card_triage.ui.prompt import PromptController  # noqa: E402


def card(cid: int, type_: int = 0, queue: int | None = None, custom_data: str = "") -> Any:
    return SimpleNamespace(
        id=cid, type=type_, queue=type_ if queue is None else queue, custom_data=custom_data
    )


class Rig:
    def __init__(self, cfg: Config, agains: dict[int, int] | None = None) -> None:
        self.cfg = cfg
        self.agains = agains or {}
        self.js: list[str] = []
        self.scheduled: list[tuple[int, Callable[[], None]]] = []
        self.cancels = 0
        self.current: int | None = None
        self.set_asides = 0
        self.prompt = PromptController(
            config=lambda: self.cfg,
            run_js=self.js.append,
            again_count=lambda cid: self.agains.get(cid, 0),
            schedule=lambda s, fn: self.scheduled.append((s, fn)),
            cancel=self._cancel,
            current_card_id=lambda: self.current,
            set_aside=self._set_aside,
        )

    def _cancel(self) -> None:
        self.cancels += 1
        self.scheduled.clear()

    def _set_aside(self) -> None:
        self.set_asides += 1

    def show(self, c: Any) -> None:
        self.current = c.id
        self.prompt.question_shown(c)

    def bars(self) -> list[str]:
        return [j for j in self.js if "createElement" in j]


def test_everything_is_off_by_default() -> None:
    rig = Rig(Config(), agains={1: 9})
    rig.show(card(1, type_=1))
    assert rig.scheduled == [] and rig.bars() == []


def test_timer_prompt_waits_n_seconds_then_shows_the_bar() -> None:
    rig = Rig(Config(timer_prompt=True, timer_seconds=45))
    rig.show(card(1))
    assert [s for s, _ in rig.scheduled] == [45]
    assert rig.bars() == []
    rig.scheduled[0][1]()
    (js,) = rig.bars()
    assert "Stuck on this one?" in js and "Set aside (X)" in js and "Keep going" in js


def test_timer_counts_through_the_answer_side_and_a_redraw_does_not_restart_it() -> None:
    rig = Rig(Config(timer_prompt=True))
    c = card(1)
    rig.show(c)
    before = list(rig.scheduled)
    rig.prompt.question_shown(c)  # the same card drawn again (edit, refresh)
    assert rig.scheduled == before
    rig.scheduled[0][1]()  # the answer side was showing by now: the bar still comes
    assert len(rig.bars()) == 1


def test_timer_firing_for_another_card_shows_nothing() -> None:
    rig = Rig(Config(timer_prompt=True))
    rig.show(card(1))
    fire = rig.scheduled[0][1]
    rig.current = 2  # the reviewer moved on without telling us
    fire()
    assert rig.bars() == []


def test_next_card_removes_the_bar_and_cancels_the_timer() -> None:
    rig = Rig(Config(timer_prompt=True))
    rig.show(card(1))
    rig.scheduled[0][1]()
    rig.js.clear()
    cancels = rig.cancels
    rig.show(card(2))
    assert rig.js[0] == bar.hide_js()
    assert rig.cancels > cancels
    assert [s for s, _ in rig.scheduled] == [30]  # a fresh clock for the new card


def test_answering_clears_the_card_so_the_same_card_coming_back_is_fresh() -> None:
    rig = Rig(Config(timer_prompt=True))
    rig.show(card(1, type_=1))
    rig.prompt.card_answered()
    assert rig.js[-1] == bar.hide_js()
    rig.show(card(1, type_=1))  # the learning card is due again at once
    assert [s for s, _ in rig.scheduled] == [30]


def test_keep_going_hides_the_bar_and_it_does_not_come_back_for_this_card() -> None:
    rig = Rig(Config(timer_prompt=True))
    c = card(1)
    rig.show(c)
    rig.scheduled[0][1]()
    fire = rig.scheduled[0][1] if rig.scheduled else (lambda: None)
    rig.prompt.command(bar.CMD_KEEP_GOING)
    assert rig.js[-1] == bar.hide_js()
    n = len(rig.bars())
    fire()
    rig.prompt.question_shown(c)
    assert len(rig.bars()) == n


def test_keep_going_before_the_bar_stops_the_timer() -> None:
    rig = Rig(Config(timer_prompt=True))
    rig.show(card(1))
    fire = rig.scheduled[0][1]
    rig.prompt.command(bar.CMD_KEEP_GOING)
    fire()
    assert rig.bars() == []


def test_set_aside_button_is_the_key() -> None:
    rig = Rig(Config())
    rig.prompt.command(bar.CMD_SET_ASIDE)
    assert rig.set_asides == 1


@pytest.mark.parametrize("type_", [2, 3])
def test_review_and_relearning_cards_are_never_offered(type_: int) -> None:
    rig = Rig(Config(timer_prompt=True, again_prompt=True), agains={1: 9})
    rig.show(card(1, type_=type_))
    assert rig.scheduled == [] and rig.bars() == []


def test_a_card_with_the_marker_is_never_offered() -> None:
    rig = Rig(Config(timer_prompt=True))
    rig.show(card(1, custom_data='{"tri":0}'))
    assert rig.scheduled == []


def test_again_prompt_shows_at_once_on_a_learning_card_at_the_threshold() -> None:
    rig = Rig(Config(again_prompt=True, again_count=2, timer_prompt=True), agains={1: 2})
    rig.show(card(1, type_=1))
    (js,) = rig.bars()
    assert "2 Agains on this card." in js and "Set aside (X)" in js
    assert rig.scheduled == []  # the bar is up: no second prompt from the timer


def test_again_prompt_below_the_threshold_or_on_a_new_card_shows_nothing() -> None:
    rig = Rig(Config(again_prompt=True, again_count=3), agains={1: 2, 2: 5})
    rig.show(card(1, type_=1))
    rig.show(card(2, type_=0))
    assert rig.bars() == []


def test_below_the_threshold_the_timer_still_applies() -> None:
    rig = Rig(Config(again_prompt=True, again_count=3, timer_prompt=True), agains={1: 1})
    rig.show(card(1, type_=1))
    assert [s for s, _ in rig.scheduled] == [30]


# the JS message filter --------------------------------------------------------------------


def test_filter_passes_other_messages_unchanged_and_claims_ours(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rig = Rig(Config())
    monkeypatch.setattr(entry, "_prompt", rig.prompt)
    passed = (False, None)
    other = (True, "someone else's answer")
    for msg in ("mathpath:open", "mp:field:1", "ease3", "", "cardtriage:set_aside"):
        assert entry.on_js_message(passed, msg, None) is passed
        assert entry.on_js_message(other, msg, None) is other
    assert rig.set_asides == 0

    assert entry.on_js_message(passed, bar.CMD_SET_ASIDE, None) == (True, None)
    assert rig.set_asides == 1
    assert entry.on_js_message(passed, bar.PREFIX + "unknown", None) == (True, None)
