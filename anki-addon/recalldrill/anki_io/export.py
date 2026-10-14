"""Write the light outcomes export (v0.3). Read only on the collection.

``outcomes.py`` (pure) has the rules and the CSV. Here: read the history and the
revlog of the drilled and holdout cards (the tuning report's rows, without the
baseline), each card's memory state through Anki's API, and its exam date; then
write ``exports/outcomes.csv`` in the profile folder atomically.

Facts read from Anki 26.08.1 (docs/DECISIONS.md, "v0.3"; ``tests/anki_io/test_export.py``):

- ``card.memory_state`` is ``None`` or has ``.stability`` and ``.difficulty``: the
  state after the card's last review. New cards have none.
- ``card.decay`` is the decay stored on the card (``None`` until a review under
  FSRS-6 stores it; Anki rounds it, e.g. 0.154 for the preset's 0.1542).
- ``col.compute_memory_state(card_id).decay`` is the card's preset's decay (always
  set; 0.1542 without parameters).
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date, tzinfo
from pathlib import Path

# anki.collection must load before anki.cards (circular import).
import anki.collection  # noqa: F401  # pyright: ignore[reportUnusedImport]
from anki.cards import CardId
from anki.collection import Collection
from anki.consts import CARD_TYPE_NEW
from anki.decks import DeckId
from anki.errors import NotFoundError

from ..history_store import read_every_log
from ..outcomes import MemoryFacts, OutcomeRecord, outcomes_csv, records
from ..storage import OUTCOMES, Storage
from ..tuning import card_rows, collect_cids
from .exam import exam_for_deck
from .revlog import card_decks, read_revlog

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class ExportResult:
    path: Path
    rows: int

    @property
    def folder(self) -> Path:
        return self.path.parent


def _preset_decay(
    col: Collection, cid: int, home: int, cache: dict[int, float | None]
) -> float | None:
    """The card's preset's decay (one lookup per preset)."""
    preset = int(col.decks.config_dict_for_deck_id(DeckId(home))["id"])
    if preset not in cache:
        try:
            cache[preset] = float(col.compute_memory_state(CardId(cid)).decay or 0) or None
        except Exception:
            log.warning("Recall Drill: no preset decay for card %s", cid, exc_info=True)
            cache[preset] = None
    return cache[preset]


def read_records(
    col: Collection, storage: Storage, now_ms: float | None = None, tz: tzinfo | None = None
) -> list[OutcomeRecord]:
    """The drilled and holdout cards' outcomes, cost and exam-day recall."""
    lines = read_every_log(storage)
    drilled, holdout = collect_cids(lines)
    cids = drilled | holdout
    rollover = col.get_preferences().scheduling.rollover
    revlog = read_revlog(col, cids)
    rows = card_rows(lines, revlog, card_decks(col, cids), rollover, tz)
    memory: dict[int, MemoryFacts] = {}
    exams: dict[int, date | None] = {}
    exam_by_deck: dict[int, date | None] = {}
    decay_by_preset: dict[int, float | None] = {}
    for cid in sorted(cids):
        try:
            card = col.get_card(CardId(cid))
        except NotFoundError:
            continue
        home = int(card.odid or card.did)
        if home not in exam_by_deck:
            found = exam_for_deck(col, storage, home)
            exam_by_deck[home] = found.day if found is not None else None
        exams[cid] = exam_by_deck[home]
        state = card.memory_state
        stability = float(state.stability) if state is not None else None
        # The preset's decay is only looked up when it can be used.
        needs_preset = stability is not None and card.decay is None and exams[cid] is not None
        memory[cid] = MemoryFacts(
            is_new=card.type == CARD_TYPE_NEW,
            stability=stability,
            decay=float(card.decay) if card.decay is not None else None,
            preset_decay=_preset_decay(col, cid, home, decay_by_preset) if needs_preset else None,
        )
    now = time.time() * 1000 if now_ms is None else now_ms
    return records(rows, revlog, memory, exams, rollover, now, tz)


def export_outcomes(
    col: Collection, storage: Storage, now_ms: float | None = None, tz: tzinfo | None = None
) -> ExportResult:
    """Reads and writes ``exports/outcomes.csv`` (atomic: temp file, then rename)."""
    recs = read_records(col, storage, now_ms, tz)
    path = storage.write_text(OUTCOMES, outcomes_csv(recs, tz))
    return ExportResult(path, len(recs))
