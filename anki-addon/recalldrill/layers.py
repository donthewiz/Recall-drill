"""The anki-cards skill's layers (v0.3.1, pure).

The skill tags each note ``Layer::1`` … ``Layer::4``. A deck drilled **by layer**
goes Layer 1 of every chapter, then Layer 2, and so on: deck order and the
progress table both read the layer here. docs/DECISIONS.md, "v0.3.1: layers".
"""

from __future__ import annotations

import re
from collections.abc import Iterable

_LAYER_RE = re.compile(r"^layer::(\d+)$", re.IGNORECASE)

NO_LAYER_RANK = 1 << 62
"""Sorts a note without a layer after every numbered layer."""


def layer_of(tags: Iterable[str]) -> int | None:
    """The ``N`` of a note tag ``Layer::N`` (case-insensitive, N a positive
    integer); the lowest when there are several; None when there is none."""
    found = [
        n
        for t in tags
        if (m := _LAYER_RE.match(t.strip())) is not None and (n := int(m.group(1))) > 0
    ]
    return min(found) if found else None


def section_label(tag: str) -> str:
    """A session's "Only with tag" as the windows name its section: "Layer 2" for ``Layer::2``,
    else the tag itself ("" for none)."""
    tag = tag.strip()
    layer = layer_of([tag]) if tag else None
    return f"Layer {layer}" if layer is not None else tag


def layer_rank(tags: Iterable[str]) -> int:
    """:func:`layer_of` as a sort key: no layer sorts last."""
    layer = layer_of(tags)
    return NO_LAYER_RANK if layer is None else layer
