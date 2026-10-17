"""The add-on's global config (``config.json``, edited in Tools > Add-ons > Config) (pure).

A missing or mistyped value takes its default, so a hand-edited config can't stop a session.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

MIN_SESSION = 1
MAX_SESSION = 12


@dataclass(frozen=True)
class Config:
    problems_per_session: int = 3
    """Recipes a learn session takes from a section (1 to 12)."""
    auto_open_in_review: bool = True
    """Open the Math Path window by itself when the reviewer shows a Math Path card."""
    prereq_lock: bool = True
    """A recipe whose prerequisite (a recipe that is a Math Path note) isn't learned is locked."""


def _int(value: Any, default: int, low: int, high: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        return default
    return max(low, min(high, value))


def _bool(value: Any, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def parse_config(raw: Mapping[str, Any] | None) -> Config:
    raw = raw or {}
    d = Config()
    return Config(
        problems_per_session=_int(
            raw.get("problems_per_session"), d.problems_per_session, MIN_SESSION, MAX_SESSION
        ),
        auto_open_in_review=_bool(raw.get("auto_open_in_review"), d.auto_open_in_review),
        prereq_lock=_bool(raw.get("prereq_lock"), d.prereq_lock),
    )
