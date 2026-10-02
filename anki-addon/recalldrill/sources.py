"""Where each engine item came from (pure).

``SourceRef`` is built by ``anki_io/build.py`` and read by the drill controller
and the session saves, which must not import anki. So it lives here, with its
JSON round trip (``sessions/<key>.json`` keeps the session's sources).
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, cast, get_args

CardClass = Literal[
    "in_filtered_deck",
    "buried",
    "flagged",
    "leech",
    "suspended_new",
    "suspended_review",
    "lapsed",
    "learning",
    "new",
    "young",
    "mature",
]
"""A card's class (``anki_io/cards.py``, ``classify``)."""


@dataclass(frozen=True)
class SourceRef:
    """Where engine item ``i`` came from, and what to display for it."""

    cid: int
    nid: int
    ord: int
    did: int
    """The card's home deck (its original deck while in a filtered deck)."""
    ntid: int
    card_class: CardClass
    flags: int
    front_html: str
    """Anki's rendered question, as-is. Still holds ``[anki:play:q:N]`` and
    ``[[type:F]]`` placeholders for the display layer to deal with."""
    extra_html: str
    """The raw Extra field (anki-cards Extras carry <i>, lists and images)."""
    answer_hash: str
    """SHA-1 (hex) of the answer text, to notice later edits."""
    has_audio: bool
    """The answer side has sound or TTS (``card.answer_av_tags()``)."""
    answer_html: str
    """Anki's rendered answer side (``render_output().answer_text``), as-is."""
    css: str
    """The note type's CSS (``render_output().css``). Some cards draw their
    masks with CSS classes only, so the display needs it."""
    image_front: bool
    """The front shows an image: no hint, no conflict/collision entry."""
    hint: str = ""
    """The disambiguation suffix appended to the front, e.g. ``" (-a___)"``."""
    colliding_answers: tuple[str, ...] = ()
    """Answers of other cards whose fronts conflict with this one under the
    hint rule (same pool as the hints, computed even when hints are off). The
    controller's "other card's answer" catch checks typed text against them."""


_FIELDS = {f.name for f in dataclasses.fields(SourceRef)}


def source_to_json(s: SourceRef) -> dict[str, Any]:
    d = dataclasses.asdict(s)
    d["colliding_answers"] = list(s.colliding_answers)
    return d


def source_from_json(d: Mapping[str, Any]) -> SourceRef:
    """Inverse of :func:`source_to_json`. Unknown keys are ignored; a missing
    key with a default takes it, any other missing key raises ``TypeError``."""
    kwargs = {k: v for k, v in d.items() if k in _FIELDS}
    if "colliding_answers" in kwargs:
        kwargs["colliding_answers"] = tuple(cast(Sequence[str], kwargs["colliding_answers"]))
    card_class = kwargs.get("card_class")
    if card_class is not None and card_class not in get_args(CardClass):
        raise ValueError(f"unknown card class {card_class!r}")
    return SourceRef(**kwargs)
