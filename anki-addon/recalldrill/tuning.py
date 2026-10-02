"""The tuning report (pure): next-day Again for drilled, holdout and baseline
cards, broken down, with rule-based suggestions for ``MIN_WORDS_TO_CHUNK`` and
``encodeReps``.

docs/DECISIONS.md, "Measurement and holdout (Phase 5)". The metric is
``measure.py``'s. :func:`build_report` takes the history lines (every log),
the revlog rows of the cards involved, and what the collection says about each
card (its deck), and returns a :class:`Report`; the dialog
(``ui/tuning_dialog.py``) only renders it.

The report **suggests**. A setting changes only when Don presses a
suggestion's Apply and confirms a dialog that shows the evidence; that writes
the add-on's global default and a ``type: "tuning"`` history line
(:func:`tuning_line`).

Phase 6: a card's ``encodeReps`` is the one it was drilled with (the session
line's per-card ``encodeReps``, set by the FSRS difficulty adjustment; the
session's for older lines), so the ``encodeReps`` breakdown and suggestion see
per-card variation. The "adjustment" breakdown groups cards by ``+1`` / ``0`` /
``−1`` against the session's reps.
"""

from __future__ import annotations

import csv
import html
import io
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, tzinfo
from typing import Any, Literal, cast

from .engine.jscompat import js_iso_string
from .measure import (
    Outcome,
    RevlogRow,
    anki_day,
    drilled_outcome,
    introduced_outcome,
    introduction_ms,
    iso_ms,
    overlaps,
    wilson,
)

CONFOUND_WARNING = (
    "Drilled and undrilled cards aren't randomly assigned. Only the holdout comparison "
    "is a fair test. The baseline below is cards you learned before using the add-on, "
    "most of which were drilled in the web app, so it's not an Anki-only baseline."
)
T_CAVEAT = (
    "These groups differ in answer length, not just chunking; treat this as a hint, not proof."
)
TOO_SMALL = "n too small"
COST_MARGIN = 1.25
"""Chunked cards must cost at least this many times the trials per word."""
T_WINDOW = 3
"""Unchunked ``[T-3, T]`` words vs chunked ``[T+1, T+4]``."""
T_STEP = 2
DELETED = "(deleted card)"

Group = Literal["drilled", "holdout", "baseline"]
Parameter = Literal["min_words_to_chunk", "encode_reps"]
PARAM_LABELS: dict[Parameter, str] = {
    "min_words_to_chunk": "MIN_WORDS_TO_CHUNK",
    "encode_reps": "encodeReps",
}


@dataclass(frozen=True)
class CardInfo:
    """What the collection says about a card now."""

    deck: str
    """Its home deck's full name."""
    top: str
    """Its top-level deck's name."""


@dataclass(frozen=True)
class ReportSettings:
    min_n: int = 30
    min_words_to_chunk: int = 8
    """The current ``T`` (the add-on's global default)."""
    encode_reps: int = 3
    """The current global ``encodeReps`` default."""


@dataclass(frozen=True)
class CardRow:
    """One card's outcome: a row of the CSV."""

    group: Group
    cid: int
    deck: str
    top: str
    outcome: Outcome
    nid: int | None = None
    session_id: str | None = None
    words: int | None = None
    chunks: int | None = None
    encode_reps: int | None = None
    """The reps this card was drilled with (its own, else the session's)."""
    adjustment: int | None = None
    """+1 / 0 / -1 against the session's reps (Phase 6); None on older lines."""
    card_class: str | None = None
    mode: str | None = None
    attempts: int | None = None
    misses: int | None = None
    reveals: int | None = None
    final_misses: int | None = None

    @property
    def struggle(self) -> int | None:
        if self.misses is None or self.reveals is None:
            return None
        return self.misses + self.reveals


@dataclass(frozen=True)
class Stat:
    """One group's numbers. ``n`` counts the primary-analysis outcomes only."""

    label: str
    cards: int
    n: int
    again: int
    pending: int
    late: int
    trials: float | None
    """Mean trials (attempts) per card, over every card of the group."""
    struggle: float | None
    """Mean misses + reveals per card, over every card of the group."""
    min_n: int
    trials_per_word: float | None = None

    @property
    def rate(self) -> float | None:
        return self.again / self.n if self.n else None

    @property
    def ci(self) -> tuple[float, float]:
        return wilson(self.again, self.n)

    @property
    def too_small(self) -> bool:
        return self.n < self.min_n

    def rate_text(self) -> str:
        if self.too_small:
            return TOO_SMALL
        lo, hi = self.ci
        return f"{_pct(self.rate or 0.0)} (95% CI {_pct(lo)}–{_pct(hi)})"

    def evidence(self) -> str:
        cost = f", {self.trials_per_word:.2f} trials/word" if self.trials_per_word else ""
        if self.n == 0:
            return f"{self.label}: n 0{cost}"
        lo, hi = self.ci
        return (
            f"{self.label}: n {self.n}, Again {_pct(self.rate or 0.0)} "
            f"(95% CI {_pct(lo)}–{_pct(hi)}){cost}"
        )


@dataclass(frozen=True)
class Suggestion:
    parameter: Parameter
    current: int
    proposed: int | None
    """None: nothing to apply."""
    verdict: str
    evidence: tuple[str, ...]
    caveat: str | None = None

    @property
    def label(self) -> str:
        return PARAM_LABELS[self.parameter]

    @property
    def actionable(self) -> bool:
        return self.proposed is not None and self.proposed != self.current


@dataclass
class Report:
    deck_filter: str | None
    decks: list[str]
    """Top-level decks the drilled cards are in (the filter's choices)."""
    sessions: int
    first_day: date | None
    last_day: date | None
    comparison: list[Stat]
    breakdowns: list[tuple[str, list[Stat]]]
    suggestions: list[Suggestion]
    rows: list[CardRow] = field(default_factory=list[CardRow])
    first_session_ms: int | None = None

    def group(self, name: Group) -> list[CardRow]:
        return [r for r in self.rows if r.group == name]

    def counts(self, name: Group) -> tuple[int, int, int, int]:
        """(cards, outcomes, late, pending)."""
        rows = self.group(name)
        by = [r.outcome.status for r in rows]
        return len(rows), by.count("outcome"), by.count("late"), by.count("pending")


# ---------------------------------------------------------------------------
# Building
# ---------------------------------------------------------------------------


def _pct(x: float) -> str:
    return f"{100 * x:.0f}%"


def _int(v: object) -> int | None:
    return v if isinstance(v, int) and not isinstance(v, bool) else None


def _str(v: object) -> str | None:
    return v if isinstance(v, str) else None


def _key(obj: object, key: str) -> object:
    """``obj[key]`` when ``obj`` is a dict, else None."""
    return cast(dict[str, Any], obj).get(key) if isinstance(obj, dict) else None


def _dicts(v: object) -> list[dict[str, Any]]:
    if not isinstance(v, list):
        return []
    return [cast(dict[str, Any], x) for x in cast(list[Any], v) if isinstance(x, dict)]


def _ints(v: object) -> list[int]:
    if not isinstance(v, list):
        return []
    return [i for i in (_int(x) for x in cast(list[Any], v)) if i is not None]


@dataclass(frozen=True)
class _SessionCard:
    nid: int | None
    card_class: str | None
    encode_reps: int | None
    adjustment: int | None
    words: int | None
    chunks: int | None
    attempts: int | None
    misses: int | None
    reveals: int | None
    final_misses: int | None


@dataclass
class _Session:
    session_id: str
    started_ms: int | None
    finished_ms: int | None
    encode_reps: int | None
    cards: dict[int, _SessionCard]
    holdout: dict[int, dict[str, Any]]


def _session(line: Mapping[str, Any]) -> _Session:
    anki = _dicts(line.get("anki"))
    cards = _dicts(line.get("cards"))
    by_cid: dict[int, _SessionCard] = {}
    # ``anki`` is parallel to ``cards`` (history_store.build_session_line).
    for a, c in zip(anki, cards, strict=False):
        cid = _int(a.get("cid"))
        if cid is None:
            continue
        by_cid[cid] = _SessionCard(
            nid=_int(a.get("nid")),
            card_class=_str(a.get("card_class")),
            encode_reps=_int(a.get("encodeReps")),
            adjustment=_int(a.get("adjust")),
            words=_int(c.get("words")),
            chunks=_int(c.get("chunks")),
            attempts=_int(c.get("attempts")),
            misses=_int(c.get("misses")),
            reveals=_int(c.get("reveals")),
            final_misses=_int(c.get("finalMisses")),
        )
    reps = _int(_key(line.get("encode"), "encodeReps"))
    holdout: dict[int, dict[str, Any]] = {}
    for h in _dicts(line.get("holdout")):
        cid = _int(h.get("cid"))
        if cid is not None:
            holdout[cid] = h
    started = line.get("startedAt")
    finished = line.get("finishedAt")
    return _Session(
        session_id=str(line.get("sessionId") or ""),
        started_ms=iso_ms(started) if isinstance(started, str) else None,
        finished_ms=iso_ms(finished) if isinstance(finished, str) else None,
        encode_reps=reps,
        cards=by_cid,
        holdout=holdout,
    )


def collect_cids(history_lines: Iterable[Mapping[str, Any]]) -> tuple[set[int], set[int]]:
    """(drilled, holdout) card ids the history's handoffs name: the cards whose
    revlog and deck the report needs (plus the baseline's)."""
    drilled: set[int] = set()
    holdout: set[int] = set()
    for line in history_lines:
        if line.get("type") != "handoff" or line.get("declined"):
            continue
        drilled.update(_ints([d.get("cid") for d in _dicts(line.get("cards"))]))
        holdout.update(_ints(_key(line.get("groups"), "holdout")))
    return drilled, holdout


def first_session_ms(history_lines: Iterable[Mapping[str, Any]]) -> int | None:
    """When the first add-on session started (the baseline's cut-off)."""
    times: list[int] = []
    for line in history_lines:
        if line.get("type") == "session":
            started = _session(line).started_ms
            if started is not None:
                times.append(started)
    return min(times) if times else None


def card_rows(
    history_lines: Sequence[Mapping[str, Any]],
    revlog: Sequence[RevlogRow],
    cards: Mapping[int, CardInfo],
    rollover: int,
    tz: tzinfo | None = None,
) -> list[CardRow]:
    """Every drilled, holdout and baseline card's outcome (all decks)."""
    sessions = {
        s.session_id: s for s in (_session(x) for x in history_lines if x.get("type") == "session")
    }
    by_cid: dict[int, list[RevlogRow]] = defaultdict(list)
    for r in revlog:
        by_cid[r.cid].append(r)

    def info(cid: int) -> CardInfo:
        return cards.get(cid) or CardInfo(DELETED, DELETED)

    rows: list[CardRow] = []
    drilled_ids: set[int] = set()
    holdout_ids: set[int] = set()
    for line in history_lines:
        if line.get("type") != "handoff" or line.get("declined"):
            continue
        t0 = iso_ms(str(line.get("timestamp") or ""))
        if t0 is None:
            continue
        sid = str(line.get("sessionId") or "")
        sess = sessions.get(sid)
        mode = _str(line.get("mode"))
        for d in _dicts(line.get("cards")):
            cid = _int(d.get("cid"))
            if cid is None:
                continue
            drilled_ids.add(cid)
            sc = sess.cards.get(cid) if sess is not None else None
            ci = info(cid)
            rows.append(
                CardRow(
                    group="drilled",
                    cid=cid,
                    deck=ci.deck,
                    top=ci.top,
                    outcome=drilled_outcome(by_cid.get(cid, ()), t0, rollover, tz),
                    nid=_int(d.get("nid")),
                    session_id=sid,
                    words=sc.words if sc else None,
                    chunks=sc.chunks if sc else None,
                    encode_reps=(
                        sc.encode_reps
                        if sc is not None and sc.encode_reps is not None
                        else (sess.encode_reps if sess else None)
                    ),
                    adjustment=sc.adjustment if sc else None,
                    card_class=sc.card_class if sc else None,
                    mode=mode,
                    attempts=sc.attempts if sc else None,
                    misses=sc.misses if sc else None,
                    reveals=sc.reveals if sc else None,
                    final_misses=sc.final_misses if sc else _int(d.get("finalMisses")),
                )
            )
        held = _ints(_key(line.get("groups"), "holdout"))
        for cid in held:
            if cid in holdout_ids:
                continue
            holdout_ids.add(cid)
            h = sess.holdout.get(cid, {}) if sess is not None else {}
            ci = info(cid)
            rows.append(
                CardRow(
                    group="holdout",
                    cid=cid,
                    deck=ci.deck,
                    top=ci.top,
                    outcome=introduced_outcome(by_cid.get(cid, ()), rollover, tz),
                    nid=_int(h.get("nid")),
                    session_id=sid,
                    card_class=_str(h.get("card_class")),
                    mode=mode,
                )
            )

    cut = first_session_ms(history_lines)
    tops = {r.top for r in rows if r.group == "drilled" and r.top != DELETED}
    if cut is not None:
        for cid in sorted(cards):
            ci = cards[cid]
            if ci.top not in tops or cid in drilled_ids or cid in holdout_ids:
                continue
            card_revlog = by_cid.get(cid, ())
            intro = introduction_ms(card_revlog)
            if intro is None or intro >= cut:
                continue
            rows.append(
                CardRow(
                    group="baseline",
                    cid=cid,
                    deck=ci.deck,
                    top=ci.top,
                    outcome=introduced_outcome(card_revlog, rollover, tz),
                )
            )
    return rows


def _mean(values: Iterable[int | None]) -> float | None:
    v = [x for x in values if x is not None]
    return sum(v) / len(v) if v else None


def stat(label: str, rows: Sequence[CardRow], min_n: int, *, per_word: bool = False) -> Stat:
    outcomes = [r for r in rows if r.outcome.status == "outcome"]
    tpw = None
    if per_word:
        known = [r for r in rows if r.attempts is not None and r.words]
        words = sum(r.words or 0 for r in known)
        tpw = sum(r.attempts or 0 for r in known) / words if words else None
    return Stat(
        label=label,
        cards=len(rows),
        n=len(outcomes),
        again=sum(1 for r in outcomes if r.outcome.again),
        pending=sum(1 for r in rows if r.outcome.status == "pending"),
        late=sum(1 for r in rows if r.outcome.status == "late"),
        trials=_mean(r.attempts for r in rows),
        struggle=_mean(r.struggle for r in rows),
        min_n=min_n,
        trials_per_word=tpw,
    )


def words_bucket(words: int | None) -> str:
    if words is None:
        return "unknown"
    if words <= 1:
        return "1"
    if words <= 3:
        return "2–3"
    if words <= 8:
        return "4–8"
    if words <= 15:
        return "9–15"
    return "16+"


WORD_BUCKETS = ("1", "2–3", "4–8", "9–15", "16+", "unknown")


def chunks_bucket(chunks: int | None) -> str:
    if chunks is None:
        return "unknown"
    if chunks <= 1:
        return "none"
    if chunks >= 4:
        return "4+"
    return str(chunks)


CHUNK_BUCKETS = ("none", "2", "3", "4+", "unknown")


def adjustment_bucket(adjustment: int | None) -> str:
    if adjustment is None:
        return "unknown"
    if adjustment > 0:
        return "+1"
    if adjustment < 0:
        return "−1"
    return "0"


ADJUSTMENT_BUCKETS = ("+1", "0", "−1", "unknown")


def _breakdown(
    rows: Sequence[CardRow],
    key: Callable[[CardRow], str],
    min_n: int,
    order: Sequence[str] | None = None,
) -> list[Stat]:
    groups: dict[str, list[CardRow]] = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)
    names = [k for k in order if k in groups] if order else sorted(groups)
    names += sorted(k for k in groups if k not in names)
    return [stat(k, groups[k], min_n) for k in names]


def suggest_t(drilled: Sequence[CardRow], current: int, min_n: int) -> Suggestion:
    """``MIN_WORDS_TO_CHUNK``: unchunked cards just at or under T against chunked
    cards just over it."""
    lo_words = max(1, current - T_WINDOW)
    unchunked = [
        r
        for r in drilled
        if r.chunks == 0 and r.words is not None and lo_words <= r.words <= current
    ]
    chunked = [
        r
        for r in drilled
        if (r.chunks or 0) > 0
        and r.words is not None
        and current + 1 <= r.words <= current + 1 + T_WINDOW
    ]
    u = stat(f"Unchunked, {lo_words}–{current} words", unchunked, min_n, per_word=True)
    c = stat(
        f"Chunked, {current + 1}–{current + 1 + T_WINDOW} words", chunked, min_n, per_word=True
    )
    evidence = (u.evidence(), c.evidence())

    def make(proposed: int | None, verdict: str) -> Suggestion:
        return Suggestion("min_words_to_chunk", current, proposed, verdict, evidence, T_CAVEAT)

    if u.too_small or c.too_small:
        return make(None, f"No suggestion: {TOO_SMALL} (each group needs {min_n}).")
    if u.ci[0] > c.ci[1]:
        new = max(1, current - T_STEP)
        return make(
            new,
            f"Suggest {current} → {new}: unchunked answers just under the threshold are "
            "forgotten significantly more often than chunked ones just over it.",
        )
    cost_up = (
        u.trials_per_word is not None
        and c.trials_per_word is not None
        and c.trials_per_word >= COST_MARGIN * u.trials_per_word
    )
    if overlaps(u.ci, c.ci) and cost_up:
        new = current + T_STEP
        return make(
            new,
            f"Suggest {current} → {new}: the Again rates overlap, and chunked answers cost "
            f"≥ {COST_MARGIN - 1:.0%} more trials per word. Fewer trials wins.",
        )
    return make(current, "No change.")


def suggest_encode_reps(drilled: Sequence[CardRow], current: int, min_n: int) -> Suggestion:
    """``encodeReps``: the lowest value that is not significantly worse than any
    higher value with enough data."""
    by: dict[int, list[CardRow]] = defaultdict(list)
    for r in drilled:
        if r.encode_reps is not None:
            by[r.encode_reps].append(r)
    stats = {v: stat(f"encodeReps {v}", by[v], min_n) for v in sorted(by)}
    evidence = tuple(
        s.evidence() + (f", {s.trials:.1f} trials/card" if s.trials is not None else "")
        for s in stats.values()
    )
    ok = [v for v, s in stats.items() if not s.too_small]
    if len(ok) < 2:
        return Suggestion(
            "encode_reps",
            current,
            None,
            f"Insufficient variation: fewer than 2 values have n ≥ {min_n}.",
            evidence,
        )
    best = max(ok)
    for v in ok:
        worse = [w for w in ok if w > v and stats[v].ci[0] > stats[w].ci[1]]
        if not worse:
            best = v
            break
    if best == current:
        return Suggestion("encode_reps", current, current, "No change.", evidence)
    if best < current:
        why = "its Again rate isn't significantly worse than the higher values'; fewer trials"
    else:
        why = "the lower values are significantly worse"
    return Suggestion("encode_reps", current, best, f"Suggest {current} → {best}: {why}.", evidence)


def build_report(
    history_lines: Sequence[Mapping[str, Any]],
    revlog_rows: Sequence[RevlogRow],
    deck_filter: str | None,
    *,
    cards: Mapping[int, CardInfo],
    rollover: int,
    settings: ReportSettings | None = None,
    tz: tzinfo | None = None,
) -> Report:
    """The report for one top-level deck (``deck_filter``), or every deck (None).

    ``cards``: every card the collection still has among the drilled and
    holdout cards, plus every card of their top-level decks (the baseline's
    candidates). ``revlog_rows``: all their revlog rows."""
    cfg = settings or ReportSettings()
    all_rows = card_rows(history_lines, revlog_rows, cards, rollover, tz)
    decks = sorted({r.top for r in all_rows if r.group == "drilled"})
    rows = [r for r in all_rows if deck_filter is None or r.top == deck_filter]
    drilled = [r for r in rows if r.group == "drilled"]
    in_filter = {r.session_id for r in drilled}
    sessions = [
        s
        for s in (_session(x) for x in history_lines if x.get("type") == "session")
        if deck_filter is None or s.session_id in in_filter
    ]
    starts = [s.started_ms for s in sessions if s.started_ms is not None]
    ends = [s.finished_ms or s.started_ms for s in sessions]
    ends_ms = [e for e in ends if e is not None]
    m = cfg.min_n
    comparison = [
        stat("Drilled", drilled, m),
        stat("Holdout", [r for r in rows if r.group == "holdout"], m),
        stat("Baseline", [r for r in rows if r.group == "baseline"], m),
    ]
    breakdowns = [
        ("answer words", _breakdown(drilled, lambda r: words_bucket(r.words), m, WORD_BUCKETS)),
        ("chunks", _breakdown(drilled, lambda r: chunks_bucket(r.chunks), m, CHUNK_BUCKETS)),
        ("encodeReps", _breakdown(drilled, lambda r: str(r.encode_reps or "unknown"), m)),
        (
            "adjustment (+1 / 0 / −1)",
            _breakdown(drilled, lambda r: adjustment_bucket(r.adjustment), m, ADJUSTMENT_BUCKETS),
        ),
        ("card class", _breakdown(drilled, lambda r: r.card_class or "unknown", m)),
        ("handoff mode", _breakdown(drilled, lambda r: r.mode or "unknown", m)),
        ("deck", _breakdown(drilled, lambda r: r.deck, m)),
    ]
    suggestions = [
        suggest_t(drilled, cfg.min_words_to_chunk, m),
        suggest_encode_reps(drilled, cfg.encode_reps, m),
    ]
    return Report(
        deck_filter=deck_filter,
        decks=decks,
        sessions=len(sessions),
        first_day=anki_day(min(starts), rollover, tz) if starts else None,
        last_day=anki_day(max(ends_ms), rollover, tz) if ends_ms else None,
        comparison=comparison,
        breakdowns=breakdowns,
        suggestions=suggestions,
        rows=rows,
        first_session_ms=first_session_ms(history_lines),
    )


def tuning_line(s: Suggestion, at_ms: float, deck_filter: str | None) -> dict[str, Any]:
    """The ``type: "tuning"`` history line for an applied suggestion."""
    return {
        "type": "tuning",
        "timestamp": js_iso_string(at_ms),
        "parameter": s.parameter,
        "configKey": s.parameter,
        "old": s.current,
        "new": s.proposed,
        "verdict": s.verdict,
        "evidence": list(s.evidence),
        "deckFilter": deck_filter,
    }


def confirmation_text(s: Suggestion, deck_filter: str | None, overrides: Sequence[str]) -> str:
    """What the Apply confirmation shows: old → new and the evidence."""
    scope = f"the {deck_filter} deck" if deck_filter else "all decks"
    lines = [
        f"Change the add-on's default {s.label} from {s.current} to {s.proposed}?",
        "",
        s.verdict,
        "",
        f"Evidence ({scope}):",
        *(f"• {e}" for e in s.evidence),
    ]
    if s.caveat:
        lines += ["", s.caveat]
    if overrides:
        lines += [
            "",
            "These decks have their own saved value, which wins over the default: "
            + ", ".join(overrides)
            + ".",
        ]
    lines += ["", "It applies to sessions started from now on (config.json)."]
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------


def _num(x: float | None, fmt: str = "{:.1f}") -> str:
    return "—" if x is None else fmt.format(x)


def header_lines(r: Report) -> list[str]:
    rng = (
        f"{r.first_day.isoformat()} to {r.last_day.isoformat()}"
        if r.first_day and r.last_day
        else "no sessions yet"
    )
    cards, outcomes, late, pending = r.counts("drilled")
    out = [
        f"Scope: {r.deck_filter or 'all decks'}",
        f"Sessions: {r.sessions} ({rng})",
        f"Drilled cards handed off: {cards}: {outcomes} with a next-day outcome, "
        f"{late} rated later than 2 days (excluded), {pending} pending.",
    ]
    h_cards, h_out, h_late, h_pending = r.counts("holdout")
    if h_cards:
        out.append(
            f"Holdout cards: {h_cards}: {h_out} with an outcome, {h_late} excluded, "
            f"{h_pending} pending."
        )
    return out


COMPARISON_COLUMNS = ("Group", "n", "Again", "95% CI", "Trials/card", "Misses+reveals/card")
BREAKDOWN_COLUMNS = ("Group", "n", "Again (95% CI)", "Trials/card", "Pending")


def comparison_cells(s: Stat) -> list[str]:
    if s.too_small:
        again, ci = TOO_SMALL, ""
    else:
        lo, hi = s.ci
        again, ci = _pct(s.rate or 0.0), f"{_pct(lo)}–{_pct(hi)}"
    return [s.label, str(s.n), again, ci, _num(s.trials), _num(s.struggle)]


def breakdown_cells(s: Stat) -> list[str]:
    return [s.label, str(s.n), s.rate_text(), _num(s.trials), str(s.pending)]


def _table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> list[str]:
    widths = [max([len(h), *(len(r[i]) for r in rows)]) for i, h in enumerate(header)]

    def fmt(cells: Sequence[str]) -> str:
        return "  ".join(c.ljust(w) for c, w in zip(cells, widths, strict=True)).rstrip()

    return [fmt(header), fmt(["-" * w for w in widths]), *(fmt(r) for r in rows)]


def render_text(r: Report) -> str:
    out = ["Recall Drill: tuning report", "", *header_lines(r), "", CONFOUND_WARNING, ""]
    out += _table(COMPARISON_COLUMNS, [comparison_cells(s) for s in r.comparison])
    out.append("(n: next-day outcomes, 1–2 days after t0. Costs are per handed-off card.)")
    for title, stats in r.breakdowns:
        out += ["", f"Drilled cards by {title}:"]
        out += _table(BREAKDOWN_COLUMNS, [breakdown_cells(s) for s in stats])
    out += ["", "Suggestions:"]
    for s in r.suggestions:
        out.append(f"- {s.label} (now {s.current}): {s.verdict}")
        out += [f"    {e}" for e in s.evidence]
        if s.caveat:
            out.append(f"    {s.caveat}")
    return "\n".join(out)


def _html_table(header: Sequence[str], rows: Sequence[Sequence[str]]) -> str:
    head = "".join(f"<th>{html.escape(h)}</th>" for h in header)
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(c)}</td>" for c in row) + "</tr>" for row in rows
    )
    return f'<table border="1" cellspacing="0" cellpadding="4"><tr>{head}</tr>{body}</table>'


def render_html(r: Report) -> str:
    """The dialog's body (Qt rich text). Suggestions get their buttons in Qt."""
    parts = [
        "<p>" + "<br>".join(html.escape(x) for x in header_lines(r)) + "</p>",
        f"<p><i>{html.escape(CONFOUND_WARNING)}</i></p>",
        "<h3>Next-day Again</h3>",
        _html_table(COMPARISON_COLUMNS, [comparison_cells(s) for s in r.comparison]),
        "<p><small>n: next-day outcomes (1–2 Anki days after t0). Trials and misses + "
        "reveals are per handed-off card.</small></p>",
    ]
    for title, stats in r.breakdowns:
        parts.append(f"<h4>Drilled cards by {html.escape(title)}</h4>")
        parts.append(_html_table(BREAKDOWN_COLUMNS, [breakdown_cells(s) for s in stats]))
    return "\n".join(parts)


CSV_COLUMNS = (
    "group",
    "cid",
    "nid",
    "deck",
    "session_id",
    "t0",
    "status",
    "rating_time",
    "elapsed_days",
    "ease",
    "again",
    "words",
    "chunks",
    "encode_reps",
    "adjustment",
    "card_class",
    "handoff_mode",
    "attempts",
    "misses",
    "reveals",
    "final_misses",
)


def _local(ms: int | None, tz: tzinfo | None) -> str:
    if ms is None:
        return ""
    return datetime.fromtimestamp(ms / 1000, tz).isoformat(timespec="seconds")


def to_csv(r: Report, tz: tzinfo | None = None) -> str:
    """The per-card outcome table (Copy as CSV)."""
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(CSV_COLUMNS)

    def cell(v: object) -> object:
        return "" if v is None else v

    for row in r.rows:
        o = row.outcome
        w.writerow(
            [
                cell(x)
                for x in (
                    row.group,
                    row.cid,
                    row.nid,
                    row.deck,
                    row.session_id,
                    _local(o.t0_ms, tz),
                    o.status,
                    _local(o.rating_ms, tz),
                    o.elapsed,
                    o.ease,
                    None if o.again is None else int(o.again),
                    row.words,
                    row.chunks,
                    row.encode_reps,
                    row.adjustment,
                    row.card_class,
                    row.mode,
                    row.attempts,
                    row.misses,
                    row.reveals,
                    row.final_misses,
                )
            ]
        )
    return buf.getvalue()
