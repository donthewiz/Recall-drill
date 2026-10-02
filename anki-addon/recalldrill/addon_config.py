"""The add-on's global config (``config.json``, edited in Tools > Add-ons > Config).

Pure: the UI passes in what ``mw.addonManager.getConfig`` returned. A missing
or mistyped value takes its default, so a hand-edited config can't stop a drill.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from .engine.types import CycleOrder, LadderMode


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


DEFAULT_CONFIG = AddonConfig()


def _int(value: object, default: int, lo: int, hi: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int | float):
        return default
    n = int(value)
    return n if lo <= n <= hi else default


def _bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def parse_config(raw: object) -> AddonConfig:
    """``getConfig``'s dict (or None) -> :class:`AddonConfig`."""
    d: Mapping[str, Any] = cast(Mapping[str, Any], raw) if isinstance(raw, dict) else {}
    dc = DEFAULT_CONFIG
    batch = _int(d.get("batch_size"), dc.batch_size, 0, 10_000)
    ladder = d.get("ladder_mode")
    cycle = d.get("cycle_order")
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
    )
