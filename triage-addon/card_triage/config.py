"""The add-on's config (``config.json``, edited in Tools → Card Triage → Settings…) (pure).

A missing or mistyped value takes its default, so a hand-edited config can't break reviewing.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .keys import check_key

DEFAULT_KEY = "x"
MIN_SECONDS = 5
MAX_SECONDS = 600
MIN_AGAINS = 1
MAX_AGAINS = 10


@dataclass(frozen=True)
class Config:
    set_aside_key: str = DEFAULT_KEY
    """The reviewer key that sets the current card aside."""
    timer_prompt: bool = False
    """Offer to set a card aside after ``timer_seconds`` on it."""
    timer_seconds: int = 30
    again_prompt: bool = False
    """Offer to set a learning card aside once it has ``again_count`` learn-type Agains."""
    again_count: int = 2


def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _key(value: Any, default: str) -> str:
    if not isinstance(value, str):
        return default
    checked = check_key(value)
    return checked.key if checked.ok else default


def parse_config(raw: Mapping[str, Any] | None) -> Config:
    raw = raw or {}
    d = Config()
    return Config(
        set_aside_key=_key(raw.get("set_aside_key"), d.set_aside_key),
        timer_prompt=_bool(raw.get("timer_prompt"), d.timer_prompt),
        timer_seconds=_int(raw.get("timer_seconds"), d.timer_seconds, MIN_SECONDS, MAX_SECONDS),
        again_prompt=_bool(raw.get("again_prompt"), d.again_prompt),
        again_count=_int(raw.get("again_count"), d.again_count, MIN_AGAINS, MAX_AGAINS),
    )
