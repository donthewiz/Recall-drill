"""The setup panel's data: selection, build, settings, estimate and the saved session.

No Qt: ``ui/setup_dialog.py`` calls these off the main thread (``QueryOp``) and
renders the result. Nothing here writes to the collection, and nothing here
saves settings: the panel saves them on Start or Save (``launch.start``,
``deck_settings.save``), hints on an edit (:func:`save_hint`) and mappings
from the mapping dialog (``notetypes.save_override``).

Replaces the Phase 2 dev preview (``anki_io/preview.py``).
"""

from __future__ import annotations

import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

from anki.collection import Collection

from .. import deck_settings, sessions
from ..addon_config import AddonConfig
from ..deck_settings import DeckSettings
from ..difficulty import SKIP_MAX_DIFFICULTY, SKIP_MIN_STABILITY, DifficultySummary, summarize
from ..engine.estimate import (
    ColdStartEstimate,
    ExposureLevel,
    compute_cold_start_estimate,
    format_cold_start_range,
)
from ..engine.items import MIN_WORDS_TO_CHUNK
from ..history_store import get_cold_start_history, hard_cards
from ..launch import resolved, session_config
from ..prompts import parse_hint_overrides
from ..sessions import SaveStatus
from ..storage import HINTS, Storage
from .build import BuildResult, DifficultyInputs, build_session
from .cards import NoteCache
from .handoff import HARD_SEARCH
from .notetypes import MappingTable, field_names, load_overrides
from .resume import ResumeCheck, check_resume
from .select import (
    Scope,
    Selection,
    SelectOptions,
    options_to_json,
    scope_to_json,
    select_cards,
)


@dataclass(frozen=True)
class NoteTypeTemplates:
    """A note type met in the scope, for the template filter and mapping dialog."""

    ntid: int
    name: str
    kind: str
    templates: tuple[tuple[int, str], ...]
    """(ord, name) of every template."""
    fields: tuple[str, ...]


@dataclass(frozen=True)
class HintRow:
    key: str
    """``"<note id>:<ord>"`` (the hints.json key)."""
    cid: int
    prompt: str
    term: str
    conflicts: tuple[str, ...]
    hint: str | None
    """The manual hint in hints.json (``""`` suppresses), or None."""
    flagged: bool
    """In a conflict no auto hint can fix: it needs a manual hint."""


@dataclass
class PanelData:
    scope: Scope
    label: str
    """The deck's full name, or the search."""
    key: str
    """The session key (``deck-<did>`` / ``search-<hash>``)."""
    settings_did: int | None
    saved_settings: DeckSettings | None
    proposal: DeckSettings | None
    """The terminology proposal: offered while nothing is saved for the deck."""
    settings: DeckSettings
    """What the panel is showing (the draft the build used)."""
    selection: Selection
    build: BuildResult
    note_types: list[NoteTypeTemplates]
    hint_rows: list[HintRow]
    estimate: ColdStartEstimate | None
    personal_history: bool
    seconds: float = 0.0
    select_options: dict[str, Any] = field(default_factory=dict[str, Any])
    holdout: list[dict[str, Any]] = field(default_factory=list[dict[str, Any]])
    """The held-out cards (``holdout_refs``), for the session save."""
    difficulty: DifficultySummary | None = None
    """The difficulty adjustment's counts (Phase 6)."""

    @property
    def stable_skipped(self) -> int:
        """Eligible ``stable`` cards left out because the class is off."""
        sel = self.selection
        return 0 if "stable" in sel.options.enabled else sel.eligible_counts.get("stable", 0)

    @property
    def drillable(self) -> int:
        return len(self.build.deck_items)

    @property
    def ineligible_total(self) -> int:
        return sum(self.selection.ineligible.values()) + self.build.empty_answers

    def estimate_text(self) -> str:
        """ "about 4–6 min" (``formatColdStartRange`` without its "~")."""
        if self.estimate is None:
            return ""
        r = format_cold_start_range(self.estimate["floorSeconds"], self.estimate["ceilingSeconds"])
        return "about " + r.removeprefix("~")


def scope_label(col: Collection, scope: Scope) -> str:
    name = scope.deck_name(col)
    return name if name is not None else str(scope.search)


def scope_key(scope: Scope) -> str:
    return sessions.scope_key(cast(sessions.ScopeJson, scope_to_json(scope)))


def settings_deck(col: Collection, storage: Storage, scope: Scope) -> int | None:
    """The deck whose settings a scope uses: the deck itself, or for a search the
    deck holding most of what it finds (with every template)."""
    if scope.deck_id is not None:
        return scope.deck_id
    table = MappingTable(col, load_overrides(storage))
    sel = select_cards(col, scope, SelectOptions(), table)
    return deck_settings.settings_deck(c.snap.home_did for c in sel.picked)


def initial_settings(storage: Storage, settings_did: int | None) -> DeckSettings:
    """The panel's starting draft: the saved settings, else nothing (defaults).
    The terminology proposal is offered, never applied by itself."""
    if settings_did is None:
        return {}
    return deck_settings.sanitize(deck_settings.get_saved(storage, settings_did) or {})


def _note_types(table: MappingTable, selection: Selection) -> list[NoteTypeTemplates]:
    out: list[NoteTypeTemplates] = []
    for ntid in sorted({ntid for ntid, _ in selection.mappings}):
        model = table.model(ntid)
        out.append(
            NoteTypeTemplates(
                ntid=ntid,
                name=str(model["name"]),
                kind=table.default_kind(ntid),
                templates=tuple((i, str(t["name"])) for i, t in enumerate(model["tmpls"])),
                fields=tuple(field_names(model)),
            )
        )
    return out


def _hint_rows(build: BuildResult, overrides: Mapping[str, str]) -> list[HintRow]:
    rows: list[HintRow] = []
    seen: set[str] = set()
    for f in build.flagged_hints:
        seen.add(f.key)
        rows.append(HintRow(f.key, f.cid, f.meaning, f.term, f.conflicts, None, True))
    for item, src in zip(build.deck_items, build.sources, strict=True):
        key = f"{src.nid}:{src.ord}"
        if key in seen or key not in overrides:
            continue
        seen.add(key)
        front = item["front"]
        prompt = front[: len(front) - len(src.hint)] if src.hint else front
        rows.append(
            HintRow(
                key, src.cid, prompt, item["back"], src.colliding_answers, overrides[key], False
            )
        )
    return rows


def read_panel(
    col: Collection,
    storage: Storage,
    scope: Scope,
    options: SelectOptions,
    settings: DeckSettings,
    settings_did: int | None,
    cfg: AddonConfig,
    exposure: ExposureLevel = "fresh",
) -> PanelData:
    """Everything the panel shows for one set of choices.

    ``options.card_ords`` should come from ``settings["card_ords"]`` (the
    template filter is a deck setting); ``settings`` is the panel's draft.
    """
    started = time.perf_counter()
    table = MappingTable(col, load_overrides(storage))
    notes = NoteCache(col)
    selection = select_cards(col, scope, options, table, notes)
    saved = deck_settings.get_saved(storage, settings_did) if settings_did is not None else None
    proposal = (
        deck_settings.propose_terminology_settings([c.answer for c in selection.picked])
        if saved is None
        else None
    )
    overrides = parse_hint_overrides(storage.read_json(HINTS, {}))
    r = resolved(settings, cfg)
    difficulty = DifficultyInputs(
        cfg.difficulty(r["difficultyAdjust"]), r["encodeReps"], cfg.min_words_to_chunk
    )
    build = build_session(
        col,
        selection,
        settings,
        table,
        overrides,
        notes,
        collisions=cfg.collision_catch,
        difficulty=difficulty,
    )
    key = scope_key(scope)
    history = get_cold_start_history(storage, key)
    estimate = None
    if build.deck_items:
        c = session_config(settings, cfg)
        estimate = compute_cold_start_estimate(
            build.deck_items,
            c["encodeReps"],
            c["chunkDifficulty"],
            c["ladderMode"],
            history["multiplier"] if history is not None else exposure,
            c.get("minWordsToChunk", MIN_WORDS_TO_CHUNK),
        )
    return PanelData(
        scope=scope,
        label=scope_label(col, scope),
        key=key,
        settings_did=settings_did,
        saved_settings=saved,
        proposal=proposal,
        settings=settings,
        selection=selection,
        build=build,
        note_types=_note_types(table, selection),
        hint_rows=_hint_rows(build, overrides),
        estimate=estimate,
        personal_history=history is not None,
        seconds=time.perf_counter() - started,
        select_options=options_to_json(options),
        holdout=holdout_refs(selection),
        difficulty=summarize(build.adjustments, difficulty.settings.adjust),
    )


def holdout_refs(selection: Selection) -> list[dict[str, Any]]:
    """The held-out cards as the session save and history line record them."""
    return [
        {
            "cid": c.snap.cid,
            "nid": c.snap.nid,
            "ord": c.snap.ord,
            "did": c.snap.home_did,
            "card_class": c.card_class,
        }
        for c in selection.holdout
    ]


def options_for(
    settings: DeckSettings,
    *,
    enabled: frozenset[Any],
    max_cards: int | None,
    extra_tag: str | None,
    order: Any,
    exclude_cids: frozenset[int] = frozenset(),
    holdout_pct: int = 0,
    holdout_salt: str = "",
    exclude_holdout_tag: bool = False,
    skip_min_stability: float = SKIP_MIN_STABILITY,
    skip_max_difficulty: float = SKIP_MAX_DIFFICULTY,
) -> SelectOptions:
    """``SelectOptions`` with the template filter taken from the deck settings."""
    return SelectOptions(
        enabled=enabled,
        card_ords=deck_settings.card_ords_option(settings),
        max_cards=max_cards,
        extra_tag=extra_tag or None,
        order=order,
        exclude_cids=exclude_cids,
        exclude_holdout_tag=exclude_holdout_tag,
        holdout_pct=holdout_pct,
        holdout_salt=holdout_salt,
        skip_min_stability=skip_min_stability,
        skip_max_difficulty=skip_max_difficulty,
    )


def hard_exclusions(storage: Storage, scope: Scope) -> frozenset[int]:
    """For the ``tag:rd::hard`` scope: the cards whose last handoff found them
    not hard (their note has the tag through a sibling). Empty for any other
    scope, and for cards never handed off."""
    if scope.search is None or scope.search.strip() != HARD_SEARCH:
        return frozenset()
    return hard_cards(storage).not_hard


def save_hint(storage: Storage, key: str, hint: str | None) -> None:
    """hints.json: set (``""`` suppresses the auto hint) or, with None, remove."""
    data = parse_hint_overrides(storage.read_json(HINTS, {}))
    if hint is None:
        data.pop(key, None)
    else:
        data[key] = hint
    storage.write_json(HINTS, data)


# ---------------------------------------------------------------------------
# The saved session for a scope
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SavedInfo:
    key: str
    saved: dict[str, Any]
    status: SaveStatus
    mastered: int
    total: int
    check: ResumeCheck | None
    """Only for a resumable save."""
    missing: tuple[str, ...]
    """"front → back" of the cards that are gone."""
    changed: tuple[str, ...]
    """"front → back" (as saved) of the cards whose answer changed."""


def _describe(saved: Mapping[str, Any], cids: Sequence[int]) -> tuple[str, ...]:
    sources = sessions.saved_sources(saved)
    items = cast(list[dict[str, Any]], saved.get("items") or [])
    by_id = {int(it["id"]): it for it in items}
    out: list[str] = []
    for cid in cids:
        idx = next((i for i, s in enumerate(sources) if s.cid == cid), None)
        it = by_id.get(idx) if idx is not None else None
        out.append(f"{it['front']} → {it['back']}" if it else f"card {cid}")
    return tuple(out)


def read_saved(col: Collection, storage: Storage, key: str) -> SavedInfo | None:
    saved = sessions.load(storage, key)
    if saved is None:
        return None
    status = sessions.save_status(saved)
    items = cast(list[dict[str, Any]], saved.get("items") or [])
    mastered = sum(1 for it in items if it.get("status") == "mastered")
    check = None
    missing: tuple[str, ...] = ()
    changed: tuple[str, ...] = ()
    if status == "resume":
        check = check_resume(col, saved, MappingTable(col, load_overrides(storage)))
        missing = _describe(saved, check.missing)
        changed = _describe(saved, check.changed)
    return SavedInfo(key, saved, status, mastered, len(items), check, missing, changed)
