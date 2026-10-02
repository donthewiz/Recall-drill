"""Completed-session history and cold-start estimates (pure, on ``storage``).

``history/<deck or search key>.jsonl`` is append-only, one JSON object per line:

- ``type: "session"``: one per completed session (written here, at completion):
  ``sessionId``, the web app's ``buildHistoryEntry`` fields, an ``anki`` block
  (per card ``cid, nid, ord, did, card_class``, parallel to the entry's
  ``cards``; Phase 6 adds ``d`` and ``s``, the card's FSRS difficulty and
  stability when the session was built (None without FSRS), ``encodeReps`` and
  ``minWordsToChunk``, the reps and chunk threshold the card was drilled with,
  and ``adjust``, +1 / 0 / -1 against the session's ``encodeReps``, and
  ``activeMs``, the card's share of the active drill time), ``activeMs`` (the
  session's active drill time; lines before Phase 6 have none), the
  encode settings used, the scope, ``collisions`` and
  ``holdout`` (the cards held out as the measurement control, Phase 5).
- ``type: "handoff"``: one per handoff (``anki_io/handoff.py``, ``handoff_line``),
  with the same ``sessionId``: mode, timestamp, the card ids per group, what
  was done, the tag counts, per card ``struggle`` and ``hard``, and the
  forecast. "Don't hand off" writes ``{"type": "handoff", "declined": true}``
  instead (:func:`declined_line`).

Lines are never rewritten, and there is no ``MAX_HISTORY_ENTRIES`` cap: Phase 5
reads the whole log. :func:`read_recent` serves the panel.

``estimates.json`` ports the web app's ``get/saveColdStartHistory``
(``cold-start-history:<slug>``): session key -> ``{multiplier, deckShape,
measuredAt}``, the cumulative actual/minimum trial multiplier measured when a
session ended. Setup reads it in place of the exposure-level seed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from .engine.estimate import (
    ColdStartDeckShape,
    compute_cumulative_cold_start_multiplier,
    pick_cold_start_deck_shape,
)
from .engine.history import build_history_entry
from .engine.items import MIN_WORDS_TO_CHUNK, min_words_for, reps_for
from .engine.jscompat import js_iso_string
from .engine.types import SessionState
from .sources import SourceRef
from .storage import ESTIMATES, HISTORY_DIR, Storage


class AnkiCardRef(TypedDict):
    cid: int
    nid: int
    ord: int
    did: int
    card_class: str
    d: float | None
    """FSRS difficulty (1-10) when the session was built, or None."""
    s: float | None
    """FSRS stability (days) when the session was built, or None."""
    encodeReps: int
    """The reps this card's ``encodeReps`` steps needed."""
    minWordsToChunk: int
    """The chunk threshold this card was built with."""
    adjust: int
    """+1 / 0 / -1: ``encodeReps`` against the session's."""
    activeMs: int
    """The card's share of the session's active drill time."""


class EncodeSettings(TypedDict):
    encodeReps: int
    chunkDifficulty: float
    MIN_WORDS_TO_CHUNK: int
    ladderMode: str
    batchSize: NotRequired[int]
    strictPunctuation: bool
    stemTolerance: bool
    hints: bool


class ColdStartHistory(TypedDict):
    multiplier: float
    deckShape: ColdStartDeckShape
    measuredAt: str


def history_name(history_key: str) -> str:
    return f"{HISTORY_DIR}/{history_key}.jsonl"


def encode_settings(state: SessionState, hints: bool) -> EncodeSettings:
    """The settings a session's items were encoded with (for the history line)."""
    c = state["config"]
    out: EncodeSettings = {
        "encodeReps": c["encodeReps"],
        "chunkDifficulty": c["chunkDifficulty"],
        "MIN_WORDS_TO_CHUNK": c.get("minWordsToChunk", MIN_WORDS_TO_CHUNK),
        "ladderMode": c["ladderMode"],
        "strictPunctuation": c.get("strictPunctuation", False),
        "stemTolerance": c["stemTolerance"],
        "hints": hints,
    }
    batch = c.get("batchSize")
    if batch is not None:
        out["batchSize"] = batch
    return out


def build_session_line(
    *,
    session_id: str,
    state: SessionState,
    sources: Sequence[SourceRef],
    finished_at: float,
    scope: Mapping[str, Any],
    collisions: int,
    hints: bool,
    holdout: Sequence[Mapping[str, Any]] = (),
    active_ms: int = 0,
    active_ms_by_item: Mapping[int, int] | None = None,
) -> dict[str, Any]:
    """One ``type: "session"`` history line. ``anki`` follows ``state["items"]``,
    so it is parallel to the entry's ``cards`` (the add-on never reorders items,
    so that is item id order too)."""
    entry = build_history_entry(state, finished_at)
    config = state["config"]
    session_min_words = config.get("minWordsToChunk", MIN_WORDS_TO_CHUNK)
    anki: list[AnkiCardRef] = []
    for item in state["items"]:
        s = sources[item["id"]]
        reps = reps_for(item, config)
        anki.append(
            {
                "cid": s.cid,
                "nid": s.nid,
                "ord": s.ord,
                "did": s.did,
                "card_class": s.card_class,
                "d": s.fsrs_d,
                "s": s.fsrs_s,
                "encodeReps": reps,
                "minWordsToChunk": min_words_for(item, session_min_words),
                "adjust": (reps > config["encodeReps"]) - (reps < config["encodeReps"]),
                "activeMs": (active_ms_by_item or {}).get(item["id"], 0),
            }
        )
    return {
        "type": "session",
        "sessionId": session_id,
        **entry,
        "anki": anki,
        "encode": encode_settings(state, hints),
        "scope": dict(scope),
        "collisions": collisions,
        "holdout": [dict(h) for h in holdout],
        "activeMs": active_ms,
    }


def has_session_line(storage: Storage, history_key: str, session_id: str) -> bool:
    return any(
        isinstance(line, dict)
        and cast(dict[str, Any], line).get("type") == "session"
        and cast(dict[str, Any], line).get("sessionId") == session_id
        for line in storage.read_jsonl(history_name(history_key))
    )


def append_session(storage: Storage, history_key: str, line: Mapping[str, Any]) -> bool:
    """Appends ``line`` unless its ``sessionId`` already has a session line (a
    crash between the append and the save's ``historyWritten`` flag). Returns
    whether it wrote."""
    if has_session_line(storage, history_key, str(line["sessionId"])):
        return False
    storage.append_jsonl(history_name(history_key), dict(line))
    return True


def append_handoff(storage: Storage, history_key: str, line: Mapping[str, Any]) -> None:
    """Appends a ``type: "handoff"`` line (a handoff, or a declined one)."""
    if line.get("type") != "handoff":
        raise ValueError("not a handoff line")
    storage.append_jsonl(history_name(history_key), dict(line))


def declined_line(session_id: str, at_ms: float) -> dict[str, Any]:
    """ "Don't hand off": the session's save is deleted and nothing is written to Anki."""
    return {
        "type": "handoff",
        "sessionId": session_id,
        "declined": True,
        "timestamp": js_iso_string(at_ms),
    }


@dataclass(frozen=True)
class HardCards:
    """Per card, whether its latest handoff found it hard (``rd::hard`` is a note
    tag, so a note's other cards share it). Cards never handed off are in neither."""

    hard: frozenset[int]
    not_hard: frozenset[int]


def hard_cards(storage: Storage) -> HardCards:
    """Every history log's handoff lines (declined ones aside), latest per card."""
    latest: dict[int, tuple[str, bool]] = {}
    for name in storage.list_names(HISTORY_DIR, ".jsonl"):
        for raw in storage.read_jsonl(name):
            if not isinstance(raw, dict):
                continue
            line = cast(dict[str, Any], raw)
            if line.get("type") != "handoff" or line.get("declined"):
                continue
            at = str(line.get("timestamp") or "")
            for card in cast(list[Any], line.get("cards") or []):
                if not isinstance(card, dict):
                    continue
                c = cast(dict[str, Any], card)
                cid = c.get("cid")
                if not isinstance(cid, int) or isinstance(cid, bool):
                    continue
                prev = latest.get(cid)
                if prev is None or at >= prev[0]:
                    latest[cid] = (at, bool(c.get("hard")))
    return HardCards(
        hard=frozenset(cid for cid, (_, h) in latest.items() if h),
        not_hard=frozenset(cid for cid, (_, h) in latest.items() if not h),
    )


HANDED_OFF_GROUPS = ("drilled_new", "siblings", "holdout", "holdout_siblings")
"""The handoff line's groups that go to Anki as new cards (handoff B's drilled
cards stay new; siblings and holdout cards always do)."""


def handed_off_cids(storage: Storage) -> frozenset[int]:
    """Every card a handoff (declined ones aside) sent to Anki as a new card, in
    any history log. Selection leaves out the ones still new (``SelectOptions.
    exclude_handed_off``): they are waiting for their first Anki review."""
    out: set[int] = set()
    for name in storage.list_names(HISTORY_DIR, ".jsonl"):
        for raw in storage.read_jsonl(name):
            if not isinstance(raw, dict):
                continue
            line = cast(dict[str, Any], raw)
            if line.get("type") != "handoff" or line.get("declined"):
                continue
            groups = line.get("groups")
            if not isinstance(groups, dict):
                continue
            for key in HANDED_OFF_GROUPS:
                for cid in cast(list[Any], cast(dict[str, Any], groups).get(key) or []):
                    if isinstance(cid, int) and not isinstance(cid, bool):
                        out.add(cid)
    return frozenset(out)


TUNING_KEY = "tuning"
"""``history/tuning.jsonl``: one ``type: "tuning"`` line per applied suggestion."""


def append_tuning(storage: Storage, line: Mapping[str, Any]) -> None:
    if line.get("type") != "tuning":
        raise ValueError("not a tuning line")
    storage.append_jsonl(history_name(TUNING_KEY), dict(line))


def read_every_log(storage: Storage) -> list[dict[str, Any]]:
    """Every line of every history log (the tuning report reads them all)."""
    out: list[dict[str, Any]] = []
    for name in storage.list_names(HISTORY_DIR, ".jsonl"):
        out += [cast(dict[str, Any], x) for x in storage.read_jsonl(name) if isinstance(x, dict)]
    return out


def read_all(storage: Storage, history_key: str) -> list[dict[str, Any]]:
    return [
        cast(dict[str, Any], x)
        for x in storage.read_jsonl(history_name(history_key))
        if isinstance(x, dict)
    ]


def read_recent(storage: Storage, history_key: str, n: int) -> list[dict[str, Any]]:
    """The last ``n`` session lines, newest last (the panel's history list)."""
    sessions = [x for x in read_all(storage, history_key) if x.get("type") == "session"]
    return sessions[-n:] if n > 0 else []


# ---------------------------------------------------------------------------
# Cold-start estimates
# ---------------------------------------------------------------------------


def _load_estimates(storage: Storage) -> dict[str, Any]:
    data = storage.read_json(ESTIMATES, {})
    return cast(dict[str, Any], data) if isinstance(data, dict) else {}


def get_cold_start_history(storage: Storage, key: str) -> ColdStartHistory | None:
    """``getColdStartHistory(slug)``."""
    if not key:
        return None
    raw = _load_estimates(storage).get(key)
    if not isinstance(raw, dict):
        return None
    d = cast(dict[str, Any], raw)
    m = d.get("multiplier")
    shape = d.get("deckShape")
    at = d.get("measuredAt")
    if not (isinstance(m, int | float) and not isinstance(m, bool) and isinstance(at, str)):
        return None
    if shape == "chunked" or shape == "full":
        return {"multiplier": float(m), "deckShape": shape, "measuredAt": at}
    return None


def save_cold_start_history(storage: Storage, key: str, history: ColdStartHistory) -> bool:
    """``saveColdStartHistory(slug, history)``."""
    if not key:
        return False
    data = _load_estimates(storage)
    data[key] = dict(history)
    storage.write_json(ESTIMATES, data)
    return True


def record_cold_start(storage: Storage, key: str, state: SessionState, now_ms: float) -> bool:
    """SessionView's ``finishSession`` part: the cumulative multiplier so far, if
    any batch is complete; nothing (and any older value kept) otherwise."""
    multiplier = compute_cumulative_cold_start_multiplier(state)
    if multiplier is None:
        return False
    return save_cold_start_history(
        storage,
        key,
        {
            "multiplier": multiplier,
            "deckShape": pick_cold_start_deck_shape(state["items"]),
            "measuredAt": js_iso_string(now_ms),
        },
    )
