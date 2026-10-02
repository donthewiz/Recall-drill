"""A card's state, read once (pure).

:class:`CardSnapshot` lives here, not in ``anki_io/cards.py``, so the pure
modules that judge a card (``difficulty.py``) can take one without importing
anki. ``anki_io/cards.py`` builds snapshots from the collection and re-exports
both names.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass


@dataclass(frozen=True)
class CardSnapshot:
    cid: int
    nid: int
    did: int
    odid: int
    ord: int
    ntid: int
    type: int
    queue: int
    ivl: int
    due: int
    lapses: int
    reps: int
    factor: int
    flags: int
    """The user flag (``card.user_flag()``, 0-7), not the raw flags column."""
    tags: tuple[str, ...]
    fsrs_d: float | None
    """FSRS difficulty, 1-10 (``memory_state.difficulty``), or None."""
    fsrs_s: float | None
    """FSRS stability in days, or None."""
    odue: int = 0
    """The home deck's due while in a filtered deck (new-queue position for new cards)."""

    @property
    def home_did(self) -> int:
        """The deck the card belongs to, even while it sits in a filtered deck."""
        return self.odid or self.did

    @property
    def new_position(self) -> int:
        """New-queue position (meaningful for type 0 only)."""
        return self.odue if self.odid else self.due

    @property
    def has_fsrs(self) -> bool:
        """Both FSRS values are known (the card has a memory state)."""
        return self.fsrs_d is not None and self.fsrs_s is not None


def has_tag(tags: Iterable[str], tag: str) -> bool:
    """Anki tags compare case-insensitively."""
    want = tag.casefold()
    return any(t.casefold() == want for t in tags)
