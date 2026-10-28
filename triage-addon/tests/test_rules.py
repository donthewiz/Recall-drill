from __future__ import annotations

import pytest

from card_triage import rules
from card_triage.rules import Verdict


@pytest.mark.parametrize(
    ("card_type", "queue", "marked", "verdict"),
    [
        (0, 0, False, Verdict.OK),
        (1, 1, False, Verdict.OK),
        (1, 3, False, Verdict.OK),  # a learning card on the day-learn queue
        (2, 2, False, Verdict.NOT_NEW_OR_LEARNING),
        (3, 1, False, Verdict.NOT_NEW_OR_LEARNING),
        (0, 0, True, Verdict.ALREADY_SET_ASIDE),
        (2, -1, True, Verdict.ALREADY_SET_ASIDE),
        (0, -1, False, Verdict.SUSPENDED),
    ],
)
def test_set_aside_verdict(card_type: int, queue: int, marked: bool, verdict: Verdict) -> None:
    assert rules.set_aside_verdict(card_type, queue, marked) is verdict
    assert rules.prompt_eligible(card_type, queue, marked) is (verdict is Verdict.OK)


def test_tooltips_say_what_the_spec_says() -> None:
    assert rules.tooltip_for(Verdict.OK) == "Set aside. Ctrl+Z to undo."
    assert (
        rules.tooltip_for(Verdict.NOT_NEW_OR_LEARNING)
        == "Card Triage sets aside only new and learning cards."
    )
    assert rules.TOOLTIP_NONE_SET_ASIDE == "No set-aside cards."
    assert (
        rules.release_question(7)
        == "Release 7 set-aside cards? They go back to where they were."
    )
    assert rules.release_question(1).startswith("Release 1 set-aside card?")


@pytest.mark.parametrize(
    ("elapsed", "limit", "due"), [(0, 30, False), (29.9, 30, False), (30, 30, True), (95, 30, True)]
)
def test_timer_due_after_n_seconds(elapsed: float, limit: int, due: bool) -> None:
    assert rules.timer_due(elapsed, limit) is due


@pytest.mark.parametrize(
    ("card_type", "count", "threshold", "due"),
    [
        (1, 1, 2, False),
        (1, 2, 2, True),
        (1, 5, 2, True),
        (0, 9, 2, False),  # new card: not learning
        (2, 9, 2, False),
        (3, 9, 2, False),
    ],
)
def test_again_count_prompt(card_type: int, count: int, threshold: int, due: bool) -> None:
    assert rules.again_prompt_due(card_type, count, threshold) is due
