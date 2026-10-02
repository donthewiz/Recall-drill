"""From the setup panel's choices to a running session (pure, on ``storage``).

The panel (``ui/setup_dialog.py``) reads cards with ``anki_io`` and hands the
result here: the session config comes from the deck's settings over the add-on
config, the deck settings are saved (Start is one of the two places they are
saved; the panel's Save is the other), and ``sessions`` starts or resumes.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from . import deck_settings, sessions
from .addon_config import AddonConfig
from .controller import ControllerSettings, DrillController
from .deck_settings import DeckSettings, ResolvedSettings
from .engine.types import DeckItem
from .sessions import NewSessionConfig, ScopeJson, SessionStore
from .sources import SourceRef
from .storage import Storage


def now_ms() -> int:
    return int(time.time() * 1000)


def config_defaults(cfg: AddonConfig) -> ResolvedSettings:
    """The add-on config as per-deck defaults (``deck_settings.resolve``'s base)."""
    return {
        "strictPunctuation": deck_settings.DEFAULTS["strictPunctuation"],
        "stemTolerance": cfg.stem_tolerance,
        "batchSize": cfg.batch_size,
        "encodeReps": cfg.encode_reps,
        "cycleOrder": cfg.cycle_order,
        "card_ords": {},
    }


def resolved(settings: DeckSettings | None, cfg: AddonConfig) -> ResolvedSettings:
    return deck_settings.resolve(settings, config_defaults(cfg))


def session_config(settings: DeckSettings | None, cfg: AddonConfig) -> NewSessionConfig:
    """App.handleStartSession's arguments: the deck's settings, then the config."""
    r = resolved(settings, cfg)
    return {
        "encodeReps": r["encodeReps"],
        "chunkDifficulty": cfg.chunk_difficulty,
        "stemTolerance": r["stemTolerance"],
        "ladderMode": cfg.ladder_mode,
        "strictPunctuation": r["strictPunctuation"],
        "batchSize": r["batchSize"],
        "cycleOrder": r["cycleOrder"],
        "minWordsToChunk": cfg.min_words_to_chunk,
    }


def controller_settings(
    cfg: AddonConfig, deck_name: str, *, drill_again: bool = False
) -> ControllerSettings:
    return ControllerSettings(
        deck_name=deck_name,
        collision_catch=cfg.collision_catch,
        play_audio_on_feedback=cfg.play_audio_on_feedback,
        source_deck_editable=not drill_again,
        autoplay_question_audio=cfg.autoplay_question_audio,
    )


def start(
    storage: Storage,
    *,
    scope: ScopeJson,
    deck_name: str,
    deck_items: Sequence[DeckItem],
    sources: Sequence[SourceRef],
    settings_did: int | None,
    settings: DeckSettings,
    select_options: Mapping[str, Any],
    hints: bool,
    cfg: AddonConfig,
    clock: Callable[[], int] = now_ms,
    holdout: Sequence[Mapping[str, Any]] = (),
) -> tuple[DrillController, SessionStore]:
    """Start: save the deck's settings, then a fresh session (overwriting any
    save under the scope's key). ``holdout``: the cards the selection held out
    (recorded in the save, handed off as new cards). Raises ``ValueError`` on 0 cards."""
    if not deck_items:
        raise ValueError("nothing to drill")
    if settings_did is not None:
        deck_settings.save(storage, settings_did, settings)
    return sessions.start_session(
        storage,
        key=sessions.scope_key(scope),
        deck_items=deck_items,
        sources=sources,
        config=session_config(settings, cfg),
        scope=scope,
        select_options=select_options,
        deck_settings=dict(settings),
        hints=hints,
        settings=controller_settings(cfg, deck_name),
        now_ms=clock,
        holdout=holdout,
    )


def resume(
    storage: Storage,
    key: str,
    saved: Mapping[str, Any],
    cfg: AddonConfig,
    clock: Callable[[], int] = now_ms,
) -> tuple[DrillController, SessionStore]:
    """Resume (or "Resume with saved text"): the save's own settings, the
    config's audio and catch switches."""
    name = str(saved.get("deckName") or "")
    return sessions.open_saved(storage, key, saved, controller_settings(cfg, name), clock)


def drill_again(
    storage: Storage,
    parent: DrillController,
    parent_store: SessionStore,
    cfg: AddonConfig,
    clock: Callable[[], int] = now_ms,
) -> tuple[DrillController, SessionStore]:
    """DoneView's "Drill these cards again": session-only, same settings."""
    settings = controller_settings(cfg, parent.settings.deck_name, drill_again=True)
    return sessions.start_drill_again(storage, parent, parent_store, settings, clock)
