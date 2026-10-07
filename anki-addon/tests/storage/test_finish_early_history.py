"""A session finished early, end to end: the cut, the Final check, one history line."""

from __future__ import annotations

from pathlib import Path

import pytest
from controller_support import Clock
from finish_early_support import KEY, run_until, stopped_mid_batch, storage

from recalldrill import history_store, sessions
from recalldrill.controller import ControllerSettings
from recalldrill.sessions import finish_early, open_saved
from recalldrill.storage import ESTIMATES, Storage

NOW = 1_790_100_000_000


@pytest.fixture
def st(tmp_path: Path) -> Storage:
    return storage(tmp_path)


def test_a_finished_early_session_writes_one_line_and_no_cold_start(st: Storage) -> None:
    ctrl, _store, saved = stopped_mid_batch(st)
    # The stop recorded a cold-start value (batch 0 is complete); the cut mustn't touch it.
    at_stop = st.read_json(ESTIMATES, {})
    assert at_stop[KEY]["multiplier"] > 0
    assert history_store.read_all(st, "42") == []
    sitting_attempts = ctrl.state["stats"]["attempts"]

    cut = finish_early(saved, (), (), NOW)
    st.write_json(sessions.save_name(KEY), cut)
    ctrl2, store2 = open_saved(st, KEY, cut, ControllerSettings(deck_name="Med Term"), Clock())
    ctrl2.start()
    run_until(ctrl2, lambda c: c.finished is not None)
    assert ctrl2.finished == "complete"

    lines = history_store.read_all(st, "42")
    assert [x["type"] for x in lines] == ["session"]
    line = lines[0]
    assert line["sessionId"] == saved["addon"]["sessionId"]
    kept = [1000, 1001, 1002]
    assert [a["cid"] for a in line["anki"]] == kept
    assert [c["front"] for c in line["cards"]] == ["front0", "front1", "front2"]
    returned = line["cut"]["returned"]
    assert [r["cid"] for r in returned] == [1003, 1004, 1005]
    assert line["cut"] == store2.meta.cut
    assert line["stats"]["attempts"] >= sitting_attempts  # the sitting's totals, not split
    assert line["holdout"] == saved["addon"]["holdout"]  # the holdout goes with this session

    final = sessions.load(st, KEY)
    assert final is not None
    assert sessions.save_status(final) == "handoff"
    assert final["addon"]["historyWritten"] is True
    assert all(i["finalDone"] for i in final["items"])
    assert len(final["items"]) == 3
    assert st.read_json(ESTIMATES, {}) == at_stop  # no cold-start value written for the cut


def test_stopping_a_cut_session_writes_no_cold_start_either(st: Storage) -> None:
    _ctrl, _store, saved = stopped_mid_batch(st)
    before = st.read_json(ESTIMATES, {})
    cut = finish_early(saved, (), (), NOW)
    st.write_json(sessions.save_name(KEY), cut)
    ctrl, _ = open_saved(st, KEY, cut, ControllerSettings(deck_name="Med Term"), Clock())
    ctrl.start()
    ctrl.save_and_stop()
    assert st.read_json(ESTIMATES, {}) == before


def test_an_uncut_session_still_records_its_cold_start(st: Storage) -> None:
    _ctrl, _store, _saved = stopped_mid_batch(st)
    assert KEY in st.read_json(ESTIMATES, {})


