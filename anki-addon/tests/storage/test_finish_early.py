"""sessions.finish_early: the cut of a stopped session down to its mastered cards."""

from __future__ import annotations

import copy
from pathlib import Path
from typing import Any

import pytest
from controller_support import Clock, source
from finish_early_support import (
    KEY,
    run_until,
    start,
    stopped_mid_batch,
    storage,
)

from recalldrill import sessions
from recalldrill.controller import ControllerSettings
from recalldrill.engine.session import SESSION_COMPLETE_ID
from recalldrill.sessions import (
    finish_early,
    finish_early_counts,
    open_saved,
    saved_sources,
)
from recalldrill.storage import Storage

NOW = 1_790_100_000_000


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return storage(tmp_path)


@pytest.fixture
def saved(st: Storage) -> dict[str, Any]:
    return stopped_mid_batch(st)[2]


def _cids(saved: dict[str, Any]) -> list[int]:
    return [s.cid for s in saved_sources(saved)]


# --- the counts ----------------------------------------------------------------


def test_counts_of_a_save_stopped_mid_batch(saved: dict[str, Any]) -> None:
    c = finish_early_counts(saved, (), ())
    # 0, 1 (batch 1) and 2 mastered; 3 part-way; 4 and 5 untouched.
    assert (c.total, c.kept, c.returned) == (6, 3, 3)
    assert (c.part_way, c.changed, c.missing) == (1, 0, 0)


def test_counts_with_changed_and_missing_cards(saved: dict[str, Any]) -> None:
    c = finish_early_counts(saved, missing=[1001], changed=[1002, 1004])
    # 1001 gone; 1002 (mastered) and 1004 (untouched) changed: back to the pool.
    assert (c.total, c.kept, c.returned, c.changed, c.missing) == (6, 1, 4, 2, 1)
    # 1003 was part-way, and so was 1002 (mastered, then sent back: its progress is dropped).
    # 1004 never started.
    assert c.part_way == 2


# --- the cut -------------------------------------------------------------------


def test_the_kept_cards_are_renumbered_and_sources_follow(saved: dict[str, Any]) -> None:
    out = finish_early(saved, missing=[1001], changed=[1002], now_ms=NOW)
    # Kept: 1000 only (1001 missing, 1002 changed, the rest unfinished).
    assert [i["id"] for i in out["items"]] == [0]
    assert _cids(out) == [1000]
    assert out["items"][0]["front"] == "front0"


def test_ids_index_sources_and_check_resume_sees_only_kept_cards(saved: dict[str, Any]) -> None:
    out = finish_early(saved, (), (), NOW)
    kept = [i for i in saved["items"] if i["status"] == "mastered"]
    assert [i["id"] for i in out["items"]] == list(range(len(kept)))
    sources = saved_sources(out)
    assert len(sources) == len(kept)
    # check_resume walks sources: they are the kept cards, in the original order.
    assert [s.cid for s in sources] == [1000 + i["id"] for i in kept]
    for i in out["items"]:
        assert sources[i["id"]].cid == 1000 + kept[i["id"]]["id"]


def test_active_time_follows_the_kept_cards(saved: dict[str, Any]) -> None:
    saved = copy.deepcopy(saved)
    saved["addon"]["activeMsByItem"] = {"0": 10, "2": 30, "3": 40, "5": 60}
    saved["addon"]["activeMs"] = 140
    out = finish_early(saved, (), (), NOW)
    assert out["addon"]["activeMsByItem"] == {"0": 10, "2": 30}
    assert out["addon"]["activeMs"] == 140
    by_cid = {r["cid"]: r["activeMs"] for r in out["addon"]["cut"]["returned"]}
    assert by_cid == {1003: 40, 1004: 0, 1005: 60}


def test_item_state_and_the_sittings_totals_are_unchanged(saved: dict[str, Any]) -> None:
    saved = copy.deepcopy(saved)
    saved["items"][0]["hardSpans"] = ["cardi"]
    saved["items"][2]["encodeRepsOverride"] = 3
    saved["items"][2]["misses"] = 4
    out = finish_early(saved, (), (), NOW)
    for new in out["items"]:
        old = saved["items"][[1000 + i["id"] for i in saved["items"]].index(_cids(out)[new["id"]])]
        assert {**new, "id": old["id"]} == old
    assert out["items"][0]["hardSpans"] == ["cardi"]
    assert out["items"][2]["encodeRepsOverride"] == 3
    for key in ("stats", "batchStartStats", "deckName", "encodeReps", "batchSize", "timestamp"):
        assert out[key] == saved[key]
    for key in (
        "sessionId",
        "startedAt",
        "scope",
        "selectOptions",
        "deckSettings",
        "hints",
        "holdout",
        "collisions",
        "activeMs",
    ):
        assert out["addon"][key] == saved["addon"][key]
    assert saved["items"][0]["id"] == 0 and len(saved["items"]) == 6  # the input is untouched


def test_engine_position_and_the_dropped_final_check_marker(saved: dict[str, Any]) -> None:
    saved = copy.deepcopy(saved)
    saved["finalCheckStartAttempts"] = 99
    out = finish_early(saved, (), (), NOW)
    assert out["phase"] == "cycle"
    assert out["queue"] == []
    assert out["currentId"] == SESSION_COMPLETE_ID
    assert out["batchIndex"] == 1  # 3 kept cards in batches of 2: the last is batch 1
    assert "finalCheckStartAttempts" not in out


def test_batch_index_follows_the_kept_count(saved: dict[str, Any]) -> None:
    # Cards 0 and 1 are in batch 0: with only them kept, the last batch is 0.
    out = finish_early(saved, missing=[], changed=[1002], now_ms=NOW)
    assert [i["id"] for i in out["items"]] == [0, 1]
    assert out["batchIndex"] == 0


def test_returned_cards_are_recorded_exactly(saved: dict[str, Any]) -> None:
    out = finish_early(saved, missing=[1001], changed=[1002, 1004], now_ms=NOW)
    cut = out["addon"]["cut"]
    assert cut["at"] == "2026-09-22T18:00:00.000Z"
    assert (cut["total"], cut["missing"]) == (6, [1001])
    by_cid = {r["cid"]: r for r in cut["returned"]}
    assert list(by_cid) == [1002, 1003, 1004, 1005]  # in session order
    assert by_cid[1002]["reason"] == "changed"
    assert by_cid[1002]["status"] == "mastered"
    assert by_cid[1003]["reason"] == "unfinished"
    assert by_cid[1003]["status"] in ("encoding", "ready")
    assert by_cid[1004]["reason"] == "changed"  # changed wins over unfinished
    assert by_cid[1004]["status"] == "new"
    assert by_cid[1005]["reason"] == "unfinished"
    src = source(3, nid=2001, ord=1)
    old = saved["items"][3]
    assert by_cid[1003] == {
        "cid": 1003,
        "nid": src.nid,
        "ord": src.ord,
        "did": src.did,
        "card_class": src.card_class,
        "status": old["status"],
        "attempts": old["attempts"],
        "misses": old["misses"],
        "reveals": old["reveals"],
        "nearMisses": old["nearMisses"],
        "activeMs": saved["addon"]["activeMsByItem"].get("3", 0),
        "reason": "unfinished",
    }
    assert old["attempts"] > 0


def test_the_cut_save_opens_in_the_final_check(st: Storage, saved: dict[str, Any]) -> None:
    out = finish_early(saved, (), (), NOW)
    ctrl, _ = open_saved(st, KEY, out, ControllerSettings(deck_name="x"), Clock())
    state = ctrl.state
    assert state["phase"] == "final"
    assert sorted([state["currentId"], *state["queue"]]) == [0, 1, 2]
    assert state.get("finalCheckStartAttempts") == state["stats"]["attempts"]
    assert state["stats"] == saved["stats"]


# --- refusals ------------------------------------------------------------------


def test_refuses_when_no_card_would_be_kept(st: Storage) -> None:
    ctrl, _ = start(st)
    ctrl.save_and_stop()
    fresh = sessions.load(st, KEY)
    assert fresh is not None
    with pytest.raises(ValueError, match="mastered"):
        finish_early(fresh, (), (), NOW)


def test_refuses_in_the_final_check(st: Storage) -> None:
    ctrl, _ = start(st)
    run_until(ctrl, lambda c: c.state["phase"] == "final")
    ctrl.save_and_stop()
    final = sessions.load(st, KEY)
    assert final is not None
    with pytest.raises(ValueError, match="Final check"):
        finish_early(final, (), (), NOW)


def test_refuses_when_nothing_would_be_returned(saved: dict[str, Any]) -> None:
    every = copy.deepcopy(saved)
    for item in every["items"]:
        item["status"] = "mastered"
    with pytest.raises(ValueError, match="nothing to give back"):
        finish_early(every, (), (), NOW)
    # ...and a missing card alone doesn't make a cut either.
    with pytest.raises(ValueError, match="nothing to give back"):
        finish_early(every, [1005], (), NOW)


def test_refuses_a_drill_again_save(saved: dict[str, Any]) -> None:
    again = copy.deepcopy(saved)
    again["addon"]["drillAgainOf"] = KEY
    with pytest.raises(ValueError, match="drill-again"):
        finish_early(again, (), (), NOW)


def test_refuses_a_save_waiting_for_its_handoff(saved: dict[str, Any]) -> None:
    pending = copy.deepcopy(saved)
    pending["addon"]["handoffPending"] = True
    with pytest.raises(ValueError, match="handoff"):
        finish_early(pending, (), (), NOW)


# --- the cut survives the store ------------------------------------------------


def test_cut_survives_persist_resume_and_persist(st: Storage, saved: dict[str, Any]) -> None:
    out = finish_early(saved, (), (), NOW)
    st.write_json(sessions.save_name(KEY), out)
    first = sessions.load(st, KEY)
    assert first is not None
    ctrl, store = open_saved(st, KEY, first, ControllerSettings(deck_name="Med Term"), Clock())
    assert store.meta.cut == out["addon"]["cut"]
    ctrl.start()  # the first save of a resumed session
    again = sessions.load(st, KEY)
    assert again is not None
    assert again["addon"]["cut"] == out["addon"]["cut"]
    ctrl2, _ = open_saved(st, KEY, again, ControllerSettings(deck_name="Med Term"), Clock())
    ctrl2.save_and_stop()
    last = sessions.load(st, KEY)
    assert last is not None
    assert last["addon"]["cut"] == out["addon"]["cut"]


def test_an_uncut_save_has_no_cut_block(saved: dict[str, Any]) -> None:
    assert "cut" not in saved["addon"]


# --- the button and the confirmation text ---------------------------------------------


def _counts(**kw: int) -> sessions.FinishEarlyCounts:
    base = {"total": 10, "kept": 4, "returned": 6, "part_way": 0, "changed": 0, "missing": 0}
    return sessions.FinishEarlyCounts(**{**base, **kw})


@pytest.mark.parametrize(
    ("screen", "show"),
    [
        ("batch_done", True),
        ("stopped", True),
        ("panel", True),
        ("trial", False),  # a card is on screen: end the session first
        ("complete", False),
    ],
)
def test_the_button_shows_only_on_the_offered_screens(screen: Any, show: bool) -> None:
    assert sessions.finish_early_button(_counts(), screen).show is show


@pytest.mark.parametrize(
    "counts",
    [
        _counts(kept=0, returned=10),  # nothing mastered
        _counts(kept=10, returned=0),  # all kept
        _counts(kept=9, returned=0, missing=1),  # a missing card alone isn't a cut
    ],
)
def test_the_button_is_hidden_when_there_is_nothing_to_cut(counts: Any) -> None:
    for screen in ("batch_done", "stopped", "panel"):
        assert not sessions.finish_early_button(counts, screen).show


def test_the_button_is_hidden_in_drill_again_and_in_the_final_check() -> None:
    assert not sessions.finish_early_button(_counts(), "stopped", drill_again=True).show
    assert not sessions.finish_early_button(_counts(), "stopped", final_check=True).show
    assert sessions.finish_early_button(_counts(), "stopped").show


def test_the_button_labels() -> None:
    assert sessions.finish_early_button(_counts(), "stopped").label == "Finish with 4 cards"
    assert sessions.finish_early_button(_counts(kept=1), "batch_done").label == (
        "Finish with 1 card"
    )
    assert sessions.finish_early_button(_counts(), "panel").label == (
        "Finish with 4 mastered cards"
    )
    assert sessions.finish_early_button(_counts(kept=1), "panel").label == (
        "Finish with 1 mastered card"
    )


def test_the_confirmation_text() -> None:
    assert sessions.finish_early_confirmation(_counts(kept=20, returned=60)) == (
        "Finish with 20 cards? They get the Final check now, then you can hand them off. "
        "The other 60 stay suspended and are picked first next time."
    )
    assert sessions.finish_early_confirmation(_counts(kept=20, returned=60, part_way=3)).endswith(
        " 3 of them were part-way through the current batch: that progress is dropped."
    )
    one = sessions.finish_early_confirmation(_counts(kept=1, returned=1, part_way=1))
    assert one == (
        "Finish with 1 card? They get the Final check now, then you can hand them off. "
        "The other card stays suspended and is picked first next time. "
        "1 of them was part-way through the current batch: that progress is dropped."
    )
    full = sessions.finish_early_confirmation(_counts(changed=2, missing=1))
    assert "2 cards changed in Anki since the drill, so they go back too" in full
    assert full.endswith("1 card no longer exists in Anki: left out.")
    assert "changed" not in sessions.finish_early_confirmation(_counts())
    assert "no longer" not in sessions.finish_early_confirmation(_counts())
