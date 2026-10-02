"""Selection -> engine input.

``deck_items[i]`` is the engine's item ``i`` (its ``id`` stays the index, as in
the web app) and ``sources[i]`` says which card it came from and how to show
it. A card whose answer turns out empty is dropped (counted, never passed to
the engine).

A card whose front shows an image (``<img>``) gets no disambiguation hint and
stays out of the conflict pool: the cards of one figure share the same header
text, and the image is what tells them apart. ``SourceRef.image_front`` marks
them so later collision checks (another card's answer) skip them too.

**Difficulty** (Phase 6, ``difficulty.py``): with :class:`DifficultyInputs`,
each card's effective encode reps and chunk threshold come from its FSRS
difficulty (or, without FSRS, its review history). ``BuildResult.adjustments``
is a side table parallel to ``deck_items``; the session build stores
:meth:`BuildResult.overrides` on the engine items. Each ``SourceRef`` carries
the card's FSRS D and S, for the history line.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field, replace

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection, SearchNode
from anki.decks import DeckId
from anki.errors import NotFoundError

from ..deck_settings import DeckSettings, hints_enabled, standard_share
from ..difficulty import CardAdjustment, DifficultySettings, adjust_card
from ..engine.types import DeckItem, ItemOverrides
from ..prompts import HintEntry, compute_hints, find_conflicts
from ..sources import SourceRef
from .cards import NoteCache
from .notetypes import MappingTable, NoteMapping, answer_text, extra_html
from .select import Candidate, Selection
from .text import grading_text


@dataclass(frozen=True)
class FlaggedHint:
    """A card whose prompt conflicts with another and no auto hint can fix."""

    cid: int
    key: str
    term: str
    meaning: str
    conflicts: tuple[str, ...]


@dataclass(frozen=True)
class DifficultyInputs:
    """What the difficulty adjustment needs besides the card."""

    settings: DifficultySettings
    deck_reps: int
    """The session's ``encodeReps`` (the deck's "Blind typings required")."""
    deck_min_words: int
    """The session's chunk threshold (``min_words_to_chunk``)."""


@dataclass
class BuildResult:
    deck_items: list[DeckItem]
    sources: list[SourceRef]
    hints_on: bool
    flagged_hints: list[FlaggedHint] = field(default_factory=list[FlaggedHint])
    empty_answers: int = 0
    hint_pool: int = 0
    """Cards the conflict check looked at."""
    adjustments: list[CardAdjustment] = field(default_factory=list[CardAdjustment])
    """Parallel to ``deck_items`` when the build had :class:`DifficultyInputs`, else empty."""

    def overrides(self) -> list[ItemOverrides]:
        """The engine's per-item overrides, parallel to ``deck_items`` (empty: none)."""
        return [a.overrides() for a in self.adjustments]


@dataclass(frozen=True)
class _Row:
    cand: Candidate
    front_html: str
    front: str
    answer: str
    extra_html: str
    extra: str
    has_audio: bool
    answer_html: str
    css: str
    image_front: bool

    @property
    def key(self) -> str:
        return hint_key(self.cand.snap.nid, self.cand.snap.ord)


def hint_key(nid: int, ord_: int) -> str:
    """The hints.json key."""
    return f"{nid}:{ord_}"


def answer_hash(answer: str) -> str:
    return hashlib.sha1(answer.encode("utf-8")).hexdigest()


_IMG_RE = re.compile(r"<img\b", re.IGNORECASE)


def has_image(html: str) -> bool:
    return _IMG_RE.search(html) is not None


def top_level_name(col: Collection, did: int) -> str:
    return col.decks.name(DeckId(did)).split("::")[0]


def _rows(col: Collection, picked: Sequence[Candidate], notes: NoteCache) -> tuple[list[_Row], int]:
    rows: list[_Row] = []
    empty = 0
    for cand in picked:
        card = col.get_card(CardId(cand.snap.cid))
        out = card.render_output(reload=True)
        front_html = out.question_text
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
                out.answer_text,
                out.css,
                has_image(front_html),
            )
        )
    return rows, empty


def _hint_pool(
    col: Collection,
    top: str,
    mapping: NoteMapping,
    known: Mapping[str, HintEntry],
    skip: set[str],
    mappings: MappingTable,
    notes: NoteCache,
) -> list[HintEntry]:
    """Every eligible card of this (note type, template) under the top-level
    deck, except cards whose front shows an image."""
    search = col.build_search_string(
        SearchNode(deck=top), f"mid:{mapping.ntid}", f"card:{mapping.template_ord + 1}"
    )
    pool: list[HintEntry] = []
    for cid in col.find_cards(search):
        card = col.get_card(CardId(cid))
        key = hint_key(card.nid, card.ord)
        if key in skip:
            continue
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
        front_html = card.render_output(reload=True).question_text
        if has_image(front_html):
            continue
        pool.append(HintEntry(key, term, grading_text(front_html)))
    return pool


def build_session(
    col: Collection,
    selection: Selection,
    deck_settings: DeckSettings | None,
    mappings: MappingTable,
    hints: Mapping[str, str],
    notes: NoteCache | None = None,
    collisions: bool = True,
    difficulty: DifficultyInputs | None = None,
) -> BuildResult:
    """Everything the session and the panel need from a selection.

    ``collisions``: look up each card's colliding answers (the conflict pool is
    read even with hints off). False skips the pool when hints are off too.
    ``difficulty``: compute each card's adjustment (``BuildResult.adjustments``).
    """
    cache = notes if notes is not None else NoteCache(col)
    rows, empty = _rows(col, selection.picked, cache)
    hints_on = hints_enabled(deck_settings, standard_share(r.cand.mapping.kind for r in rows))

    suffixes: dict[str, str] = {}
    colliding: dict[str, tuple[str, ...]] = {}
    flagged: list[FlaggedHint] = []
    pool_size = 0
    if hints_on or collisions:
        groups: dict[tuple[str, int, int], list[_Row]] = {}
        image_keys = {r.key for r in rows if r.image_front}
        for r in rows:
            m = r.cand.mapping
            if m.kind != "standard" or r.image_front:
                continue
            top = top_level_name(col, r.cand.snap.home_did)
            groups.setdefault((top, m.ntid, m.template_ord), []).append(r)
        for (top, _, _), group in groups.items():
            targets = [HintEntry(r.key, r.answer, r.front) for r in group]
            known = {t.key: t for t in targets}
            pool = _hint_pool(col, top, group[0].cand.mapping, known, image_keys, mappings, cache)
            pool_size += len(pool)
            if hints_on:
                result = compute_hints(targets, pool, hints)
                conflicts = result.conflicts
                suffixes.update(result.suffixes)
                cids = {r.key: r.cand.snap.cid for r in group}
                flagged.extend(
                    FlaggedHint(cids[t.key], t.key, t.term, t.meaning, tuple(conflicts[t.key]))
                    for t in result.flagged
                )
            else:
                conflicts = find_conflicts(targets, pool)
            if collisions:
                for key, terms in conflicts.items():
                    colliding[key] = tuple(dict.fromkeys(terms))

    deck_items: list[DeckItem] = []
    sources: list[SourceRef] = []
    adjustments: list[CardAdjustment] = []
    for r in rows:
        hint = suffixes.get(r.key, "")
        item: DeckItem = {"front": r.front + hint, "back": r.answer}
        if r.extra:
            item["extra"] = r.extra
        deck_items.append(item)
        s = r.cand.snap
        if difficulty is not None:
            adjustments.append(
                adjust_card(s, difficulty.deck_reps, difficulty.deck_min_words, difficulty.settings)
            )
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
                answer_html=r.answer_html,
                css=r.css,
                image_front=r.image_front,
                hint=hint,
                colliding_answers=colliding.get(r.key, ()),
                fsrs_d=s.fsrs_d,
                fsrs_s=s.fsrs_s,
            )
        )
    return BuildResult(deck_items, sources, hints_on, flagged, empty, pool_size, adjustments)


@dataclass(frozen=True)
class RebuiltCard:
    """One card as ``build`` reads it now (after an edit in Anki's Browser)."""

    front: str
    """Grading text of the rendered front, plus the session's hint suffix."""
    back: str
    extra: str
    source: SourceRef


def rebuild_card(col: Collection, src: SourceRef, mappings: MappingTable) -> RebuiltCard | None:
    """Re-read one session card the way :func:`build_session` read it. The hint
    and the colliding answers are the session's (they depend on the whole
    pool). None when the card is gone or its answer is now empty."""
    try:
        card = col.get_card(CardId(src.cid))
    except NotFoundError:
        return None
    note = card.note()
    mapping = mappings.for_card(note.mid, card.ord)
    answer = answer_text(col, note, mapping, card.ord)
    if not answer:
        return None
    out = card.render_output(reload=True)
    x_html = extra_html(note, mapping)
    front_html = out.question_text
    source = replace(
        src,
        front_html=front_html,
        extra_html=x_html,
        answer_hash=answer_hash(answer),
        has_audio=bool(card.answer_av_tags()),
        answer_html=out.answer_text,
        css=out.css,
        image_front=has_image(front_html),
    )
    return RebuiltCard(grading_text(front_html) + src.hint, answer, grading_text(x_html), source)


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
