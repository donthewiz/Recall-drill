"""The exam tracker's in-memory cache and its refresh rule (v0.4 step 2; pure, no Qt).

The deck screen's render hook never computes: it draws what is in :class:`NumbersCache`. The
reader (``anki_io/exam_tracker.py``) runs in the background, one run at a time
(:class:`Refresher`), and its result replaces the cache. Entries are keyed by (deck id, Anki
day), so a result from yesterday is never drawn today.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import date

from .exam_tracker import TrackerNumbers


class NumbersCache:
    """The last reader result: numbers per (deck id, Anki day)."""

    def __init__(self) -> None:
        self._data: dict[tuple[int, date], TrackerNumbers] = {}
        self._day: date | None = None
        self._dirty = False

    def get(self, deck_id: int, day: date) -> TrackerNumbers | None:
        return self._data.get((deck_id, day))

    def for_day(self, day: date) -> dict[int, TrackerNumbers]:
        """Every exam deck's numbers computed on ``day`` ({} for a result of another day)."""
        return {did: n for (did, d), n in self._data.items() if d == day}

    def has_day(self, day: date) -> bool:
        """A reader result for ``day`` exists (even one with no exam deck in it)."""
        return self._day == day

    def store(self, day: date, numbers: Mapping[int, TrackerNumbers]) -> None:
        """Replaces everything with one run's result."""
        self._data = {(did, day): n for did, n in numbers.items()}
        self._day = day

    def invalidate(self) -> None:
        """The collection or a setting changed: recompute when the deck screen shows next."""
        self._dirty = True

    def started(self) -> None:
        """A run started, so changes from here on need another one."""
        self._dirty = False

    @property
    def dirty(self) -> bool:
        """Something changed since the last run started."""
        return self._dirty

    def needs_refresh(self, day: date) -> bool:
        return self._dirty or not self.has_day(day)

    def clear(self) -> None:
        self._data = {}
        self._day = None
        self._dirty = False


class Refresher[T]:
    """Never more than one reader running; a request during a run schedules exactly one
    more run after it, however many requests came in.

    ``run(finish)`` starts the reader in the background and must call ``finish(result)``
    later on the main thread (``finish(None)`` on failure). ``on_result(result)`` stores a
    result and redraws the deck screen once."""

    def __init__(
        self,
        run: Callable[[Callable[[T | None], None]], None],
        on_result: Callable[[T], None],
    ) -> None:
        self._run = run
        self._on_result = on_result
        self.running = False
        self.pending = False
        self.runs = 0
        """Runs started so far (tests)."""

    def request(self) -> None:
        if self.running:
            self.pending = True
            return
        self.running = True
        self.runs += 1
        self._run(self._finished)

    def _finished(self, result: T | None) -> None:
        self.running = False
        try:
            if result is not None:
                self._on_result(result)
        finally:
            if self.pending:
                self.pending = False
                self.request()
