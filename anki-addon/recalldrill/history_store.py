"""Completed-session history and cold-start estimates (pure, on ``storage``).

``history/<deck or search key>.jsonl`` is append-only, one JSON object per line:

- ``type: "session"``: one per completed session (written here, at completion):
  ``sessionId``, the web app's ``buildHistoryEntry`` fields, an ``anki`` block
  (per card ``cid, nid, ord, card_class``), the encode settings used, the scope,
  ``collisions`` and ``holdout: []`` (Phase 5 fills it in).
- ``type: "handoff"``: Phase 4 appends one per handoff, with the same ``sessionId``.

Lines are never rewritten, and there is no ``MAX_HISTORY_ENTRIES`` cap: Phase 5
reads the whole log. :func:`read_recent` serves the panel.

``estimates.json`` ports the web app's ``get/saveColdStartHistory``
(``cold-start-history:<slug>``): session key -> ``{multiplier, deckShape,
measuredAt}``, the cumulative actual/minimum trial multiplier measured when a
session ended. Setup reads it in place of the exposure-level seed.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any, NotRequired, TypedDict, cast

from .engine.estimate import (
    ColdStartDeckShape,
    compute_cumulative_cold_start_multiplier,
    pick_cold_start_deck_shape,
)
from .engine.history import build_history_entry
from .engine.items import MIN_WORDS_TO_CHUNK
from .engine.jscompat import js_iso_string
from .engine.types import SessionState
from .sources import SourceRef
from .storage import ESTIMATES, HISTORY_DIR, Storage


class AnkiCardRef(TypedDict):
    cid: int
    nid: int
    ord: int
    card_class: str


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
        "MIN_WORDS_TO_CHUNK": MIN_WORDS_TO_CHUNK,
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
) -> dict[str, Any]:
    """One ``type: "session"`` history line."""
    entry = build_history_entry(state, finished_at)
    by_id = {i["id"]: i for i in state["items"]}
    anki: list[AnkiCardRef] = []
    for item_id in sorted(by_id):
        s = sources[item_id]
        anki.append({"cid": s.cid, "nid": s.nid, "ord": s.ord, "card_class": s.card_class})
    return {
        "type": "session",
        "sessionId": session_id,
        **entry,
        "anki": anki,
        "encode": encode_settings(state, hints),
        "scope": dict(scope),
        "collisions": collisions,
        "holdout": [],
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
