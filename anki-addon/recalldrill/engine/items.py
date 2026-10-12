"""Deck parsing, chunking, the combine ladder, remediation helpers, and DrillItem
construction/normalization. Port of ``src/utils/items.ts``.

The TS module is the reference; this is a copy, not an improvement. Parity is
checked against recorded TS outputs in ``tests/golden/items.json``.

============================  ================================
TS name                       Python name
============================  ================================
``parseDeck``                 ``parse_deck``
``listItems``                 ``list_items``
``MIN_WORDS_TO_CHUNK``        ``MIN_WORDS_TO_CHUNK``
``joinRuns``                  ``_join_runs``
``chunkText``                 ``chunk_text``
``renderFirstLetterCue``      ``render_first_letter_cue``
``buildCombineSequence``      ``build_combine_sequence``
``cycleRepsToMaster``         ``cycle_reps_to_master``
``requiredRepsForWindow``     ``required_reps_for_window``
``splitInHalf``               ``split_in_half``
``culpritHalf``               ``culprit_half``
``findAllCulpritChunks``      ``find_all_culprit_chunks``
``joinWindow``                ``join_window``
``ORDER_CUES``                ``ORDER_CUES``
``listOrderFromWording``      ``list_order_from_wording``
``withListOrder``             ``with_list_order``
``shuffle``                   ``shuffle``
``selectNextEncodeItem``      ``select_next_encode_item``
``slugify``                   ``slugify``
``shuffleWithinBatches``      ``_shuffle_within_batches``
``partitionIntoBatches``      ``partition_into_batches``
``buildItems``                ``build_items``
``buildItem``                 ``build_item``
``normalizeItem``             ``normalize_item``
``resolveBatchConfig``        ``resolve_batch_config``
``resolveSourceDeckEditable``  ``resolve_source_deck_editable``
============================  ================================

Add-on only (docs/DECISIONS.md, "Engine extensions"): :func:`reps_for` and the
optional per-item ``encodeRepsOverride`` / ``minWordsToChunkOverride``. With
neither set, every function here behaves exactly as its TS original.

Every ``Math.random()`` in the TS code is a :func:`.rand.random` call here, at
the same point and in the same order.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping, Sequence
from typing import Any, NotRequired, TypedDict, cast

from . import rand
from .grading import compute_word_diff, exact_match, grade, split_list_items
from .jscompat import WS_RE, js_round, js_split_ws, js_trim, truthy
from .types import (
    CombineSequenceItem,
    DeckItem,
    DrillItem,
    ItemOverrides,
    LadderMode,
    SessionConfig,
)


def parse_deck(text: str) -> list[DeckItem]:
    """Parses ``front<TAB>back[<TAB>extra]``, ``front::back[::extra]`` and
    ``front - back`` lines."""
    out: list[DeckItem] = []

    for raw_line in text.split("\n"):
        line = js_trim(raw_line)
        if not line or line.startswith("//") or line.startswith("#"):
            continue

        front = ""
        back = ""
        extra = ""

        if "\t" in line:
            # Optional third segment ("Extra"): front[TAB]back[TAB]extra.
            parts = line.split("\t")
            front = js_trim(parts[0])
            back = js_trim(parts[1] if len(parts) > 1 else "")
            extra = js_trim("\t".join(parts[2:]))
        elif "::" in line:
            # Optional third segment: front::back::extra.
            parts = line.split("::")
            front = js_trim(parts[0])
            back = js_trim(parts[1] if len(parts) > 1 else "")
            extra = js_trim("::".join(parts[2:]))
        elif " - " in line and "->" not in line:
            # Fallback for hyphen separator
            parts = line.split(" - ")
            front = js_trim(parts[0])
            back = js_trim(" - ".join(parts[1:]))

        if front and back:
            if extra:
                out.append({"front": front, "back": back, "extra": extra})
            else:
                out.append({"front": front, "back": back})

    return out


def list_items(text: str) -> list[str] | None:
    """The items of a comma- or semicolon-separated list, or None (2026-10-12).

    Splits on ``,`` and ``;`` outside ``()`` and ``[]``, trims each item, drops a
    leading "and " or "or " and empty items, and keeps each item's own wording.
    A list has 3 or more items: "radius and ulna" is one item."""
    items = split_list_items(text)
    return items if len(items) >= 3 else None


# Answers at or under this many words skip the chunk/combine ladder and use
# stage 'full' directly.
MIN_WORDS_TO_CHUNK = 8


def _join_runs(runs: list[list[str]], joiner: str) -> list[str] | None:
    """Joins runs of units into chunks; a lonely 1-unit trailing run merges into
    the one before. Fewer than 2 chunks: None."""
    if len(runs) > 1 and len(runs[-1]) <= 1:
        last = runs.pop()
        runs[-1] = [*runs[-1], *last]
    return [joiner.join(r) for r in runs] if len(runs) > 1 else None


def chunk_text(
    text: str, chunk_percent: float = 35, min_words_to_chunk: int = MIN_WORDS_TO_CHUNK
) -> list[str] | None:
    """Splits an answer into chunks, or None.

    A list answer (:func:`list_items`) with 4+ items, or 3 items and more than
    ``min_words_to_chunk`` words, is cut at item boundaries, ``max(2,
    js_round(items x pct))`` items per chunk, joined with ", ". Any other answer
    over the threshold is cut every ``js_round(words x pct)`` words, a cut inside
    parentheses moving to just after the word that closes them."""
    words = [w for w in js_split_ws(text) if len(w) > 0]
    pct = max(15, min(100, chunk_percent))

    items = list_items(text)
    if items is not None and (len(items) >= 4 or len(words) > min_words_to_chunk):
        # 100% means full card at once (no chunking)
        if pct >= 100:
            return None
        items_per_chunk = max(2, js_round(len(items) * (pct / 100)))
        if items_per_chunk >= len(items):
            return None
        item_runs = [items[i : i + items_per_chunk] for i in range(0, len(items), items_per_chunk)]
        return _join_runs(item_runs, ", ")

    if len(words) <= min_words_to_chunk:
        return None

    # 100% means full card at once (no chunking)
    if pct >= 100:
        return None

    target_chunk_size = max(2, js_round(len(words) * (pct / 100)))

    if target_chunk_size >= len(words):
        return None

    # Never cut inside parentheses: the cut moves to just after the closing word.
    depth_after: list[int] = []
    depth = 0
    for w in words:
        for ch in w:
            if ch == "(":
                depth += 1
            elif ch == ")" and depth > 0:
                depth -= 1
        depth_after.append(depth)
    runs: list[list[str]] = []
    start = 0
    while start < len(words):
        end = min(start + target_chunk_size, len(words))
        while end < len(words) and depth_after[end - 1] > 0:
            end += 1
        runs.append(words[start:end])
        start = end
    return _join_runs(runs, " ")


_ASCII_ALNUM = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789")


def render_first_letter_cue(target: str) -> str:
    """Attempt-0 cue: the first alphanumeric of each alphanumeric run, the rest of
    the run as ``_``, and every other character in place.

    "The heart pumps blood." -> "T__ h____ p____ b_____.", "-itis" -> "-i___",
    "cardi/o" -> "c____/o". Do NOT simplify to "reveal index 0 of the word".

    TS walks UTF-16 code units and Python walks code points. Both leave every
    non-ASCII unit or character untouched and end the run there, so the output
    is the same.
    """

    def render_word(word: str) -> str:
        in_run = False
        out: list[str] = []
        for ch in word:
            if ch not in _ASCII_ALNUM:
                in_run = False
                out.append(ch)
                continue
            reveal = not in_run
            in_run = True
            out.append(ch if reveal else "_")
        return "".join(out)

    return " ".join(render_word(word) for word in target.split(" "))


def build_combine_sequence(n: int, mode: LadderMode = "cumulative") -> list[CombineSequenceItem]:
    """Combine windows for ``n`` chunks: growing prefixes (cumulative) or every
    increasing-size window ending at each position (exhaustive)."""
    seq: list[CombineSequenceItem] = []
    if mode == "exhaustive":
        for e in range(2, n + 1):
            for s in range(2, e + 1):
                seq.append({"start": e - s + 1, "end": e})
        return seq

    for e in range(2, n + 1):
        seq.append({"start": 1, "end": e})
    return seq


def reps_for(item: Mapping[str, Any], config: SessionConfig | int) -> int:
    """Add-on only: the consecutive blind successes this card's ``encodeReps``
    steps need. Its ``encodeRepsOverride`` when set, else the session's
    (``config["encodeReps"]``, or ``config`` itself when it is the number)."""
    session_reps = config if isinstance(config, int) else config["encodeReps"]
    override = item.get("encodeRepsOverride")
    return session_reps if override is None else override


def min_words_for(item: Mapping[str, Any], session_min_words: int) -> int:
    """Add-on only: this card's chunking threshold. Its ``minWordsToChunkOverride``
    when set, else the session's."""
    override = item.get("minWordsToChunkOverride")
    return session_min_words if override is None else override


def cycle_reps_to_master(item: Mapping[str, Any]) -> int:
    """Correct cycle answers in a row that master the card (2026-10-12): 1 for a
    clean card (no miss and no reveal on it this session; near misses don't
    count, and an overridden miss was never recorded), else 2. A restarted card
    has fresh counters, so it is clean again."""
    clean = item.get("misses", 0) == 0 and item.get("reveals", 0) == 0
    return 1 if clean else 2


def required_reps_for_window(seq_item: CombineSequenceItem, n: int, encode_reps: int) -> int:
    """Consecutive blind successes a cumulative combine window needs."""
    return encode_reps if seq_item["end"] >= n else 1


def split_in_half(text: str) -> tuple[str, str]:
    words = text.split(" ")
    mid = math.ceil(len(words) / 2)
    return " ".join(words[:mid]), " ".join(words[mid:])


def culprit_half(typed: str, left: str, right: str, strict: bool = False) -> str:
    typed_trimmed = js_trim(typed)
    typed_words = js_split_ws(typed_trimmed) if typed_trimmed else []
    left_word_count = len(left.split(" "))
    left_typed = " ".join(typed_words[:left_word_count])
    if not exact_match(left_typed, left, strict):
        return left
    return right


def find_all_culprit_chunks(
    typed: str,
    chunks: Sequence[str],
    start_idx: int,
    end_idx: int,
    strict: bool = False,
    any_order: bool = False,
    stem_tolerance: bool | None = None,
) -> list[int]:
    """Chunk indices in ``start_idx..end_idx`` with an unmatched word in the LCS diff.

    Falls back to ``[end_idx]`` when every word matched. An any-order card (TS
    ``anyOrder: {stemTolerance}``) joins the window with ", " and uses grade()'s
    any-order diff, with ``stem_tolerance``.
    """
    combined_target = join_window(chunks, start_idx, end_idx + 1, any_order)
    if any_order:
        diff = grade(
            typed,
            combined_target,
            strict_punctuation=strict,
            stem_tolerance=stem_tolerance,
            any_order=True,
        )["diff"]
    else:
        diff = compute_word_diff(typed, combined_target, strict)

    culprits: list[int] = []
    word_cursor = 0
    for idx in range(start_idx, end_idx + 1):
        chunk_word_count = len(chunks[idx].split(" "))
        chunk_diff = diff[word_cursor : word_cursor + chunk_word_count]
        if any(not d["matched"] for d in chunk_diff):
            culprits.append(idx)
        word_cursor += chunk_word_count

    if not culprits:
        culprits.append(end_idx)

    return culprits


def join_window(chunks: Sequence[str], start: int, end: int, any_order: bool = False) -> str:
    """``chunks[start:end]`` as one combine window: ", " for an any-order card
    (its chunks are runs of list items), else a space."""
    return (", " if any_order else " ").join(chunks[start:end])


ORDER_CUES: tuple[str, ...] = (
    "in order",
    "the order",
    "order is",
    "sequence",
    "step",
    "steps",
    "chain",
    "cycle",
    "then",
    "proximal to distal",
    "distal to proximal",
    "superior to inferior",
    "inferior to superior",
    "superficial to deep",
    "deep to superficial",
    "largest to smallest",
    "smallest to largest",
    "anterior to posterior",
    "posterior to anterior",
    "medial to lateral",
    "lateral to medial",
    "\u2192",
)
"""Wording that makes a list ordered (the anki-cards skill's sequence cues, plus
the reverse directions and the anterior/posterior and medial/lateral pairs)."""

_CLOZE_BLANK_RE = re.compile("\\[(?:\\.\\.\\.|\u2026)\\]")
_UNDERSCORES_RE = re.compile("_{2,}")
_CUE_RES = {
    cue: re.compile("(?:^|[^a-z0-9])" + re.escape(cue) + "(?:\\Z|[^a-z0-9])")
    for cue in ORDER_CUES
    if cue != "\u2192"
}


def list_order_from_wording(front: str) -> str:
    """"ordered" when the front (cloze blank ``[...]`` / ``___`` removed) has one of
    :data:`ORDER_CUES`, else "any" (2026-10-12)."""
    text = _CLOZE_BLANK_RE.sub(" ", front)
    text = _UNDERSCORES_RE.sub(" ", text)
    text = WS_RE.sub(" ", text.lower())
    for cue in ORDER_CUES:
        if cue == "\u2192":
            if cue in text:
                return "ordered"
            continue
        if _CUE_RES[cue].search(text):
            return "ordered"
    return "any"


def with_list_order(card: DeckItem) -> DeckItem:
    """``card`` with ``anyOrder`` set for an unordered list answer, else unchanged."""
    if list_items(card["back"]) is None or list_order_from_wording(card["front"]) != "any":
        return card
    return {**card, "anyOrder": True}


def shuffle[T](arr: Sequence[T]) -> list[T]:
    """Fisher-Yates over a copy, drawing ``rand.random()`` exactly like the TS loop."""
    a = list(arr)
    for i in range(len(a) - 1, 0, -1):
        j = math.floor(rand.random() * (i + 1))
        a[i], a[j] = a[j], a[i]
    return a


def select_next_encode_item(batch: Sequence[DrillItem], last_item_id: int) -> DrillItem | None:
    """Round-robins over ``batch`` from after ``last_item_id`` to the next item that
    is neither 'ready' nor 'mastered'. Returns the batch's own dict, or None."""

    def needs_encoding(i: DrillItem) -> bool:
        return i["status"] != "ready" and i["status"] != "mastered"

    pending = [i for i in batch if needs_encoding(i)]
    if not pending:
        return None

    last_idx = next((idx for idx, i in enumerate(batch) if i["id"] == last_item_id), -1)
    if last_idx == -1:
        return pending[0]

    for step in range(1, len(batch) + 1):
        candidate = batch[(last_idx + step) % len(batch)]
        if needs_encoding(candidate):
            return candidate
    return None  # unreachable: pending is non-empty, so the loop finds one


_SLUG_NON_ALNUM_RE = re.compile("[^a-z0-9]+")
_SLUG_EDGE_DASHES_RE = re.compile("^-+|-+\\Z")


def slugify(name: str) -> str:
    s = js_trim(name).lower()
    s = _SLUG_NON_ALNUM_RE.sub("-", s)
    s = _SLUG_EDGE_DASHES_RE.sub("", s)
    return s or "deck"


def _batch_step(item_count: int, batch_size: int | None) -> int:
    """TS ``batchSize && batchSize > 0 ? batchSize : items.length``."""
    return batch_size if batch_size is not None and batch_size > 0 else item_count


def _shuffle_within_batches[T](items: Sequence[T], batch_size: int | None = None) -> list[T]:
    """A copy with each deck-order batch shuffled; batch membership is unchanged."""
    size = _batch_step(len(items), batch_size)
    result: list[T] = []
    if size == 0:  # no items: the TS loop runs zero times (range() can't take a 0 step)
        return result
    for i in range(0, len(items), size):
        result.extend(shuffle(items[i : i + size]))
    return result


def partition_into_batches[T](items: Sequence[T], batch_size: int | None = None) -> list[list[T]]:
    """Batch membership only, in the current order. Size <= 0, None or >= len is one batch."""
    size = _batch_step(len(items), batch_size)
    if not items:
        return []
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def build_items(
    parsed: Sequence[DeckItem],
    chunk_percent: float = 35,
    ladder_mode: LadderMode = "cumulative",
    batch_size: int | None = None,
    min_words_to_chunk: int = MIN_WORDS_TO_CHUNK,
    shuffle_within_batch: bool = True,
    overrides: Sequence[ItemOverrides | None] | None = None,
) -> list[DrillItem]:
    """Fresh items for a deck. ``shuffle_within_batch=False`` keeps deck order (what
    the app and the add-on use); the default True matches the TS harness and tests.

    ``overrides`` (add-on only): per card, parallel to ``parsed``; None (or a
    None entry) is the TS call."""
    items = [
        build_item(
            p,
            i,
            chunk_percent,
            ladder_mode,
            min_words_to_chunk,
            overrides[i] if overrides is not None and i < len(overrides) else None,
        )
        for i, p in enumerate(parsed)
    ]
    return _shuffle_within_batches(items, batch_size) if shuffle_within_batch else items


def build_item(
    p: DeckItem,
    item_id: int,
    chunk_percent: float,
    ladder_mode: LadderMode,
    min_words_to_chunk: int,
    overrides: ItemOverrides | None = None,
) -> DrillItem:
    """One fresh item (status 'new', no progress) for a card.

    ``overrides`` (add-on only) is stored on the item; its
    ``minWordsToChunkOverride`` wins over ``min_words_to_chunk``."""
    o: ItemOverrides = overrides if overrides is not None else {}
    chunks = chunk_text(p["back"], chunk_percent, min_words_for(o, min_words_to_chunk))
    item: DrillItem = {
        "id": item_id,
        "front": p["front"],
        "back": p["back"],
        "status": "new",
        "encodeStreak": 0,
        "cycleStreak": 0,
        "chunks": chunks,
        "chunkIndex": 0,
        "chunkStreak": 0,
        "combineSeq": build_combine_sequence(len(chunks), ladder_mode) if chunks else None,
        "combineSeqIdx": 0,
        "combineStreak": 0,
        "combineMissCount": 0,
        "remediateStack": [],
        "remediateQueue": [],
        "remediateReturnSeqIdx": 0,
        "stage": "chunks" if chunks else "full",
    }
    # TS `extra: p.extra`: absent stays absent.
    if "extra" in p:
        item["extra"] = p["extra"]
    if "anyOrder" in p:
        item["anyOrder"] = p["anyOrder"]
    if "encodeRepsOverride" in o:
        item["encodeRepsOverride"] = o["encodeRepsOverride"]
    if "minWordsToChunkOverride" in o:
        item["minWordsToChunkOverride"] = o["minWordsToChunkOverride"]
    return item


def item_overrides(item: Mapping[str, Any]) -> ItemOverrides:
    """Add-on only: the card's overrides, to carry onto a rebuilt item."""
    out: ItemOverrides = {}
    if "encodeRepsOverride" in item:
        out["encodeRepsOverride"] = item["encodeRepsOverride"]
    if "minWordsToChunkOverride" in item:
        out["minWordsToChunkOverride"] = item["minWordsToChunkOverride"]
    return out


def _nullish(value: Any, default: Any) -> Any:
    """TS ``value ?? default`` (JSON null and an absent key are both None here)."""
    return default if value is None else value


# Fields normalizeItem threads through unchanged (`field: it.field`). When the
# saved item doesn't have one, TS's undefined drops it from the JSON, so the
# Python result leaves the key out.
_PASS_THROUGH_FIELDS = (
    "id",
    "front",
    "back",
    "extra",
    "anyOrder",
    "finalDone",
    "finalMisses",
    "attempts",
    "misses",
    "reveals",
    "nearMisses",
    "hardSpans",
    # Add-on only (engine extensions): a resumed card keeps its overrides.
    "encodeRepsOverride",
    "minWordsToChunkOverride",
)


def normalize_item(it: Mapping[str, Any], ladder_mode: LadderMode = "cumulative") -> DrillItem:
    """Fills defaults on a saved item and migrates legacy shapes."""
    # Saved JSON: any field may be missing (None here) or of any JSON type.
    chunks: Any = it.get("chunks")
    combine_seq: Any = it.get("combineSeq")
    remediate_stack: Any = it.get("remediateStack")
    remediate_queue: Any = it.get("remediateQueue")
    status: Any = it.get("status")
    stage: Any = it.get("stage")

    fields: dict[str, Any] = {key: it[key] for key in _PASS_THROUGH_FIELDS if key in it}
    fields.update(
        {
            "status": status if truthy(status) else "new",
            "encodeStreak": _nullish(it.get("encodeStreak"), 0),
            "cycleStreak": _nullish(it.get("cycleStreak"), 0),
            "chunks": chunks if truthy(chunks) else None,
            "chunkIndex": _nullish(it.get("chunkIndex"), 0),
            "chunkStreak": _nullish(it.get("chunkStreak"), 0),
            "combineSeq": combine_seq
            if truthy(combine_seq)
            else (build_combine_sequence(len(chunks), ladder_mode) if truthy(chunks) else None),
            "combineSeqIdx": _nullish(it.get("combineSeqIdx"), 0),
            "combineStreak": _nullish(it.get("combineStreak"), 0),
            "combineMissCount": _nullish(it.get("combineMissCount"), 0),
            "remediateStack": remediate_stack if truthy(remediate_stack) else [],
            "remediateQueue": remediate_queue if truthy(remediate_queue) else [],
            "remediateReturnSeqIdx": _nullish(it.get("remediateReturnSeqIdx"), 0),
            "stage": stage if truthy(stage) else ("chunks" if truthy(chunks) else "full"),
        }
    )

    if (
        fields["status"] == "encoding"
        and fields["stage"] == "remediate"
        and not len(fields["remediateStack"])
    ):
        fields["stage"] = "chunks" if truthy(fields["chunks"]) else "full"
        fields["chunkIndex"] = 0
        fields["chunkStreak"] = 0

    # C8a: chunkStreak's valid range for stage 'chunks' is {0, 1}. Clamp a
    # pre-C8a save down to 1.
    if fields["stage"] == "chunks" and fields["chunkStreak"] > 1:
        fields["chunkStreak"] = 1

    return cast(DrillItem, fields)


class BatchConfig(TypedDict):
    batchIndex: int
    batchSize: int


class _SavedBatchFields(TypedDict):
    batchIndex: NotRequired[int]
    batchSize: NotRequired[int]


class _SavedSourceFields(TypedDict):
    sourceDeckEditable: NotRequired[bool]


def resolve_batch_config(saved: _SavedBatchFields, items: Sequence[DrillItem]) -> BatchConfig:
    """Migration for a save from before batching: batch 0, one whole-deck batch."""
    return {
        "batchIndex": _nullish(saved.get("batchIndex"), 0),
        "batchSize": _nullish(saved.get("batchSize"), len(items)),
    }


def resolve_source_deck_editable(saved: _SavedSourceFields) -> bool:
    """A save with no recorded source is session-only."""
    return _nullish(saved.get("sourceDeckEditable"), False)
