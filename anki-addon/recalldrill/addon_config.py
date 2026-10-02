"""The add-on's global config (``config.json``, edited in Tools > Add-ons > Config).

Pure: the UI passes in what ``mw.addonManager.getConfig`` returned. A missing
or mistyped value takes its default, so a hand-edited config can't stop a drill.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from .deck_settings import HOLDOUT_MAX_PCT
from .difficulty import DifficultySettings
from .engine.items import MIN_WORDS_TO_CHUNK
from .engine.types import CycleOrder, LadderMode

HandoffMode = Literal["A", "B"]
"""How drilled new cards get their first Anki review (docs/DECISIONS.md, "Handoff: A vs B"):
A = ``set_due_date`` to tomorrow, B = front of the new queue, buried until tomorrow."""


@dataclass(frozen=True)
class AddonConfig:
    encode_reps: int = 3
    chunk_difficulty: float = 35
    batch_size: int = 5
    stem_tolerance: bool = True
    ladder_mode: LadderMode = "cumulative"
    cycle_order: CycleOrder = "shuffled"
    collision_catch: bool = True
    play_audio_on_feedback: bool = True
    autoplay_question_audio: bool = False
    handoff_mode: HandoffMode = "B"
    handoff_siblings: bool = True
    hard_threshold: int = 3
    clear_flag_on_handoff: bool = True
    tag_long: bool = False
    min_words_to_chunk: int = MIN_WORDS_TO_CHUNK
    """Answers with at most this many words are drilled whole (the engine's
    ``MIN_WORDS_TO_CHUNK``, passed per session as ``SessionConfig.minWordsToChunk``)."""
    holdout_pct: int = 0
    """Default percent of eligible new cards held out of the drill as a
    measurement control (0 = off). Deck scopes only (Phase 5). A deck's own
    ``holdoutPct`` (setup panel, Holdout %) wins."""
    holdout_exclude: bool = True
    """Leave cards tagged ``rd::holdout`` out of every selection."""
    min_n: int = 30
    """The tuning report's minimum sample per compared group."""
    difficulty_adjust: bool = True
    """Default for a deck's "Adjust reps by difficulty" (Phase 6)."""
    hard_d: float = 7
    """FSRS difficulty (1-10) at or above which a card gets one more rep and chunks earlier."""
    easy_d: float = 3
    """FSRS difficulty at or below which a card gets one fewer rep."""
    min_encode_reps: int = 2
    """An easy card's reps never go below this (nor below the deck's own, if lower)."""
    hard_chunk_shift: int = 2
    """A hard card's chunk threshold is the session's minus this (never under 4)."""
    skip_min_stability: float = 30
    """The ``stable`` class: FSRS stability at least this many days ..."""
    skip_max_difficulty: float = 5
    """... and difficulty at most this."""

    def difficulty(self, adjust: bool | None = None) -> DifficultySettings:
        """The difficulty rules; ``adjust`` (the deck's toggle) wins over the default."""
        return DifficultySettings(
            adjust=self.difficulty_adjust if adjust is None else adjust,
            hard_d=self.hard_d,
            easy_d=self.easy_d,
            min_encode_reps=self.min_encode_reps,
            hard_chunk_shift=self.hard_chunk_shift,
            skip_min_stability=self.skip_min_stability,
            skip_max_difficulty=self.skip_max_difficulty,
        )


DEFAULT_CONFIG = AddonConfig()


def _int(value: object, default: int, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    n = int(value)
    return n if lo <= n <= hi else default


def _float(value: object, default: float, lo: float, hi: float) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    x = float(value)
    return x if lo <= x <= hi else default


def _bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def parse_config(raw: object) -> AddonConfig:
    """``getConfig``'s dict (or None) -> :class:`AddonConfig`."""
    d: Mapping[str, Any] = cast(Mapping[str, Any], raw) if isinstance(raw, dict) else {}
    dc = DEFAULT_CONFIG
    batch = _int(d.get("batch_size"), dc.batch_size, 0, 10_000)
    ladder = d.get("ladder_mode")
    cycle = d.get("cycle_order")
    mode = d.get("handoff_mode")
    return AddonConfig(
        encode_reps=_int(d.get("encode_reps"), dc.encode_reps, 1, 10),
        chunk_difficulty=_int(d.get("chunk_difficulty"), int(dc.chunk_difficulty), 1, 100),
        batch_size=batch,
        stem_tolerance=_bool(d.get("stem_tolerance"), dc.stem_tolerance),
        ladder_mode=ladder if ladder in ("cumulative", "exhaustive") else dc.ladder_mode,
        cycle_order=cycle if cycle in ("shuffled", "inOrder") else dc.cycle_order,
        collision_catch=_bool(d.get("collision_catch"), dc.collision_catch),
        play_audio_on_feedback=_bool(d.get("play_audio_on_feedback"), dc.play_audio_on_feedback),
        autoplay_question_audio=_bool(d.get("autoplay_question_audio"), dc.autoplay_question_audio),
        handoff_mode=mode if mode in ("A", "B") else dc.handoff_mode,
        handoff_siblings=_bool(d.get("handoff_siblings"), dc.handoff_siblings),
        hard_threshold=_int(d.get("hard_threshold"), dc.hard_threshold, 1, 1000),
        clear_flag_on_handoff=_bool(d.get("clear_flag_on_handoff"), dc.clear_flag_on_handoff),
        tag_long=_bool(d.get("tag_long"), dc.tag_long),
        min_words_to_chunk=_int(d.get("min_words_to_chunk"), dc.min_words_to_chunk, 1, 100),
        holdout_pct=_int(d.get("holdout_pct"), dc.holdout_pct, 0, HOLDOUT_MAX_PCT),
        holdout_exclude=_bool(d.get("holdout_exclude"), dc.holdout_exclude),
        min_n=_int(d.get("min_n"), dc.min_n, 1, 100_000),
        difficulty_adjust=_bool(d.get("difficulty_adjust"), dc.difficulty_adjust),
        hard_d=_float(d.get("hard_d"), dc.hard_d, 1, 10),
        easy_d=_float(d.get("easy_d"), dc.easy_d, 1, 10),
        min_encode_reps=_int(d.get("min_encode_reps"), dc.min_encode_reps, 1, 10),
        hard_chunk_shift=_int(d.get("hard_chunk_shift"), dc.hard_chunk_shift, 0, 100),
        skip_min_stability=_float(d.get("skip_min_stability"), dc.skip_min_stability, 0, 1_000_000),
        skip_max_difficulty=_float(d.get("skip_max_difficulty"), dc.skip_max_difficulty, 1, 10),
    )
