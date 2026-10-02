"""Per-card encode reps and chunk threshold from what Anki knows of the card (pure).

docs/DECISIONS.md, "Difficulty adjustment (Phase 6)". The engine takes the
result as each item's optional ``encodeRepsOverride`` /
``minWordsToChunkOverride`` (docs/DECISIONS.md, "Engine extensions").

The rules, first match wins:

- **FSRS memory state** (``memory_state``, D on its 1-10 scale, not the 0-1
  ``prop:d`` search scale):
  - ``D >= hard_d``: one more rep, and the card chunks earlier (its threshold
    is the session's minus ``hard_chunk_shift``, never under
    :data:`MIN_CHUNK_THRESHOLD`, never above the session's);
  - ``D <= easy_d``: one fewer rep, never under ``min_encode_reps`` (or under
    the deck's own reps when those are already lower: a deck drilled at 1
    stays at 1), and never under 1;
  - otherwise no change.
- **No FSRS state, but reviewed before** (``reps > 0``): ``lapses >= 3``, or an
  SM-2 ease under 200% (``factor`` 1-1999), or the ``leech`` tag: one more rep.
- **New card**: no change. New cards, most of what gets drilled, have no FSRS
  data, so they keep the session's word-count and ``chunkDifficulty`` rules.

:func:`is_stable` is the ``stable`` class (``anki_io/cards.classify``): FSRS
says the card is already well learned, so a drill would spend trials on it for
nothing. Off by default in selection.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from .card_state import CardSnapshot, has_tag
from .engine.types import ItemOverrides

HARD_D = 7.0
EASY_D = 3.0
MIN_ENCODE_REPS = 2
HARD_CHUNK_SHIFT = 2
MIN_CHUNK_THRESHOLD = 4
"""A hard card's chunk threshold never goes below this many words."""
SKIP_MIN_STABILITY = 30.0
SKIP_MAX_DIFFICULTY = 5.0
HISTORY_LAPSES = 3
"""Without FSRS: this many lapses or more makes a card hard."""
HISTORY_FACTOR = 2000
"""Without FSRS: an SM-2 ease factor under this (200%) makes a card hard."""
LEECH_TAG = "leech"


@dataclass(frozen=True)
class DifficultySettings:
    adjust: bool = True
    """``difficulty_adjust`` (config default; the deck's own toggle wins)."""
    hard_d: float = HARD_D
    easy_d: float = EASY_D
    min_encode_reps: int = MIN_ENCODE_REPS
    hard_chunk_shift: int = HARD_CHUNK_SHIFT
    skip_min_stability: float = SKIP_MIN_STABILITY
    skip_max_difficulty: float = SKIP_MAX_DIFFICULTY


Basis = Literal["off", "new", "fsrs", "history"]
"""What the decision rests on: adjustment switched off, a new card (no data),
the FSRS memory state, or the review history without FSRS."""


@dataclass(frozen=True)
class CardAdjustment:
    """One card's effective encode reps and chunk threshold, and why."""

    basis: Basis
    encode_reps: int
    """The reps this card's ``encodeReps`` steps need."""
    min_words_to_chunk: int
    """This card's chunk threshold (answers with at most this many words are
    drilled whole)."""
    deck_reps: int
    deck_min_words: int
    fsrs_d: float | None = None
    fsrs_s: float | None = None

    @property
    def adjustment(self) -> int:
        """+1, 0 or -1: more, the deck's, or fewer reps."""
        return (self.encode_reps > self.deck_reps) - (self.encode_reps < self.deck_reps)

    @property
    def chunks_earlier(self) -> bool:
        return self.min_words_to_chunk < self.deck_min_words

    def overrides(self) -> ItemOverrides:
        """The engine fields: only what differs from the session's values."""
        out: ItemOverrides = {}
        if self.encode_reps != self.deck_reps:
            out["encodeRepsOverride"] = self.encode_reps
        if self.min_words_to_chunk != self.deck_min_words:
            out["minWordsToChunkOverride"] = self.min_words_to_chunk
        return out


def is_stable(
    snap: CardSnapshot,
    min_stability: float = SKIP_MIN_STABILITY,
    max_difficulty: float = SKIP_MAX_DIFFICULTY,
) -> bool:
    """FSRS present, ``S >= min_stability`` days, ``D <= max_difficulty``, not a leech."""
    if snap.fsrs_d is None or snap.fsrs_s is None:
        return False
    return (
        snap.fsrs_s >= min_stability
        and snap.fsrs_d <= max_difficulty
        and not has_tag(snap.tags, LEECH_TAG)
    )


def easy_reps(deck_reps: int, min_encode_reps: int) -> int:
    """One fewer, but never under ``min_encode_reps`` (or the deck's own reps, when
    those are already lower) and never under 1."""
    floor = max(1, min(min_encode_reps, deck_reps))
    return max(deck_reps - 1, floor)


def hard_threshold(deck_min_words: int, shift: int) -> int:
    """The session's threshold minus ``shift``, never under
    :data:`MIN_CHUNK_THRESHOLD` and never above the session's."""
    return min(deck_min_words, max(MIN_CHUNK_THRESHOLD, deck_min_words - shift))


def history_hard(snap: CardSnapshot) -> bool:
    """Without FSRS: lapsed 3+ times, an ease under 200%, or tagged ``leech``."""
    return (
        snap.lapses >= HISTORY_LAPSES
        or 0 < snap.factor < HISTORY_FACTOR
        or has_tag(snap.tags, LEECH_TAG)
    )


def adjust_card(
    snap: CardSnapshot | None,
    deck_reps: int,
    deck_min_words: int,
    settings: DifficultySettings = DifficultySettings(),  # noqa: B008 (frozen)
) -> CardAdjustment:
    """The card's encode reps and chunk threshold (see the module docstring)."""

    def result(basis: Basis, reps: int = deck_reps, words: int = deck_min_words) -> CardAdjustment:
        return CardAdjustment(
            basis,
            reps,
            words,
            deck_reps,
            deck_min_words,
            snap.fsrs_d if snap is not None else None,
            snap.fsrs_s if snap is not None else None,
        )

    if snap is None:
        return result("new")
    if not settings.adjust:
        return result("off")
    if snap.fsrs_d is not None:
        d = snap.fsrs_d
        if d >= settings.hard_d:
            return result(
                "fsrs",
                deck_reps + 1,
                hard_threshold(deck_min_words, settings.hard_chunk_shift),
            )
        if d <= settings.easy_d:
            return result("fsrs", easy_reps(deck_reps, settings.min_encode_reps))
        return result("fsrs")
    if snap.reps > 0:
        return result("history", deck_reps + 1 if history_hard(snap) else deck_reps)
    return result("new")


@dataclass(frozen=True)
class DifficultySummary:
    """The setup panel's line."""

    plus: int
    """Cards drilled with one more rep."""
    minus: int
    """Cards drilled with one fewer rep."""
    chunk_earlier: int
    """Cards whose chunk threshold is lower than the session's."""
    new_cards: int
    """Cards with no review data: unchanged."""
    adjusted_on: bool

    def text(self) -> str:
        if not self.adjusted_on:
            return "Difficulty adjustment off: every card uses the deck's reps and chunking."
        return (
            f"Difficulty-adjusted: {_cards(self.plus)} +1 rep, {_cards(self.minus)} −1 rep, "
            f"{_cards(self.chunk_earlier)} chunk earlier. "
            f"New cards ({self.new_cards}): no FSRS data, unchanged."
        )


def _cards(n: int) -> str:
    return f"{n} card" if n == 1 else f"{n} cards"


def summarize(adjustments: Iterable[CardAdjustment], adjusted_on: bool) -> DifficultySummary:
    plus = minus = earlier = new = 0
    for a in adjustments:
        plus += a.adjustment > 0
        minus += a.adjustment < 0
        earlier += a.chunks_earlier
        new += a.basis == "new"
    return DifficultySummary(plus, minus, earlier, new, adjusted_on)
