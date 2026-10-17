"""Several collection writes as one undo step, rolled back if one fails."""

from __future__ import annotations

import logging
from collections.abc import Callable

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.collection import Collection, OpChanges

log = logging.getLogger(__name__)


class StepFailed(Exception):
    """A multi-write step failed. ``rolled_back``: what it had done is undone."""

    def __init__(self, cause: Exception, rolled_back: bool) -> None:
        super().__init__(str(cause) or type(cause).__name__)
        self.cause = cause
        self.rolled_back = rolled_back


def run_as_one_step(col: Collection, label: str, work: Callable[[], None]) -> OpChanges:
    """Run ``work`` (any number of collection writes) as one undo step called ``label``.

    Each backend call commits on its own, so on failure the calls already made are merged into
    the step's entry and undone: nothing is left half-applied."""
    pos = col.add_custom_undo_entry(label)
    try:
        work()
        return col.merge_undo_entries(pos)
    except Exception as exc:
        raise StepFailed(exc, _roll_back(col, pos, label)) from exc


def _roll_back(col: Collection, pos: int, label: str) -> bool:
    try:
        col.merge_undo_entries(pos)
        if col.undo_status().undo != label:
            return False
        col.undo()
    except Exception:
        log.exception("Math Path: rolling back %r failed", label)
        return False
    return True
