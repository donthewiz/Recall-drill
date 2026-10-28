"""The set-aside marker in a card's ``custom_data`` (pure).

``custom_data`` is a JSON object kept as a string on the card. Card Triage owns one key, ``tri``,
whose value is the card's flag before it was set aside (0 to 7). Every other key is kept as is.
Anki limits ``custom_data`` to 100 bytes and a key to 8 bytes.
"""

from __future__ import annotations

import json
from typing import Any

MARKER_KEY = "tri"
MAX_CUSTOM_DATA_BYTES = 100
MAX_KEY_BYTES = 8
MAX_FLAG = 7
"""Anki's flags: 0 (none) and 1 to 7."""


def parse_custom_data(raw: str) -> dict[str, Any] | None:
    """The keys of a card's ``custom_data``; ``None`` if it isn't a JSON object."""
    if raw.strip() == "":
        return {}
    try:
        value = json.loads(raw)
    except ValueError:
        return None
    if not isinstance(value, dict):
        return None
    return {str(k): v for k, v in value.items()}  # pyright: ignore[reportUnknownVariableType, reportUnknownArgumentType]


def has_marker(data: dict[str, Any]) -> bool:
    return MARKER_KEY in data


def saved_flag(data: dict[str, Any]) -> int:
    """The flag saved in the marker; 0 if the marker is missing or holds anything but 0 to 7."""
    value = data.get(MARKER_KEY)
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value <= MAX_FLAG:
        return value
    return 0


def serialize(data: dict[str, Any]) -> str:
    """Compact JSON, as Anki writes it; ``""`` for no keys."""
    if not data:
        return ""
    return json.dumps(data, separators=(",", ":"), ensure_ascii=False)


def fits(data: dict[str, Any]) -> bool:
    """Whether ``data`` stays inside Anki's limits (total size and key size)."""
    if any(len(k.encode("utf-8")) > MAX_KEY_BYTES for k in data):
        return False
    return len(serialize(data).encode("utf-8")) <= MAX_CUSTOM_DATA_BYTES


def with_marker(data: dict[str, Any], flag: int) -> str | None:
    """``custom_data`` with the marker added and every other key kept; ``None`` if that would
    break Anki's limits."""
    new = {**data, MARKER_KEY: flag}
    return serialize(new) if fits(new) else None


def without_marker(data: dict[str, Any]) -> str:
    """``custom_data`` with the marker removed and every other key kept."""
    return serialize({k: v for k, v in data.items() if k != MARKER_KEY})
