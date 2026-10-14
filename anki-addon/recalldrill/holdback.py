"""Hold back (v0.3, pure): keep a deck's new cards out of Anki until they are drilled.

docs/DECISIONS.md, "v0.3: whole-section drilling, exam dates, export".

A deck's ``holdBack`` setting (``deck_settings.json``, default off) means its
new cards reach Anki only after they have been drilled (the handoff
unsuspends them) or released undrilled (``release.py``). The setting applies
to the deck and its subdecks: a deck's explicit value wins, else the nearest
parent's explicit value. Turning it on, and the **Hold back N** button, run
the third collection write (``anki_io/holdback.py``): it suspends the deck's
new, unsuspended cards that aren't already handed off and waiting for Anki, and
tags their notes ``rd::held``. The handoff and the release remove the tag.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass
from typing import Literal

TAG_HELD = "rd::held"
"""The note tag a hold-back adds and a handoff or release removes."""
UNDO_LABEL = "Recall Drill: hold back"

OrderName = Literal["priority_first", "deck_order"]


@dataclass(frozen=True)
class HoldBack:
    on: bool
    did: int | None = None
    """The deck whose explicit setting decides (this deck, or a parent); None = default off."""


def effective(chain: Iterable[int], explicit: Callable[[int], bool | None]) -> HoldBack:
    """The deck's hold-back: the first deck of ``chain`` (the deck, then its
    parents, nearest first) with an explicit value decides; none: off."""
    for did in chain:
        value = explicit(did)
        if value is not None:
            return HoldBack(value, did)
    return HoldBack(False)


def default_order(hold_back: bool) -> OrderName:
    """The setup panel's default Order: deck order (new-queue position) for a deck
    that holds cards back, so a section drills in the order the skill added it."""
    return "deck_order" if hold_back else "priority_first"


def button_label(n: int) -> str:
    return f"Hold back {n}"


def release_question(n: int) -> str:
    return f"Release {n} held card{'' if n == 1 else 's'} to Anki now?"
