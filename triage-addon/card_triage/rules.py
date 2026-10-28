"""What may be set aside and when to offer it (pure)."""

from __future__ import annotations

from enum import Enum

CARD_NEW = 0
CARD_LEARNING = 1
QUEUE_SUSPENDED = -1

SET_ASIDE_FLAG = 1
"""Red: the visible mark on a set-aside card."""
TAG = "triage"
"""The visible mark on a set-aside card's note."""


class Verdict(Enum):
    OK = "ok"
    NOT_NEW_OR_LEARNING = "not_new_or_learning"
    ALREADY_SET_ASIDE = "already_set_aside"
    SUSPENDED = "suspended"
    TOO_BIG = "too_big"
    UNREADABLE = "unreadable"


TOOLTIP_SET_ASIDE = "Set aside. Ctrl+Z to undo."
TOOLTIP_NOT_ELIGIBLE = "Card Triage sets aside only new and learning cards."
TOOLTIP_NONE_SET_ASIDE = "No set-aside cards."
TOOLTIP_TOO_BIG = "Can't set aside: this card's custom data has no room for the marker."
TOOLTIP_UNREADABLE = "Can't set aside: this card's custom data can't be read."
TOOLTIP_SUSPENDED = "This card is already suspended."
TOOLTIP_ALREADY = "This card is already set aside."


def tooltip_for(verdict: Verdict) -> str:
    return {
        Verdict.OK: TOOLTIP_SET_ASIDE,
        Verdict.NOT_NEW_OR_LEARNING: TOOLTIP_NOT_ELIGIBLE,
        Verdict.ALREADY_SET_ASIDE: TOOLTIP_ALREADY,
        Verdict.SUSPENDED: TOOLTIP_SUSPENDED,
        Verdict.TOO_BIG: TOOLTIP_TOO_BIG,
        Verdict.UNREADABLE: TOOLTIP_UNREADABLE,
    }[verdict]


def release_question(count: int) -> str:
    noun = "card" if count == 1 else "cards"
    return f"Release {count} set-aside {noun}? They go back to where they were."


def set_aside_verdict(card_type: int, queue: int, marked: bool) -> Verdict:
    """Whether a card may be set aside: new (type 0) or learning (type 1) only; review and
    relearning cards are left alone, and so is a card that already has the marker."""
    if marked:
        return Verdict.ALREADY_SET_ASIDE
    if card_type not in (CARD_NEW, CARD_LEARNING):
        return Verdict.NOT_NEW_OR_LEARNING
    if queue == QUEUE_SUSPENDED:
        return Verdict.SUSPENDED
    return Verdict.OK


def prompt_eligible(card_type: int, queue: int, marked: bool) -> bool:
    """Whether the reviewer should offer to set this card aside."""
    return set_aside_verdict(card_type, queue, marked) is Verdict.OK


def timer_due(elapsed_seconds: float, limit_seconds: int) -> bool:
    """The timer prompt is due once the card has been on screen ``limit_seconds``."""
    return elapsed_seconds >= limit_seconds


def again_prompt_due(card_type: int, again_count: int, threshold: int) -> bool:
    """The Again-count prompt: a learning card (type 1) with at least ``threshold`` learn-type
    Agains in its history."""
    return card_type == CARD_LEARNING and again_count >= threshold
