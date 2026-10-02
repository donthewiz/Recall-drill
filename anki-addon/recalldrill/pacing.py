"""Pacing a deck to a target date, and the time figures beside it (pure).

docs/DECISIONS.md, "Pacing (Phase 6)".

- **Settings** (``pacing.json``, by deck id): ``target_date``,
  ``drill_weekdays`` (default Mon-Fri) and ``finish_days_before`` (default 1).
- **Remaining**: the scope's eligible ``new`` and ``suspended_new`` cards that
  pass the template filter, minus notes tagged ``rd::drilled`` or
  ``rd::holdout`` (counted by ``anki_io/select.py``).
- **Drill days left**: the drill weekdays from today through
  ``target_date - finish_days_before``. Today counts unless a session in this
  scope completed today (an Anki day, from the history).
- **Today's N**: ``ceil(remaining / days_left)``.

Every minute figure comes from Don's own data and says where it came from;
there are no fixed constants (the web app's cold-start estimate is no longer
shown):

- **Drill minutes** (:func:`drill_speed`): the median active seconds per
  drilled card, by answer shape (chunked or whole), over the last 10 timed
  sessions in the top-level deck (at least 3), else over the timed sessions of
  every deck (labelled so), else none.
- **Anki minutes**: Anki's FSRS simulator (``anki_io/workload.py``), else the
  revlog arithmetic here (:func:`revlog_times`, :func:`revlog_load`), else none.

No daily time budget: the minutes are information only.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta, tzinfo
from typing import Any, Literal, cast

from .measure import RevlogRow, anki_day, iso_ms
from .storage import PACING, Storage

WEEKDAY_NAMES = ("Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun")
MONTH_NAMES = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")
DEFAULT_WEEKDAYS = frozenset(range(5))
"""Monday-Friday (``date.weekday()`` numbers)."""
DEFAULT_FINISH_DAYS_BEFORE = 1

TIMED_SESSIONS = 10
"""Drill speed: the last this many timed sessions."""
MIN_TIMED_SESSIONS = 3
"""Drill speed: fewer timed sessions than this is no estimate."""
REVLOG_DAYS = 30
"""The revlog fallback's window."""
MIN_RATINGS = 50
"""Fewer of Don's own ratings than this is no estimate."""
SIMULATE_EXTRA_DAYS = 14
"""The simulator runs this many days past the last drill day."""


def short_date(d: date) -> str:
    """ "Mon Oct 5" (English names, whatever the locale)."""
    return f"{WEEKDAY_NAMES[d.weekday()]} {MONTH_NAMES[d.month - 1]} {d.day}"


def minutes_text(seconds: float) -> str:
    """ "under 1 min", "about 7 min"."""
    m = seconds / 60
    if m < 1:
        return "under 1 min"
    return f"about {math.floor(m + 0.5)} min"


def _plural(n: int, one: str, many: str | None = None) -> str:
    return f"{n} {one if n == 1 else (many or one + 's')}"


# ---------------------------------------------------------------------------
# Settings and storage
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PacingSettings:
    target_date: date | None = None
    drill_weekdays: frozenset[int] = DEFAULT_WEEKDAYS
    finish_days_before: int = DEFAULT_FINISH_DAYS_BEFORE

    @property
    def last_drill_day(self) -> date | None:
        if self.target_date is None:
            return None
        return self.target_date - timedelta(days=self.finish_days_before)

    def to_json(self) -> dict[str, Any]:
        return {
            "target_date": self.target_date.isoformat() if self.target_date else None,
            "drill_weekdays": sorted(self.drill_weekdays),
            "finish_days_before": self.finish_days_before,
        }


def settings_from_json(raw: object) -> PacingSettings:
    """Keeps what's valid; anything else takes its default."""
    if not isinstance(raw, dict):
        return PacingSettings()
    d = cast(dict[str, Any], raw)
    target: date | None = None
    t = d.get("target_date")
    if isinstance(t, str):
        try:
            target = date.fromisoformat(t)
        except ValueError:
            target = None
    days = d.get("drill_weekdays")
    weekdays = DEFAULT_WEEKDAYS
    if isinstance(days, list):
        weekdays = frozenset(
            x
            for x in cast(list[object], days)
            if isinstance(x, int) and not isinstance(x, bool) and 0 <= x <= 6
        )
    before = d.get("finish_days_before")
    finish = (
        before
        if isinstance(before, int) and not isinstance(before, bool) and 0 <= before <= 365
        else DEFAULT_FINISH_DAYS_BEFORE
    )
    return PacingSettings(target, weekdays, finish)


def _load_all(storage: Storage) -> dict[str, Any]:
    data = storage.read_json(PACING, {})
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def load(storage: Storage, did: int) -> PacingSettings:
    return settings_from_json(_load_all(storage).get(str(did)))


def save(storage: Storage, did: int, settings: PacingSettings) -> None:
    data = _load_all(storage)
    data[str(did)] = settings.to_json()
    storage.write_json(PACING, data)


# ---------------------------------------------------------------------------
# Drill days and today's N
# ---------------------------------------------------------------------------


def completed_today(
    history_lines: Iterable[Mapping[str, Any]],
    today: date,
    rollover_hour: int,
    tz: tzinfo | None = None,
) -> bool:
    """A ``type: "session"`` line (a completed session) finished on Anki day ``today``."""
    for line in history_lines:
        if line.get("type") != "session":
            continue
        finished = line.get("finishedAt")
        ms = iso_ms(finished) if isinstance(finished, str) else None
        if ms is not None and anki_day(ms, rollover_hour, tz) == today:
            return True
    return False


def drill_days(today: date, settings: PacingSettings, done_today: bool) -> list[date]:
    """The drill weekdays from today (tomorrow, if a session completed today)
    through the last drill day."""
    last = settings.last_drill_day
    if last is None:
        return []
    d = today + timedelta(days=1) if done_today else today
    out: list[date] = []
    while d <= last:
        if d.weekday() in settings.drill_weekdays:
            out.append(d)
        d += timedelta(days=1)
    return out


PaceStatus = Literal["no_target", "target_passed", "done", "behind", "ok"]


@dataclass(frozen=True)
class Pace:
    status: PaceStatus
    remaining: int
    days: tuple[date, ...] = ()
    """The drill days left (:func:`drill_days`)."""
    today: date | None = None
    target_date: date | None = None
    done_today: bool = False

    @property
    def days_left(self) -> int:
        return len(self.days)

    @property
    def per_day(self) -> int:
        """``ceil(remaining / days_left)``: the cards each drill day takes (0 when
        there is no drill day left)."""
        if not self.days or self.remaining <= 0:
            return 0
        return math.ceil(self.remaining / len(self.days))

    @property
    def drills_today(self) -> bool:
        return bool(self.days) and self.days[0] == self.today

    @property
    def today_n(self) -> int:
        """Today's cards: :attr:`per_day` on a drill day that still counts, else 0."""
        return self.per_day if self.status == "ok" and self.drills_today else 0

    def headline(self) -> str:
        """The first part of the pacing line (no minutes)."""
        if self.status == "no_target":
            return "No target date."
        assert self.target_date is not None
        target = short_date(self.target_date)
        if self.status == "target_passed":
            return (
                f"The target date ({target}) has passed: "
                f"{_plural(self.remaining, 'card')} left. Pick a new date."
            )
        if self.status == "done":
            return f"Nothing left to drill before {target}."
        if self.status == "behind":
            return f"Behind: {_plural(self.remaining, 'card')}, no drill days left before {target}."
        left = f"{self.remaining} left over {_plural(self.days_left, 'drill day')}"
        if self.drills_today:
            return f"Today: {_plural(self.per_day, 'card')}. {left}."
        nxt = f"next: {short_date(self.days[0])}, {_plural(self.per_day, 'card')}"
        why = "done (a session finished today)" if self.done_today else "not a drill day"
        return f"Today: {why}; {nxt}. {left}."


def compute_pace(today: date, settings: PacingSettings, remaining: int, done_today: bool) -> Pace:
    """Today's pace. The edge cases: no target; the target passed; nothing
    remaining; no drill day left with cards remaining ("behind"); today not a
    drill day, or already done (today's N is 0, the next drill day's is given)."""
    target = settings.target_date
    if target is None:
        return Pace("no_target", remaining, today=today)
    if today > target:
        return Pace("target_passed", remaining, today=today, target_date=target)
    if remaining <= 0:
        return Pace("done", 0, today=today, target_date=target)
    days = tuple(drill_days(today, settings, done_today))
    status: PaceStatus = "ok" if days else "behind"
    return Pace(status, remaining, days, today, target, done_today)


# ---------------------------------------------------------------------------
# Tomorrow's new cards, and Anki's limits
# ---------------------------------------------------------------------------


def _half_up(x: float) -> int:
    return math.floor(x + 0.5)


def holdout_share(n: int, pct: int) -> int:
    """Holdout cards set aside while ``n`` cards are picked for the drill
    (``apply_holdout`` keeps going until ``n`` drill cards): ``n * p / (100 - p)``."""
    if n <= 0 or pct <= 0 or pct >= 100:
        return 0
    return _half_up(n * pct / (100 - pct))


@dataclass(frozen=True)
class PlannedNew:
    """The cards one drill day's handoff sends to Anki."""

    drilled: int
    siblings: int
    holdout: int

    @property
    def total(self) -> int:
        return self.drilled + self.siblings + self.holdout


def planned_new(
    n: int, sibling_ratio: float, holdout_pct: int, mode: str, siblings_on: bool = True
) -> PlannedNew:
    """N, plus their suspended new siblings (at the scope's measured ratio,
    when ``handoff_siblings`` is on), plus the holdout share under handoff B."""
    siblings = _half_up(n * sibling_ratio) if siblings_on else 0
    held = holdout_share(n, holdout_pct) if mode == "B" else 0
    return PlannedNew(n, siblings, held)


def ceiling_warning(
    mode: str,
    planned: PlannedNew,
    new_limit: int,
    reviews_tomorrow: int,
    review_limit: int,
) -> str | None:
    """Warn (never block) when tomorrow's handoff won't fit Anki's limit.

    B: tomorrow's new cards (N + siblings + holdout share) against new/day.
    A: the N drilled cards (reviews tomorrow) against the room left in the
    review limit after the reviews already due tomorrow (the Phase 4 forecast's
    count)."""
    if planned.drilled <= 0:
        return None
    if mode == "B":
        over = planned.total - max(0, new_limit)
        if over <= 0:
            return None
        parts = [f"{planned.drilled} drilled"]
        if planned.siblings:
            parts.append(f"{planned.siblings} siblings")
        if planned.holdout:
            parts.append(f"{planned.holdout} holdout")
        return (
            f"Tomorrow: {_plural(planned.total, 'new card')} ({' + '.join(parts)}), over the "
            f"deck's new/day limit of {new_limit}: Anki holds back {over}."
        )
    room = max(0, review_limit - reviews_tomorrow)
    over = planned.drilled - room
    if over <= 0:
        return None
    return (
        f"Tomorrow: {_plural(planned.drilled, 'drilled card')} become reviews, with room for "
        f"{room} under the review limit of {review_limit} ({reviews_tomorrow} already due): "
        f"Anki holds back {over}."
    )


# ---------------------------------------------------------------------------
# Drill speed, from the history's active time
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TimedSession:
    finished_ms: int
    cards: tuple[tuple[bool, int], ...]
    """(chunked, active ms) per drilled card."""


def timed_session(line: Mapping[str, Any]) -> TimedSession | None:
    """A ``type: "session"`` line with ``activeMs`` (lines before Phase 6 have none)."""
    if line.get("type") != "session":
        return None
    active = line.get("activeMs")
    if not isinstance(active, int) or isinstance(active, bool) or active <= 0:
        return None
    finished = line.get("finishedAt")
    ms = iso_ms(finished) if isinstance(finished, str) else None
    anki = cast(list[Any], line.get("anki") or [])
    cards = cast(list[Any], line.get("cards") or [])
    per_card: list[tuple[bool, int]] = []
    for a, c in zip(anki, cards, strict=False):
        if not isinstance(a, dict) or not isinstance(c, dict):
            continue
        card_ms = cast(dict[str, Any], a).get("activeMs")
        chunks = cast(dict[str, Any], c).get("chunks")
        if isinstance(card_ms, int) and not isinstance(card_ms, bool) and card_ms > 0:
            per_card.append((isinstance(chunks, int) and chunks > 1, card_ms))
    if not per_card:
        return None
    return TimedSession(ms or 0, tuple(per_card))


DrillScope = Literal["deck", "all"]


@dataclass(frozen=True)
class DrillSpeed:
    scope: DrillScope
    sessions: int
    chunked_s: float | None
    """Median active seconds per chunked card, or None (no such card timed)."""
    full_s: float | None
    """Median active seconds per card drilled whole, or None."""
    overall_s: float

    def per_card(self, chunked: bool) -> float:
        own = self.chunked_s if chunked else self.full_s
        return self.overall_s if own is None else own

    def seconds(self, n_chunked: int, n_full: int) -> float:
        return n_chunked * self.per_card(True) + n_full * self.per_card(False)

    def source(self) -> str:
        where = "" if self.scope == "deck" else " (all decks: fewer than 3 in this deck)"
        return f"your pace, last {_plural(self.sessions, 'timed session')}{where}"


NO_DRILL_ESTIMATE = "no estimate yet (needs 3 timed sessions)"


def _median(values: Sequence[float]) -> float | None:
    return statistics.median(values) if values else None


def _speed(sessions: Sequence[TimedSession], scope: DrillScope) -> DrillSpeed:
    cards = [c for s in sessions for c in s.cards]
    chunked = [ms / 1000 for ch, ms in cards if ch]
    full = [ms / 1000 for ch, ms in cards if not ch]
    overall = _median([ms / 1000 for _, ms in cards])
    assert overall is not None
    return DrillSpeed(scope, len(sessions), _median(chunked), _median(full), overall)


def drill_speed(
    deck_lines: Iterable[Mapping[str, Any]],
    all_lines: Iterable[Mapping[str, Any]],
    last: int = TIMED_SESSIONS,
    min_sessions: int = MIN_TIMED_SESSIONS,
) -> DrillSpeed | None:
    """The medians over the last ``last`` timed sessions in the deck when it has
    at least ``min_sessions``, else over every deck's, else None."""

    def recent(lines: Iterable[Mapping[str, Any]]) -> list[TimedSession]:
        timed = [t for t in (timed_session(x) for x in lines) if t is not None]
        timed.sort(key=lambda t: t.finished_ms)
        return timed[-last:] if last > 0 else []

    deck = recent(deck_lines)
    if len(deck) >= min_sessions:
        return _speed(deck, "deck")
    every = recent(all_lines)
    if len(every) >= min_sessions:
        return _speed(every, "all")
    return None


# ---------------------------------------------------------------------------
# The revlog fallback for Anki minutes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RevlogTimes:
    """Don's answer times in one deck over the last :data:`REVLOG_DAYS` days."""

    review_ms: float | None
    """Median ``time`` of review and relearning ratings."""
    learn_ms: float | None
    """Median ``time`` of learning (new card) ratings."""
    learn_ratings_per_card: float
    """Learning ratings per card that had any (a new card's steps)."""
    ratings: int

    @property
    def enough(self) -> bool:
        return self.ratings >= MIN_RATINGS


def revlog_times(rows: Iterable[RevlogRow], since_ms: int) -> RevlogTimes:
    """Counted ratings (``ease >= 1``; learn, review, relearn) since ``since_ms``
    with a recorded time."""
    review: list[float] = []
    learn: list[float] = []
    learn_cards: set[int] = set()
    for r in rows:
        if r.id < since_ms or r.ease < 1 or r.time <= 0:
            continue
        if r.type == 0:
            learn.append(r.time)
            learn_cards.add(r.cid)
        elif r.type in (1, 2):
            review.append(r.time)
    per_card = len(learn) / len(learn_cards) if learn_cards else 1.0
    return RevlogTimes(_median(review), _median(learn), per_card, len(review) + len(learn))


def revlog_load(
    times: RevlogTimes, due_by_day: Sequence[int], new_by_day: Sequence[int]
) -> list[float]:
    """Seconds per coming day: reviews due that day x the review median, plus
    that day's new cards x their learning ratings x the learning median. A
    missing median takes the other one's place."""
    review_ms = times.review_ms if times.review_ms is not None else times.learn_ms
    learn_ms = times.learn_ms if times.learn_ms is not None else times.review_ms
    if review_ms is None or learn_ms is None:
        return [0.0 for _ in due_by_day]
    out: list[float] = []
    for i, due in enumerate(due_by_day):
        new = new_by_day[i] if i < len(new_by_day) else 0
        out.append((due * review_ms + new * times.learn_ratings_per_card * learn_ms) / 1000)
    return out


AnkiSource = Literal["simulator", "revlog", "none"]


@dataclass(frozen=True)
class AnkiLoad:
    """Review time in Anki: tomorrow and the peak day."""

    source: AnkiSource
    tomorrow_s: float = 0.0
    peak_s: float = 0.0
    peak_date: date | None = None
    note: str = ""
    """Where the figures come from, or why there are none."""
    fallback_reason: str = ""
    """Why the simulator wasn't used (shown with a fallback)."""

    @classmethod
    def from_days(
        cls,
        source: AnkiSource,
        seconds: Sequence[float],
        first_day: date,
        note: str,
        fallback_reason: str = "",
    ) -> AnkiLoad:
        """``seconds[i]`` is day ``first_day + i``; index 0 is tomorrow."""
        if not seconds:
            return cls("none", note=NO_ANKI_ESTIMATE, fallback_reason=fallback_reason)
        peak_i = max(range(len(seconds)), key=lambda i: (seconds[i], -i))
        return cls(
            source,
            seconds[0],
            seconds[peak_i],
            first_day + timedelta(days=peak_i),
            note,
            fallback_reason,
        )


NO_ANKI_ESTIMATE = "no estimate yet"


# ---------------------------------------------------------------------------
# The panel's line
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PacingView:
    """Everything the panel's Pacing section shows."""

    pace: Pace
    drill_s: float | None = None
    drill_source: str = NO_DRILL_ESTIMATE
    anki: AnkiLoad = field(default_factory=lambda: AnkiLoad("none", note=NO_ANKI_ESTIMATE))
    warning: str | None = None
    planned: PlannedNew | None = None

    def line(self) -> str:
        """ "Today: 12 cards, about 9 min drilling (your pace) + about 6 min in Anki
        tomorrow (FSRS simulator). Peak: about 14 min on Thu Oct 8. 57 left over
        5 drill days." (each part only when it applies)."""
        p = self.pace
        if p.status != "ok":
            return p.headline()
        n = p.today_n if p.drills_today else p.per_day
        if p.drills_today:
            parts = [f"Today: {_plural(n, 'card')}"]
        else:
            why = "done (a session finished today)" if p.done_today else "not a drill day"
            parts = [f"Today: {why}; next {short_date(p.days[0])}: {_plural(n, 'card')}"]
        parts[0] += (
            f", {minutes_text(self.drill_s)} drilling (your pace)"
            if self.drill_s is not None
            else ", drill time: no estimate yet"
        )
        if self.anki.source != "none":
            label = "FSRS simulator" if self.anki.source == "simulator" else "your revlog times"
            parts[0] += f" + {minutes_text(self.anki.tomorrow_s)} in Anki tomorrow ({label})"
        text = parts[0] + "."
        if self.anki.source != "none" and self.anki.peak_date is not None:
            text += f" Peak: {minutes_text(self.anki.peak_s)} on {short_date(self.anki.peak_date)}."
        return text + f" {p.remaining} left over {_plural(p.days_left, 'drill day')}."

    def sources(self) -> str:
        """The small print: where each number comes from."""
        drill = f"Drill time: {self.drill_source}."
        anki = f"Anki time: {self.anki.note}."
        if self.anki.fallback_reason:
            anki += f" {self.anki.fallback_reason}"
        elif self.anki.source == "none":
            anki += f" Fewer than {MIN_RATINGS} of your own ratings in this deck so far."
        return f"{drill} {anki}"
