"""Phase 6 on a scratch collection: FSRS memory states -> the panel's
difficulty line and stable count -> the session's per-item overrides -> the
history line's per-card ``d``, ``s``, reps and threshold."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
from anki.cards import FSRSMemoryState
from anki.collection import Collection
from anki.consts import CARD_TYPE_REV, QUEUE_TYPE_REV
from anki_fixtures import add_note, deck

from recalldrill import history_store, sessions
from recalldrill.addon_config import DEFAULT_CONFIG, AddonConfig
from recalldrill.anki_io.cards import DEFAULT_ENABLED
from recalldrill.anki_io.panel import PanelData, options_for, read_panel
from recalldrill.anki_io.select import Scope
from recalldrill.controller import DrillController
from recalldrill.deck_settings import DeckSettings
from recalldrill.engine.session import select_trial
from recalldrill.launch import start
from recalldrill.storage import Storage

LONG = "one two three four five six seven"
"""7 words: drilled whole at T 8, chunked at a hard card's T 6."""


def _card(
    col: Collection,
    did: Any,
    front: str,
    back: str,
    *,
    d: float | None = None,
    s: float | None = None,
    ivl: int = 5,
    lapses: int = 0,
    review: bool = True,
) -> int:
    note = add_note(col, "Basic", did, {"Front": front, "Back": back})
    card = note.cards()[0]
    if review:
        card.type = CARD_TYPE_REV
        card.queue = QUEUE_TYPE_REV
        card.ivl = ivl
        card.due = col.sched.today + 3
        card.reps = 6
        card.lapses = lapses
        card.factor = 2500
        if d is not None and s is not None:
            card.memory_state = FSRSMemoryState(stability=s, difficulty=d)
        col.update_card(card)
    return card.id


@pytest.fixture
def setup(col: Collection, tmp_path: Path) -> tuple[Collection, Storage, int, dict[str, int]]:
    did = deck(col, "A&P")
    cids = {
        "hard": _card(col, did, "hard q", LONG, d=8.5, s=4.0),
        "easy": _card(col, did, "easy q", "easy answer", d=2.0, s=6.0),
        "mid": _card(col, did, "mid q", "mid answer", d=5.0, s=6.0),
        "stable": _card(col, did, "stable q", "stable answer", d=4.0, s=60.0, ivl=50),
        "lapsed": _card(col, did, "lapsed q", "lapsed answer", lapses=4),
        "new": _card(col, did, "new q", LONG, review=False),
    }
    return col, Storage(tmp_path / "user_files", "User 1"), int(did), cids


def _read(
    col: Collection, st: Storage, did: int, draft: DeckSettings, cfg: AddonConfig = DEFAULT_CONFIG
) -> PanelData:
    options = options_for(
        draft, enabled=DEFAULT_ENABLED, max_cards=None, extra_tag=None, order="deck_order"
    )
    return read_panel(col, st, Scope(deck_id=did), options, draft, did, cfg)


def _by_cid(p: PanelData) -> dict[int, Any]:
    return {src.cid: a for src, a in zip(p.build.sources, p.build.adjustments, strict=True)}


def test_panel_line_counts_and_stable(setup: Any) -> None:
    col, st, did, cids = setup
    p = _read(col, st, did, {})
    assert p.selection.eligible_counts["stable"] == 1 and p.stable_skipped == 1
    assert cids["stable"] not in {s.cid for s in p.build.sources}
    a = _by_cid(p)
    assert (a[cids["hard"]].encode_reps, a[cids["hard"]].min_words_to_chunk) == (4, 6)
    assert a[cids["easy"]].encode_reps == 2
    assert a[cids["mid"]].adjustment == 0
    assert (a[cids["lapsed"]].basis, a[cids["lapsed"]].encode_reps) == ("history", 4)
    assert (a[cids["new"]].basis, a[cids["new"]].overrides()) == ("new", {})
    assert p.difficulty is not None
    assert p.difficulty.text() == (
        "Difficulty-adjusted: 2 cards +1 rep, 1 card −1 rep, 1 card chunk earlier. "
        "New cards (1): no FSRS data, unchanged."
    )
    src = {s.cid: s for s in p.build.sources}
    assert (src[cids["hard"]].fsrs_d, src[cids["hard"]].fsrs_s) == pytest.approx((8.5, 4.0))
    assert (src[cids["new"]].fsrs_d, src[cids["new"]].fsrs_s) == (None, None)


def test_stable_class_switched_on_is_drilled(setup: Any) -> None:
    col, st, did, cids = setup
    options = options_for(
        {},
        enabled=DEFAULT_ENABLED | {"stable"},
        max_cards=None,
        extra_tag=None,
        order="deck_order",
    )
    p = read_panel(col, st, Scope(deck_id=did), options, {}, did, DEFAULT_CONFIG)
    assert p.stable_skipped == 0
    assert cids["stable"] in {s.cid for s in p.build.sources}


def test_stable_thresholds_come_from_the_config(setup: Any) -> None:
    col, st, did, _ = setup
    options = options_for(
        {},
        enabled=DEFAULT_ENABLED,
        max_cards=None,
        extra_tag=None,
        order="deck_order",
        skip_min_stability=100,
    )
    p = read_panel(col, st, Scope(deck_id=did), options, {}, did, DEFAULT_CONFIG)
    assert p.selection.eligible_counts["stable"] == 0


def test_toggle_off_and_deck_reps(setup: Any) -> None:
    col, st, did, cids = setup
    off = _read(col, st, did, {"difficultyAdjust": False})
    assert off.build.overrides() == [{}] * len(off.build.deck_items)
    assert off.difficulty is not None and off.difficulty.text().startswith(
        "Difficulty adjustment off"
    )
    cfg_off = _read(col, st, did, {}, AddonConfig(difficulty_adjust=False))
    assert all(o == {} for o in cfg_off.build.overrides())
    at_one = _by_cid(_read(col, st, did, {"encodeReps": 1}))
    assert at_one[cids["easy"]].encode_reps == 1  # a deck at 1 stays at 1
    assert at_one[cids["hard"]].encode_reps == 2


def _finish(ctrl: DrillController) -> None:
    for _ in range(2000):
        if ctrl.finished:
            return
        if ctrl.state["phase"] == "batch-done":
            ctrl.next_batch()
            continue
        if ctrl.view().buttons.continue_:
            ctrl.continue_()
            continue
        trial = select_trial(ctrl.state)
        assert trial is not None
        ctrl.submit(trial["target"])
        if ctrl.processing:
            ctrl.dwell_elapsed()
    raise AssertionError("didn't finish")


def test_start_applies_the_overrides_and_history_records_them(setup: Any) -> None:
    col, st, did, cids = setup
    p = _read(col, st, did, {"batchSize": 0})
    ctrl, store = start(
        st,
        scope=sessions.scope_json(deck_id=did),
        deck_name=p.label,
        deck_items=p.build.deck_items,
        sources=p.build.sources,
        settings_did=did,
        settings={"batchSize": 0},
        select_options=p.select_options,
        hints=False,
        cfg=DEFAULT_CONFIG,
        overrides=p.build.overrides(),
    )
    by_cid = {ctrl.sources[it["id"]].cid: it for it in ctrl.state["items"]}
    hard = by_cid[cids["hard"]]
    assert (hard.get("encodeRepsOverride"), hard.get("minWordsToChunkOverride")) == (4, 6)
    assert hard["chunks"] is not None  # 7 words chunk under the card's T 6
    assert by_cid[cids["new"]]["chunks"] is None  # the session's T 8 keeps 7 words whole
    assert "encodeRepsOverride" not in by_cid[cids["new"]]
    ctrl.start()
    saved = sessions.load(st, store.meta.key)
    assert saved is not None
    resumed = {
        sessions.saved_sources(saved)[it["id"]].cid: it for it in sessions.resume(saved)["items"]
    }
    assert resumed[cids["hard"]].get("encodeRepsOverride") == 4
    assert resumed[cids["easy"]].get("encodeRepsOverride") == 2

    _finish(ctrl)
    (line,) = [x for x in history_store.read_all(st, str(did)) if x["type"] == "session"]
    anki = {a["cid"]: a for a in line["anki"]}
    h = anki[cids["hard"]]
    assert (h["d"], h["s"]) == pytest.approx((8.5, 4.0))
    assert (h["encodeReps"], h["minWordsToChunk"], h["adjust"]) == (4, 6, 1)
    e = anki[cids["easy"]]
    assert (e["encodeReps"], e["minWordsToChunk"], e["adjust"]) == (2, 8, -1)
    n = anki[cids["new"]]
    assert (n["d"], n["s"], n["encodeReps"], n["minWordsToChunk"], n["adjust"]) == (
        None,
        None,
        3,
        8,
        0,
    )
