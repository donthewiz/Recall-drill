"""Saved drill sessions (pure, on ``storage``): ``sessions/<key>.json``.

Keys: ``deck-<did>`` for a deck scope, ``search-<sha1(query)[:12]>`` for a
search, ``again-<parent key>`` for a "Drill these cards again" session.

A save is the web app's ``SavedSessionState`` exactly as SessionView builds it
(:meth:`DrillController.saved_dict`), plus an ``addon`` block:

- ``sources`` (one per engine item) and ``collisions`` (from the controller);
- ``scope``, ``selectOptions``, ``deckSettings`` (a snapshot) and ``hints``;
- ``sessionId`` (uuid4 hex, made at Start; Phase 4 links its handoff to it),
  ``startedAt`` (epoch ms);
- ``handoffPending`` and ``historyWritten``;
- ``drillAgainOf``: the parent key, for a drill-again session;
- ``holdout``: the cards the selection held out as the measurement control
  (Phase 5: ``cid, nid, ord, did, card_class`` each). They aren't drilled; the
  handoff hands them to Anki as new cards, tagged ``rd::holdout``.

Lifecycle, as App.tsx's ``handleFinishSession`` with the handoff on top:

- Every answer saves (atomic writes come from ``storage``).
- Save and stop / End session: the save stays and resumes later.
- The Final check completes: history is written once (``historyWritten``),
  then ``handoffPending`` is set and the save is kept. It is deleted only after
  a successful handoff (:func:`complete_handoff`) or when Don chooses "Don't
  hand off" (:func:`decline_handoff`); each appends a ``type: "handoff"``
  history line first. A pending save offers "Hand off finished session", never
  "Resume" (:func:`save_status`).
- A drill-again session writes no history and has no handoff: its save is
  deleted on completion, as the web app clears it.
"""

from __future__ import annotations

import hashlib
import uuid
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, NotRequired, TypedDict, cast

from .controller import ControllerSettings, DrillController
from .engine.items import MIN_WORDS_TO_CHUNK, build_items, normalize_item, resolve_batch_config
from .engine.jscompat import truthy
from .engine.session import SESSION_COMPLETE_ID, empty_stats, init_session
from .engine.types import (
    CycleOrder,
    DeckItem,
    LadderMode,
    SessionConfig,
    SessionState,
    SessionStats,
)
from .history_store import (
    append_handoff,
    append_session,
    build_session_line,
    declined_line,
    record_cold_start,
)
from .sources import SourceRef, source_from_json
from .storage import SESSIONS_DIR, Storage

SaveStatus = Literal["resume", "handoff"]


class ScopeJson(TypedDict):
    deckId: int | None
    search: str | None


class AppDefaults(TypedDict):
    """The App-level settings a resume falls back to for a field a save lacks."""

    chunkDifficulty: float
    ladderMode: LadderMode
    stemTolerance: bool


APP_DEFAULTS: AppDefaults = {
    "chunkDifficulty": 35,
    "ladderMode": "cumulative",
    "stemTolerance": True,
}


class NewSessionConfig(TypedDict):
    encodeReps: int
    chunkDifficulty: float
    stemTolerance: bool
    ladderMode: LadderMode
    strictPunctuation: bool
    batchSize: int
    cycleOrder: NotRequired[CycleOrder]
    minWordsToChunk: NotRequired[int]
    """The add-on's chunking threshold (an engine extension); absent: the TS constant."""


# ---------------------------------------------------------------------------
# Keys
# ---------------------------------------------------------------------------


def deck_key(did: int) -> str:
    return f"deck-{did}"


def search_key(query: str) -> str:
    return f"search-{hashlib.sha1(query.encode('utf-8')).hexdigest()[:12]}"


def again_key(parent_key: str) -> str:
    return f"again-{parent_key}"


def scope_json(deck_id: int | None = None, search: str | None = None) -> ScopeJson:
    if (deck_id is None) == (search is None):
        raise ValueError("a scope needs exactly one of deck_id or search")
    return {"deckId": deck_id, "search": search}


def scope_key(scope: ScopeJson) -> str:
    did = scope["deckId"]
    if did is not None:
        return deck_key(did)
    search = scope["search"]
    assert search is not None
    return search_key(search)


def history_key(scope: ScopeJson) -> str:
    """``history/<did or search key>.jsonl``."""
    did = scope["deckId"]
    return str(did) if did is not None else scope_key(scope)


def save_name(key: str) -> str:
    return f"{SESSIONS_DIR}/{key}.json"


# ---------------------------------------------------------------------------
# The addon block
# ---------------------------------------------------------------------------


@dataclass
class SessionMeta:
    key: str
    session_id: str
    started_at: int
    scope: ScopeJson
    select_options: dict[str, Any]
    deck_settings: dict[str, Any]
    hints: bool
    drill_again_of: str | None = None
    handoff_pending: bool = False
    history_written: bool = False
    holdout: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])

    @property
    def is_drill_again(self) -> bool:
        return self.drill_again_of is not None

    def to_json(self) -> dict[str, Any]:
        return {
            "scope": dict(self.scope),
            "selectOptions": self.select_options,
            "deckSettings": self.deck_settings,
            "hints": self.hints,
            "sessionId": self.session_id,
            "startedAt": self.started_at,
            "handoffPending": self.handoff_pending,
            "historyWritten": self.history_written,
            "drillAgainOf": self.drill_again_of,
            "holdout": self.holdout,
        }

    @classmethod
    def from_json(cls, key: str, addon: Mapping[str, Any]) -> SessionMeta:
        scope = cast(Mapping[str, Any], addon.get("scope") or {})
        return cls(
            key=key,
            session_id=str(addon["sessionId"]),
            started_at=int(addon.get("startedAt") or 0),
            scope={"deckId": scope.get("deckId"), "search": scope.get("search")},
            select_options=dict(cast(Mapping[str, Any], addon.get("selectOptions") or {})),
            deck_settings=dict(cast(Mapping[str, Any], addon.get("deckSettings") or {})),
            hints=bool(addon.get("hints", False)),
            drill_again_of=cast(str | None, addon.get("drillAgainOf")),
            handoff_pending=bool(addon.get("handoffPending", False)),
            history_written=bool(addon.get("historyWritten", False)),
            holdout=[
                dict(cast(Mapping[str, Any], h))
                for h in cast(list[Any], addon.get("holdout") or [])
                if isinstance(h, dict)
            ],
        )


def new_session_id() -> str:
    return uuid.uuid4().hex


# ---------------------------------------------------------------------------
# Reading and deleting saves
# ---------------------------------------------------------------------------


def load(storage: Storage, key: str) -> dict[str, Any] | None:
    """The save for ``key``, or None (missing, corrupt, or not a session)."""
    data = storage.read_json(save_name(key), None)
    if not isinstance(data, dict):
        return None
    d = cast(dict[str, Any], data)
    addon = d.get("addon")
    if not isinstance(addon, dict) or "sessionId" not in addon or "items" not in d:
        return None
    return d


def save_status(saved: Mapping[str, Any]) -> SaveStatus:
    """A finished session waiting for its handoff is not resumable."""
    addon = cast(Mapping[str, Any], saved.get("addon") or {})
    return "handoff" if addon.get("handoffPending") else "resume"


def list_keys(storage: Storage) -> list[str]:
    prefix = f"{SESSIONS_DIR}/"
    return [n[len(prefix) : -len(".json")] for n in storage.list_names(SESSIONS_DIR, ".json")]


def delete(storage: Storage, key: str) -> bool:
    return storage.delete(save_name(key))


def discard(storage: Storage, key: str) -> bool:
    """ "Don't hand off" on a finished session (or Start fresh): the save goes."""
    return delete(storage, key)


def _pending_meta(key: str, saved: Mapping[str, Any]) -> SessionMeta:
    return SessionMeta.from_json(key, cast(Mapping[str, Any], saved["addon"]))


def complete_handoff(
    storage: Storage, key: str, saved: Mapping[str, Any], line: Mapping[str, Any]
) -> None:
    """After a successful handoff: its history line, then the save goes. The
    save goes even if the line can't be written (that error is re-raised): the
    cards are in Anki now, so the session mustn't be offered again."""
    meta = _pending_meta(key, saved)
    try:
        append_handoff(storage, history_key(meta.scope), line)
    finally:
        delete(storage, key)


def decline_handoff(storage: Storage, key: str, saved: Mapping[str, Any], now_ms: int) -> None:
    """ "Don't hand off": a declined line in the history, and the save goes."""
    meta = _pending_meta(key, saved)
    try:
        append_handoff(storage, history_key(meta.scope), declined_line(meta.session_id, now_ms))
    finally:
        delete(storage, key)


def saved_sources(saved: Mapping[str, Any]) -> list[SourceRef]:
    addon = cast(Mapping[str, Any], saved["addon"])
    return [source_from_json(cast(Mapping[str, Any], s)) for s in addon.get("sources", [])]


# ---------------------------------------------------------------------------
# The store: one session's save, history and estimates
# ---------------------------------------------------------------------------


class SessionStore:
    """The persist and finish callbacks for one :class:`DrillController`."""

    def __init__(self, storage: Storage, meta: SessionMeta, now_ms: Callable[[], int]) -> None:
        self.storage = storage
        self.meta = meta
        self._now_ms = now_ms

    @property
    def name(self) -> str:
        return save_name(self.meta.key)

    def persist(self, saved: dict[str, Any]) -> None:
        """The controller's ``persist``: its dict plus this session's meta."""
        out = dict(saved)
        out["addon"] = {**cast(Mapping[str, Any], saved.get("addon") or {}), **self.meta.to_json()}
        self.storage.write_json(self.name, out)

    def finish(self, ctrl: DrillController, complete: bool) -> None:
        """The controller's ``on_finish`` (SessionView's ``finishSession`` plus
        App's ``handleFinishSession``)."""
        state = ctrl.state
        record_cold_start(self.storage, self.meta.key, state, self._now_ms())
        if not complete:
            return  # the controller already saved the state as it stands
        if self.meta.is_drill_again:
            delete(self.storage, self.meta.key)
            return
        if not self.meta.history_written:
            append_session(
                self.storage,
                history_key(self.meta.scope),
                build_session_line(
                    session_id=self.meta.session_id,
                    state=state,
                    sources=ctrl.sources,
                    finished_at=self._now_ms(),
                    scope=self.meta.scope,
                    collisions=ctrl.collisions,
                    hints=self.meta.hints,
                    holdout=self.meta.holdout,
                ),
            )
            self.meta.history_written = True
        self.meta.handoff_pending = True
        self.persist(ctrl.saved_dict())


# ---------------------------------------------------------------------------
# Start and resume
# ---------------------------------------------------------------------------


def new_session_state(
    deck_items: Sequence[DeckItem], config: NewSessionConfig, now_ms: int
) -> SessionState:
    """App.handleStartSession then SessionView's initSession: deck order, no shuffle."""
    min_words = config.get("minWordsToChunk")
    items = build_items(
        deck_items,
        config["chunkDifficulty"],
        config["ladderMode"],
        config["batchSize"],
        MIN_WORDS_TO_CHUNK if min_words is None else min_words,
        shuffle_within_batch=False,
    )
    engine_config: SessionConfig = {
        "encodeReps": config["encodeReps"],
        "chunkDifficulty": config["chunkDifficulty"],
        "stemTolerance": config["stemTolerance"],
        "ladderMode": config["ladderMode"],
        "strictPunctuation": config["strictPunctuation"],
        "batchSize": config["batchSize"],
        "cycleOrder": config.get("cycleOrder", "shuffled"),
    }
    if min_words is not None:
        engine_config["minWordsToChunk"] = min_words
    stats: SessionStats = {**empty_stats(), "startTime": now_ms}
    return init_session(
        {
            "items": items,
            "phase": "encode",
            "queue": [],
            "stats": stats,
            "currentId": SESSION_COMPLETE_ID,
            "batchIndex": 0,
            "batchStartStats": empty_stats(),
            "config": engine_config,
        }
    )


def resume(saved: Mapping[str, Any], defaults: AppDefaults = APP_DEFAULTS) -> SessionState:
    """App.handleResumeSession, then SessionView's initial initSession."""

    def nullish(key: str, default: Any) -> Any:
        v = saved.get(key)
        return default if v is None else v

    mode = cast(LadderMode, nullish("ladderMode", defaults["ladderMode"]))
    items = [normalize_item(cast(Mapping[str, Any], it), mode) for it in saved["items"]]
    batch = resolve_batch_config(cast(Any, saved), items)
    stats = cast(SessionStats, {**empty_stats(), **saved["stats"]})
    start = saved.get("batchStartStats")
    batch_start = cast(
        SessionStats, {**empty_stats(), **(saved["stats"] if start is None else start)}
    )
    config: SessionConfig = {
        "encodeReps": saved["encodeReps"] if truthy(saved.get("encodeReps")) else 3,
        "chunkDifficulty": nullish("chunkDifficulty", defaults["chunkDifficulty"]),
        "stemTolerance": nullish("stemTolerance", defaults["stemTolerance"]),
        "ladderMode": mode,
        "strictPunctuation": nullish("strictPunctuation", False),
        "batchSize": batch["batchSize"],
        "cycleOrder": nullish("cycleOrder", "shuffled"),
    }
    min_words = saved.get("minWordsToChunk")
    if isinstance(min_words, int) and not isinstance(min_words, bool):
        config["minWordsToChunk"] = min_words
    state: SessionState = {
        "items": items,
        "phase": saved["phase"],
        "queue": list(saved.get("queue") or []),
        "stats": stats,
        "currentId": nullish("currentId", SESSION_COMPLETE_ID),
        "batchIndex": batch["batchIndex"],
        "batchStartStats": batch_start,
        "config": config,
    }
    fcs = saved.get("finalCheckStartAttempts")
    if fcs is not None:
        state["finalCheckStartAttempts"] = fcs
    return init_session(state)


def start_session(
    storage: Storage,
    *,
    key: str,
    deck_items: Sequence[DeckItem],
    sources: Sequence[SourceRef],
    config: NewSessionConfig,
    scope: ScopeJson,
    select_options: Mapping[str, Any],
    deck_settings: Mapping[str, Any],
    hints: bool,
    settings: ControllerSettings,
    now_ms: Callable[[], int],
    drill_again_of: str | None = None,
    holdout: Sequence[Mapping[str, Any]] = (),
) -> tuple[DrillController, SessionStore]:
    """A fresh session. Overwrites any save under ``key``. Call
    ``controller.start()`` once the window is up (it writes the first save)."""
    now = now_ms()
    meta = SessionMeta(
        key=key,
        session_id=new_session_id(),
        started_at=now,
        scope=scope,
        select_options=dict(select_options),
        deck_settings=dict(deck_settings),
        hints=hints,
        drill_again_of=drill_again_of,
        holdout=[dict(h) for h in holdout],
    )
    store = SessionStore(storage, meta, now_ms)
    ctrl = DrillController(
        new_session_state(deck_items, config, now),
        sources,
        settings,
        store.persist,
        now_ms,
        on_finish=store.finish,
    )
    return ctrl, store


def start_drill_again(
    storage: Storage,
    parent: DrillController,
    parent_store: SessionStore,
    settings: ControllerSettings,
    now_ms: Callable[[], int],
) -> tuple[DrillController, SessionStore]:
    """DoneView's "Drill these cards again" -> App.handleDrillAgain: a fresh,
    session-only session over the Final-check misses, same settings."""
    deck_items, sources = parent.drill_again_input()
    if not deck_items:
        raise ValueError("no Final-check misses to drill again")
    c = parent.state["config"]
    size = c.get("batchSize")
    config: NewSessionConfig = {
        "encodeReps": c["encodeReps"],
        "chunkDifficulty": c["chunkDifficulty"],
        "stemTolerance": c["stemTolerance"],
        "ladderMode": c["ladderMode"],
        "strictPunctuation": c.get("strictPunctuation", False),
        "batchSize": len(deck_items) if size is None else size,
        "cycleOrder": c.get("cycleOrder", "shuffled"),
    }
    min_words = c.get("minWordsToChunk")
    if min_words is not None:
        config["minWordsToChunk"] = min_words
    m = parent_store.meta
    return start_session(
        storage,
        key=again_key(m.key),
        deck_items=deck_items,
        sources=sources,
        config=config,
        scope=m.scope,
        select_options=m.select_options,
        deck_settings=m.deck_settings,
        hints=m.hints,
        settings=settings,
        now_ms=now_ms,
        drill_again_of=m.key,
    )


def open_saved(
    storage: Storage,
    key: str,
    saved: Mapping[str, Any],
    settings: ControllerSettings,
    now_ms: Callable[[], int],
    defaults: AppDefaults = APP_DEFAULTS,
) -> tuple[DrillController, SessionStore]:
    """Resume a save ("Resume", or "Resume with the saved text")."""
    if save_status(saved) == "handoff":
        raise ValueError("this session is finished and waiting for its handoff")
    addon = cast(Mapping[str, Any], saved["addon"])
    meta = SessionMeta.from_json(key, addon)
    store = SessionStore(storage, meta, now_ms)
    ctrl = DrillController(
        resume(saved, defaults),
        saved_sources(saved),
        settings,
        store.persist,
        now_ms,
        on_finish=store.finish,
        collisions=int(addon.get("collisions") or 0),
    )
    return ctrl, store
