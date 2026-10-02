"""The add-on's global config (``config.json``, edited in Tools > Add-ons > Config).

Pure: the UI passes in what ``mw.addonManager.getConfig`` returned. A missing
or mistyped value takes its default, so a hand-edited config can't stop a drill.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

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
    )
