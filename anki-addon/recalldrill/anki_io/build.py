"""Selection -> engine input.

``deck_items[i]`` is the engine's item ``i`` (its ``id`` stays the index, as in
the web app) and ``sources[i]`` says which card it came from and how to show
it. A card whose answer turns out empty is dropped (counted, never passed to
the engine).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, SearchNode
from anki.decks import DeckId

from ..deck_settings import DeckSettings, hints_enabled, standard_share
from ..engine.types import DeckItem
from ..prompts import HintEntry, compute_hints
from .cards import CardClass, NoteCache
from .notetypes import MappingTable, NoteMapping, answer_text, extra_html
from .select import Candidate, Selection
from .text import grading_text


@dataclass(frozen=True)
class SourceRef:
    """Where engine item ``i`` came from, and what to display for it."""

    cid: int
    nid: int
    ord: int
    did: int
    """The card's home deck (its original deck while in a filtered deck)."""
    ntid: int
    card_class: CardClass
    flags: int
    front_html: str
    """Anki's rendered question, as-is. Still holds ``[anki:play:q:N]`` and
    ``[[type:F]]`` placeholders for the display layer to deal with."""
    extra_html: str
    """The raw Extra field (anki-cards Extras carry <i>, lists and images)."""
    answer_hash: str
    """SHA-1 (hex) of the answer text, to notice later edits."""
    has_audio: bool
    """The answer side has sound or TTS (``card.answer_av_tags()``)."""
    hint: str = ""
    """The disambiguation suffix appended to the front, e.g. ``" (-a___)"``."""


@dataclass(frozen=True)
class FlaggedHint:
    """A card whose prompt conflicts with another and no auto hint can fix."""

    cid: int
    key: str
    term: str
    meaning: str
    conflicts: tuple[str, ...]


@dataclass
class BuildResult:
    deck_items: list[DeckItem]
    sources: list[SourceRef]
    hints_on: bool
    flagged_hints: list[FlaggedHint] = field(default_factory=list[FlaggedHint])
    empty_answers: int = 0
    hint_pool: int = 0
    """Cards the conflict check looked at."""


@dataclass(frozen=True)
class _Row:
    cand: Candidate
    front_html: str
    front: str
    answer: str
    extra_html: str
    extra: str
    has_audio: bool

    @property
    def key(self) -> str:
        return hint_key(self.cand.snap.nid, self.cand.snap.ord)


def hint_key(nid: int, ord_: int) -> str:
    """The hints.json key."""
    return f"{nid}:{ord_}"


def answer_hash(answer: str) -> str:
    return hashlib.sha1(answer.encode("utf-8")).hexdigest()


def top_level_name(col: Collection, did: int) -> str:
    return col.decks.name(DeckId(did)).split("::")[0]


def _rows(col: Collection, picked: Sequence[Candidate], notes: NoteCache) -> tuple[list[_Row], int]:
    rows: list[_Row] = []
    empty = 0
    for cand in picked:
        card = col.get_card(CardId(cand.snap.cid))
        front_html = card.render_output(reload=True).question_text
        note = notes.get(card.nid)
        answer = answer_text(col, note, cand.mapping, card.ord)
        if not answer:
            empty += 1
            continue
        x_html = extra_html(note, cand.mapping)
        rows.append(
            _Row(
                cand,
                front_html,
                grading_text(front_html),
                answer,
                x_html,
                grading_text(x_html),
                bool(card.answer_av_tags()),
            )
        )
    return rows, empty


def _hint_pool(
    col: Collection,
    top: str,
    mapping: NoteMapping,
    known: Mapping[str, HintEntry],
    mappings: MappingTable,
    notes: NoteCache,
) -> list[HintEntry]:
    """Every eligible card of this (note type, template) under the top-level deck."""
    search = col.build_search_string(
        SearchNode(deck=top), f"mid:{mapping.ntid}", f"card:{mapping.template_ord + 1}"
    )
    pool: list[HintEntry] = []
    for cid in col.find_cards(search):
        card = col.get_card(CardId(cid))
        key = hint_key(card.nid, card.ord)
        hit = known.get(key)
        if hit is not None:
            pool.append(hit)
            continue
        m = mappings.for_card(mapping.ntid, card.ord)
        if m.ineligible or m.answer_field is None:
            continue
        term = answer_text(col, notes.get(card.nid), m, card.ord)
        if not term:
            continue
        meaning = grading_text(card.render_output(reload=True).question_text)
        pool.append(HintEntry(key, term, meaning))
    return pool


def build_session(
    col: Collection,
    selection: Selection,
    deck_settings: DeckSettings | None,
    mappings: MappingTable,
    hints: Mapping[str, str],
    notes: NoteCache | None = None,
) -> BuildResult:
    """Everything the session and the panel need from a selection."""
    cache = notes if notes is not None else NoteCache(col)
    rows, empty = _rows(col, selection.picked, cache)
    hints_on = hints_enabled(deck_settings, standard_share(r.cand.mapping.kind for r in rows))

    suffixes: dict[str, str] = {}
    flagged: list[FlaggedHint] = []
    pool_size = 0
    if hints_on:
        groups: dict[tuple[str, int, int], list[_Row]] = {}
        for r in rows:
            m = r.cand.mapping
            if m.kind != "standard":
                continue
            top = top_level_name(col, r.cand.snap.home_did)
            groups.setdefault((top, m.ntid, m.template_ord), []).append(r)
        for (top, _, _), group in groups.items():
            targets = [HintEntry(r.key, r.answer, r.front) for r in group]
            known = {t.key: t for t in targets}
            pool = _hint_pool(col, top, group[0].cand.mapping, known, mappings, cache)
            pool_size += len(pool)
            result = compute_hints(targets, pool, hints)
            suffixes.update(result.suffixes)
            cids = {r.key: r.cand.snap.cid for r in group}
            flagged.extend(
                FlaggedHint(cids[t.key], t.key, t.term, t.meaning, tuple(result.conflicts[t.key]))
                for t in result.flagged
            )

    deck_items: list[DeckItem] = []
    sources: list[SourceRef] = []
    for r in rows:
        hint = suffixes.get(r.key, "")
        item: DeckItem = {"front": r.front + hint, "back": r.answer}
        if r.extra:
            item["extra"] = r.extra
        deck_items.append(item)
        s = r.cand.snap
        sources.append(
            SourceRef(
                cid=s.cid,
                nid=s.nid,
                ord=s.ord,
                did=s.home_did,
                ntid=s.ntid,
                card_class=r.cand.card_class,
                flags=s.flags,
                front_html=r.front_html,
                extra_html=r.extra_html,
                answer_hash=answer_hash(r.answer),
                has_audio=r.has_audio,
                hint=hint,
            )
        )
    return BuildResult(deck_items, sources, hints_on, flagged, empty, pool_size)


def build_session_items(
    col: Collection,
    selection: Selection,
    deck_settings: DeckSettings | None,
    mappings: MappingTable,
    hints: Mapping[str, str],
) -> tuple[list[DeckItem], list[SourceRef]]:
    """(deck_items, sources) in selection order; item ``i`` <-> ``sources[i]``."""
    r = build_session(col, selection, deck_settings, mappings, hints)
    return r.deck_items, r.sources
